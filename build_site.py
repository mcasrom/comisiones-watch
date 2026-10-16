#!/usr/bin/env python3
"""Generador estático del observatorio de comisiones.

Parte de la SQLite (`ingest_csv.py` rellena composición; `ingest_opendata.py`
rellena iniciativas, leyes aprobadas e intervenciones) y produce el índice, una
ficha por comisión, la metodología y `llms.txt`.

Dimensiones publicadas por comisión: **constitución, reuniones, trabajos,
resultados** y **coste estimado**. El coste sigue sin publicarse mientras todas
las tarifas estén `pendiente_validacion`. Todo lo que no tiene dato se marca
como no disponible; nada se inventa. Reejecutable, sin red.
"""
import csv
import html
import json
import shutil
import sqlite3
from pathlib import Path

from adapters.congreso import (
    composition_metadata,
    discover_commissions,
    parse_composition_payload,
)
from metrics import commission_metrics
from ingest_opendata import DDL as OPENDATA_DDL

BASE = Path(__file__).resolve().parent
CUTOFF = "2026-10-12"
LISTING_SOURCE = "https://www.congreso.es/es/comisiones"
COMPOSITION_SOURCE = (
    "https://www.congreso.es/es/organos/composicion-en-la-legislatura"
    "?p_p_id=organos&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    "&_organos_selectedLegislatura=XV&_organos_selectedOrganoSup=1"
    "&_organos_selectedSuborgano=301"
)
INICIATIVAS_SOURCE = "https://www.congreso.es/es/opendata/iniciativas"
INTERVENCIONES_SOURCE = "https://www.congreso.es/es/opendata/intervenciones"
TARIFF_SOURCES = {
    "congreso": "https://www.congreso.es/es/cem/regecodip",
    "senado": "https://www.senado.es/web/composicionorganizacion/senadores/regimeneconomico/index.html",
}
CSS = """
:root{color-scheme:light dark;--fg:#111;--bg:#fff;--muted:#555;--line:#ccc;--card:#f6f6f6;--accent:#0b5}
@media (prefers-color-scheme:dark){:root{--fg:#eee;--bg:#111;--muted:#bbb;--line:#444;--card:#1b1b1b;--accent:#3c9}}
body{font-family:system-ui,sans-serif;line-height:1.55;color:var(--fg);background:var(--bg);margin:0}
main{max-width:68rem;margin:auto;padding:1rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.75rem}
.kpi{border:1px solid var(--line);border-radius:.6rem;padding:.75rem;background:var(--card)}
.kpi b{display:block;font-size:1.4rem}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid var(--line);padding:.4rem;text-align:left;vertical-align:top}
tfoot td{font-weight:600}
.skip{position:absolute;left:-999px}
.skip:focus{left:.5rem;top:.5rem;background:var(--fg);color:var(--bg);padding:.5rem}
a:focus-visible,button:focus-visible,input:focus-visible{outline:.15rem solid currentColor}
.muted{color:var(--muted)}
"""


def _page(title, body, description):
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#contenido">Saltar al contenido</a>
<main id="contenido">
{body}
</main>
</body>
</html>
"""


def build_db(root):
    """Completa la SQLite sin borrar lo ingerido por los ingestores."""
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / "comisiones.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS commissions(
          source_id TEXT PRIMARY KEY,
          chamber TEXT NOT NULL,
          kind TEXT NOT NULL,
          name TEXT NOT NULL,
          section TEXT NOT NULL,
          url TEXT NOT NULL,
          legislatura TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS composition_raw(
          id INTEGER PRIMARY KEY,
          commission_source_id TEXT NOT NULL,
          full_name TEXT NOT NULL,
          party TEXT,
          role_id TEXT NOT NULL,
          role_label TEXT NOT NULL,
          role TEXT,
          start_date TEXT,
          end_date TEXT,
          profile_url TEXT,
          needs_role_dictionary INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_seed(
          chamber TEXT NOT NULL,
          role TEXT NOT NULL,
          monthly_eur REAL NOT NULL,
          valid_from TEXT NOT NULL,
          valid_to TEXT,
          source_url TEXT NOT NULL,
          status TEXT NOT NULL,
          payments_per_year INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    con.executescript(OPENDATA_DDL)
    listing_html = (root / "tests" / "fixtures" / "congreso_comisiones.html").read_text(
        encoding="utf-8"
    )
    commissions = discover_commissions(listing_html)
    con.executemany(
        "INSERT INTO commissions VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(source_id) DO UPDATE SET "
        "chamber=excluded.chamber, kind=excluded.kind, "
        "section=excluded.section, url=excluded.url, legislatura=excluded.legislatura",
        [
            (
                item["source_id"],
                item["chamber"],
                item["kind"],
                item["name"],
                item["section"],
                item["url"],
                item["legislatura"],
            )
            for item in commissions
        ],
    )
    has_301 = con.execute(
        "SELECT COUNT(*) FROM composition_raw WHERE commission_source_id='301'"
    ).fetchone()[0]
    if not has_301:
        payload = json.loads(
            (root / "tests" / "fixtures" / "composicion_301.json").read_text(
                encoding="utf-8"
            )
        )
        rows = parse_composition_payload(payload, commission_id=301)
        con.executemany(
            "INSERT INTO composition_raw VALUES (NULL,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "301",
                    row["full_name"],
                    row["party"],
                    row["role_raw"]["id"],
                    row["role_raw"]["label"],
                    row["role"],
                    row["start_date"],
                    row["end_date"],
                    row["profile_url"],
                    int(row["needs_role_dictionary"]),
                )
                for row in rows
            ],
        )
        metadata = composition_metadata(payload)
        con.execute(
            "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("constituted_on_301", metadata["constituted_on"]),
        )
        con.execute(
            "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("closed_on_301", metadata["closed_on"] or ""),
        )
    if not con.execute("SELECT COUNT(*) FROM rate_seed").fetchone()[0]:
        with open(root / "rates_seed.csv", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                con.execute(
                    "INSERT INTO rate_seed VALUES (?,?,?,?,?,?,?,?)",
                    (
                        row["chamber"],
                        row["role"],
                        float(row["monthly_eur"]),
                        row["valid_from"],
                        row.get("valid_to") or None,
                        row["source_url"],
                        row["status"],
                        int(row["payments_per_year"]),
                    ),
                )
    for key, value in (
        ("cutoff", CUTOFF),
        ("listing_source", LISTING_SOURCE),
        ("composition_source", COMPOSITION_SOURCE),
        ("iniciativas_source", INICIATIVAS_SOURCE),
        ("intervenciones_source", INTERVENCIONES_SOURCE),
    ):
        con.execute(
            "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    con.commit()
    return con


def _unavailable(label, note="dato no disponible"):
    return (
        f"<div class=kpi><div><strong>{html.escape(label)}</strong>"
        f"<b>{html.escape(note)}</b></div></div>"
    )


def _kpi(label, value, note=""):
    suffix = f' <span class="muted">{html.escape(note)}</span>' if note else ""
    return (
        f"<div class=kpi><div><strong>{html.escape(label)}</strong>"
        f"<b>{html.escape(str(value))}</b>{suffix}</div></div>"
    )


def _int(value):
    return 0 if value is None else int(value)


def _collect_stats(con):
    """Reúne por comisión: constitución, sesiones, comparecencias, iniciativas.

    Cada sesión se clasifica por su contenido (comparecencia/debate/otro) para
    alimentar `commission_metrics` sin recalcular reglas en el generador.
    """
    stats = {}

    def slot(code):
        return stats.setdefault(
            code,
            {
                "constituted": None,
                "sessions": [],
                "speakers": 0,
                "iniciativas": 0,
                "aprobadas": 0,
                "metrics": None,
            },
        )

    for code, start in con.execute(
        "SELECT commission_source_id, MIN(start_date) FROM composition_raw"
        " WHERE start_date IS NOT NULL GROUP BY commission_source_id"
    ):
        slot(code)["constituted"] = start
    for code, start in con.execute(
        "SELECT substr(key,18), value FROM meta WHERE key LIKE 'constituted_on_%'"
    ):
        if start and slot(code)["constituted"] is None:
            slot(code)["constituted"] = start
    for code, sesion, has_comp, has_deb in con.execute(
        "SELECT commission_source_id, sesion,"
        " MAX(CASE WHEN lower(fase) LIKE '%comparecencia%'"
        "   OR lower(tipo_intervencion) LIKE '%comparecencia%' THEN 1 ELSE 0 END),"
        " MAX(CASE WHEN lower(fase) LIKE '%debate%'"
        "   OR lower(tipo_intervencion) LIKE '%debate%' THEN 1 ELSE 0 END)"
        " FROM intervenciones"
        " WHERE commission_source_id IS NOT NULL AND sesion IS NOT NULL"
        " GROUP BY commission_source_id, sesion"
    ):
        kind = "comparecencia" if has_comp else "debate" if has_deb else "otro"
        slot(code)["sessions"].append({"session_date": sesion, "kind": kind})
    for code, speakers in con.execute(
        "SELECT commission_source_id, COUNT(DISTINCT orador) FROM intervenciones"
        " WHERE commission_source_id IS NOT NULL GROUP BY commission_source_id"
    ):
        slot(code)["speakers"] = _int(speakers)
    for code, total in con.execute(
        "SELECT comision_source_id, COUNT(*) FROM iniciativas"
        " WHERE comision_source_id IS NOT NULL GROUP BY comision_source_id"
    ):
        slot(code)["iniciativas"] = _int(total)
    for code, total in con.execute(
        "SELECT comision_source_id, COUNT(*) FROM iniciativas"
        " WHERE comision_source_id IS NOT NULL"
        " AND lower(resultado_tramitacion) LIKE '%aprobado%'"
        " GROUP BY comision_source_id"
    ):
        slot(code)["aprobadas"] = _int(total)
    for code, row in stats.items():
        row["sessions"].sort(key=lambda item: item["session_date"])
        if row["constituted"]:
            row["metrics"] = commission_metrics(
                constituted_on=row["constituted"],
                sessions=row["sessions"],
                today=CUTOFF,
            )
    return stats


def build(root=BASE):
    con = build_db(root)
    web = root / "web"
    if web.exists():
        shutil.rmtree(web)
    web.mkdir()

    discovered = con.execute("SELECT COUNT(*) FROM commissions").fetchone()[0]
    with_composition = [
        row[0]
        for row in con.execute(
            "SELECT DISTINCT commission_source_id FROM composition_raw ORDER BY 1"
        ).fetchall()
    ]
    composition_rows = con.execute("SELECT COUNT(*) FROM composition_raw").fetchone()[0]
    approved = con.execute(
        "SELECT COUNT(*) FROM rate_seed WHERE status='aprobada'"
    ).fetchone()[0]
    total_iniciativas = con.execute(
        "SELECT COUNT(*) FROM iniciativas WHERE comision_source_id IS NOT NULL"
    ).fetchone()[0]
    total_intervenciones = con.execute("SELECT COUNT(*) FROM intervenciones").fetchone()[0]
    total_sesiones = con.execute(
        "SELECT COUNT(DISTINCT commission_source_id || '|' || sesion)"
        " FROM intervenciones WHERE commission_source_id IS NOT NULL AND sesion IS NOT NULL"
    ).fetchone()[0]
    total_leyes = con.execute("SELECT COUNT(*) FROM leyes_aprobadas").fetchone()[0]
    stats = _collect_stats(con)

    rows = con.execute(
        "SELECT chamber, kind, name, source_id, url FROM commissions ORDER BY name"
    ).fetchall()
    table_rows = []
    for chamber, kind, name, source_id, url in rows:
        info = stats.get(source_id, {})
        sessions = len(info.get("sessions", []))
        iniciativas = info.get("iniciativas", 0)
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(chamber)}</td><td>{html.escape(kind)}</td>"
            f"<td>{html.escape(name)}</td><td>{html.escape(source_id)}</td>"
            f"<td>{sessions if sessions else '—'}</td>"
            f"<td>{iniciativas if iniciativas else '—'}</td>"
            f"<td><a href=\"comision-{html.escape(source_id)}.html\">ficha</a>"
            f' · <a href="{html.escape(url)}">fuente</a></td></tr>'
        )
    table = "".join(table_rows)
    index_body = f"""
<h1>Comisiones: actividad, trabajos, resultados y coste</h1>
<p>Congreso de los Diputados, XV legislatura (disuelta el 6-oct-2026). Fecha de corte: {CUTOFF}.
Datos verificados de fuentes oficiales; lo que falta se marca, no se estima.</p>
<div class=kpis>
{_kpi("Comisiones", discovered)}
{_kpi("Con composición", len(with_composition), f"{composition_rows} registros")}
{_kpi("Sesiones (XV)", total_sesiones)}
{_kpi("Iniciativas (XV)", total_iniciativas, "por comisión competente")}
{_kpi("Leyes aprobadas", total_leyes)}
{_unavailable("Coste estimado", f"{approved} tarifas aprobadas")}
</div>
<p class="muted">Las sesiones se cuentan por fechas distintas de reunión del órgano en el
volcado de intervenciones ({total_intervenciones:,} intervenciones cargadas). Las iniciativas
son las que tienen cada comisión como competente. El coste no se publica mientras las
tarifas estén pendientes de validación.</p>
<p><label>Filtrar listado <input type=search data-filter placeholder="Escribe cámara, tipo o nombre"></label></p>
<table><caption>Comisiones del Congreso</caption>
<thead><tr><th>Cámara</th><th>Tipo</th><th>Nombre</th><th>Código</th><th>Sesiones</th><th>Iniciativas</th><th>Enlaces</th></tr></thead>
<tbody>{table}</tbody></table>
<p><a href="metodologia.html">Metodología y límites</a></p>
<script>
const q=document.querySelector('[data-filter]');
if(q){{
q.addEventListener('input',()=>{{
const needle=q.value.toLowerCase();
for(const row of document.querySelectorAll('tbody tr')){{
row.hidden=needle && !row.textContent.toLowerCase().includes(needle);
}}
}});
}}
</script>
"""
    (web / "index.html").write_text(
        _page(
            "Comisiones: actividad y resultados",
            index_body,
            "Observatorio de comisiones del Congreso: constitución, sesiones, iniciativas, leyes y coste.",
        ),
        encoding="utf-8",
    )

    for code in sorted(stats):
        _write_ficha(con, web, code, stats)

    _write_metodologia(con, web, stats, total_leyes)
    (web / "llms.txt").write_text(
        f"Observatorio de comisiones del Congreso (XV legislatura, corte {CUTOFF}).\n"
        f"{discovered} comisiones descubiertas; {len(with_composition)} con composición"
        f" ({composition_rows} registros).\n"
        f"{total_sesiones} sesiones, {total_iniciativas} iniciativas y {total_leyes}"
        " leyes aprobadas cargadas del opendata.\n"
        "Coste estimado: dato no disponible (tarifas pendientes de validación).\n"
        f"Fuentes: {LISTING_SOURCE} ; {INICIATIVAS_SOURCE} ; {INTERVENCIONES_SOURCE} ;"
        f" CSV de composición del Congreso ; {TARIFF_SOURCES['congreso']} .\n",
        encoding="utf-8",
    )
    con.close()
    return web


def _write_ficha(con, web, code, stats):
    name = con.execute(
        "SELECT name FROM commissions WHERE source_id=?", (code,)
    ).fetchone()[0]
    info = stats[code]
    members = con.execute(
        "SELECT full_name, party, role_label, role, start_date, end_date,"
        " profile_url FROM composition_raw"
        " WHERE commission_source_id=? ORDER BY full_name",
        (code,),
    ).fetchall()
    office = sum(1 for member in members if member[3])
    pending_roles = len(members) - office
    constituted = info["constituted"]
    metrics = info["metrics"]
    sessions = info["sessions"]
    comparecencias = sum(1 for item in sessions if item["kind"] == "comparecencia")
    last_session = sessions[-1]["session_date"] if sessions else None

    if constituted:
        constitucion = f"Constitución: {constituted}."
    else:
        constitucion = "Constitución: no consta en las fuentes cargadas."
    if sessions:
        sessions_note = (
            f"{len(sessions)} reuniones, {comparecencias} con comparecencia,"
            f" última el {last_session}."
        )
    else:
        sessions_note = "Sin reuniones cargadas de esta comisión."
    status_note = (
        f"Actividad: {metrics['status']} ({metrics['substantive_per_month']} por mes)."
        if metrics
        else ""
    )
    speakers = info["speakers"]
    member_rows = "".join(
        "<tr>"
        f"<td>{html.escape(person)}</td><td>{html.escape(party or 'no consta')}</td>"
        f"<td>{html.escape(label)}"
        + (f" ({html.escape(role)})" if role else " (pendiente de diccionario)")
        + "</td>"
        f"<td>{html.escape(start or 'no consta')}</td>"
        f"<td>{html.escape(end or 'en curso/no consta')}</td>"
        f"<td>{f'<a href=\"{html.escape(profile)}\">ficha</a>' if profile else 'sin enlace'}</td></tr>"
        for person, party, label, role, start, end, profile in members
    )
    tipo_rows = "".join(
        f"<tr><td>{html.escape(tipo or '(sin tipo)')}</td><td>{total}</td></tr>"
        for tipo, total in con.execute(
            "SELECT tipo, COUNT(*) FROM iniciativas WHERE comision_source_id=?"
            " GROUP BY tipo ORDER BY 2 DESC, 1",
            (code,),
        )
    )
    situacion_rows = "".join(
        f"<tr><td>{html.escape(situacion or '(sin dato)')}</td><td>{total}</td></tr>"
        for situacion, total in con.execute(
            "SELECT situacion_actual, COUNT(*) FROM iniciativas"
            " WHERE comision_source_id=? GROUP BY situacion_actual ORDER BY 2 DESC, 1",
            (code,),
        )
    )
    trabajos = (
        f"<p>Iniciativas competencia de la comisión: <b>{info['iniciativas']}</b>"
        f" ({info['aprobadas']} con resultado «Aprobado»).</p>"
        if info["iniciativas"]
        else "<p>Sin iniciativas cargadas con esta comisión como competente.</p>"
    )
    eje_ini = constituted or "¿?"
    ficha_body = f"""
<p><a href="index.html">Volver</a></p>
<h1>{html.escape(name)} ({html.escape(code)})</h1>
<p>{constitucion} Composición cargada: {len(members)} registros, {office} con cargo
normalizado y {pending_roles} pendientes.</p>
<h2>Reuniones</h2>
<p>{html.escape(sessions_note)} {html.escape(status_note)}
{('Comparecientes distintos: <b>%d</b>.' % speakers) if speakers else ''}</p>
<svg viewBox="0 0 600 90" role="img" aria-label="Periodo cubierto por las fuentes">
<line x1="20" y1="60" x2="580" y2="60" stroke="currentColor" stroke-width="2"/>
<circle cx="20" cy="60" r="5" fill="currentColor"/>
<circle cx="580" cy="60" r="5" fill="currentColor"/>
<text x="20" y="80">{html.escape(eje_ini)}</text>
<text x="500" y="80">{html.escape(CUTOFF)}</text>
<text x="20" y="30">{html.escape(f"{len(sessions)} fechas de reunión cargadas" if sessions else 'Sin reuniones cargadas')}</text>
</svg>
<h2>Trabajos</h2>
{trabajos}
<table><caption>Iniciativas por tipo</caption>
<thead><tr><th>Tipo</th><th>Total</th></tr></thead>
<tbody>{tipo_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
<h2>Resultados</h2>
<table><caption>Iniciativas por situación</caption>
<thead><tr><th>Situación</th><th>Total</th></tr></thead>
<tbody>{situacion_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
<h2>Coste</h2>
<p>Coste publicado: <b>dato no disponible</b> porque todas las tarifas están pendientes de
validación (ver <a href="metodologia.html">metodología</a>).</p>
<h2>Composición oficial</h2>
<table><caption>Personas en cargos o adscripciones públicas</caption>
<thead><tr><th>Nombre</th><th>Grupo</th><th>Cargo</th><th>Alta</th><th>Baja</th><th>Fuente</th></tr></thead>
<tbody>{member_rows}</tbody></table>
<p>Fuente: listado oficial del Congreso, CSV de composición, e iniciativas e
intervenciones del opendata del Congreso.</p>
"""
    (web / f"comision-{code}.html").write_text(
        _page(
            f"{name}: actividad y resultados",
            ficha_body,
            "Ficha de comisión: constitución, reuniones, trabajos, resultados y composición.",
        ),
        encoding="utf-8",
    )


def _write_metodologia(con, web, stats, total_leyes):
    rates = con.execute(
        "SELECT chamber, role, monthly_eur, valid_from, source_url, status FROM rate_seed ORDER BY chamber, role"
    ).fetchall()
    rate_rows = "".join(
        "<tr>"
        f"<td>{html.escape(chamber)}</td><td>{html.escape(role)}</td>"
        f"<td>{monthly:.2f}</td><td>{html.escape(valid_from)}</td>"
        f"<td><a href=\"{html.escape(source)}\">fuente</a></td>"
        f"<td>{html.escape(status)}</td></tr>"
        for chamber, role, monthly, valid_from, source, status in rates
    )
    method_body = f"""
<p><a href="index.html">Volver</a></p>
<h1>Metodología y límites</h1>
<p>Fecha de corte: {CUTOFF}. XV legislatura, disuelta el 6-oct-2026: los volcados del
opendata son un <b>estado congelado</b> del final de legislatura.</p>
<h2>Qué publica cada dimensión y de dónde sale</h2>
<ul>
<li><b>Constitución</b>: fecha de alta más antigua de la composición oficial
(<code>FechaAlta</code>).</li>
<li><b>Reuniones</b>: fechas distintas de sesión del órgano en el volcado de
intervenciones (<a href="{INTERVENCIONES_SOURCE}">opendata/intervenciones</a>). Una
«reunión» es una fecha; la comparecencia se marca por la fase o el tipo de intervención.</li>
<li><b>Trabajos</b>: iniciativas cuya comisión competente es la comisión
(<a href="{INICIATIVAS_SOURCE}">opendata/iniciativas</a>: proyectos de ley,
proposiciones de ley y propuestas de reforma).</li>
<li><b>Resultados</b>: situación actual de esas iniciativas y las leyes aprobadas
({total_leyes} leyes de la XV).</li>
<li><b>Coste</b>: mensualidad oficial × meses × 14/12. <b>No se publica</b> mientras las
tarifas estén en <code>pendiente_validacion</code>.</li>
</ul>
<h2>Consultas reproducibles</h2>
<pre><code>SELECT COUNT(*) FROM commissions;
SELECT COUNT(DISTINCT commission_source_id || '|' || sesion) FROM intervenciones
  WHERE commission_source_id IS NOT NULL;
SELECT comision_source_id, COUNT(*) FROM iniciativas GROUP BY 1;
SELECT COUNT(*) FROM leyes_aprobadas;
SELECT COUNT(*) FROM rate_seed WHERE status='aprobada';</code></pre>
<h2>Emparejado de nombres</h2>
<p>El opendata usa nombres abreviados («Eco. Social», «S. Social», «Parlam.»). Se normalizan
y se casan con el nombre oficial; las comisiones de investigación se casan por palabras
significativas. Lo que no casa queda visible en <code>data/opendata_manifest.json</code> y no se
atribuye a ciegas.</p>
<h2>Semilla de tarifas</h2>
<table><caption>Tarifas oficiales pendientes de validación</caption>
<thead><tr><th>Cámara</th><th>Cargo</th><th>€/mes</th><th>Vigencia</th><th>Fuente</th><th>Estado</th></tr></thead>
<tbody>{rate_rows}</tbody></table>
<h2>Limitaciones conocidas</h2>
<ul>
<li>Senado con acceso automatizado bloqueado; sus tarifas no se han podido descargar.</li>
<li>Una «reunión» cuenta por fecha; no distingue sesión ordinaria de extraordinaria.</li>
<li>Las leyes aprobadas no se reparten por comisión en la fuente; se muestran en conjunto.</li>
<li>Comisiones de investigación solapadas (suministro eléctrico del 28-abr-2025) pueden
compartir etiqueta en el opendata: si el emparejado es ambiguo, queda registrado.</li>
</ul>
"""
    (web / "metodologia.html").write_text(
        _page(
            "Metodología del observatorio de comisiones",
            method_body,
            "Cómo se calcula cada cifra y qué falta.",
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    print(build())
