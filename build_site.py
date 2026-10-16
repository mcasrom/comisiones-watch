#!/usr/bin/env python3
"""Generador estático mínimo del piloto de comisiones.

Parte de la SQLite piloto (rellenada por `ingest_csv.py` con CSV verificados)
y la completa con el descubrimiento del listado y la muestra 301 solo donde
falta dato. Genera índice, una ficha por comisión con composición, metodología
y `llms.txt`. No hace red, no publica costes con tarifas pendientes y marca
como no disponible todo lo que aún no tiene muestra válida. Reejecutable.
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

BASE = Path(__file__).resolve().parent
CUTOFF = "2026-10-12"
LISTING_SOURCE = "https://www.congreso.es/es/comisiones"
COMPOSITION_SOURCE = (
    "https://www.congreso.es/es/organos/composicion-en-la-legislatura"
    "?p_p_id=organos&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    "&_organos_selectedLegislatura=XV&_organos_selectedOrganoSup=1"
    "&_organos_selectedSuborgano=301"
)
TARIFF_SOURCES = {
    "congreso": "https://www.congreso.es/es/cem/regecodip",
    "senado": "https://www.senado.es/web/composicionorganizacion/senadores/regimeneconomico/index.html",
}
CSS = """
:root{color-scheme:light dark;--fg:#111;--bg:#fff;--muted:#555;--line:#ccc;--card:#f6f6f6}
@media (prefers-color-scheme:dark){:root{--fg:#eee;--bg:#111;--muted:#bbb;--line:#444;--card:#1b1b1b}}
body{font-family:system-ui,sans-serif;line-height:1.55;color:var(--fg);background:var(--bg);margin:0}
main{max-width:68rem;margin:auto;padding:1rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.75rem}
.kpi{border:1px solid var(--line);border-radius:.6rem;padding:.75rem;background:var(--card)}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid var(--line);padding:.4rem;text-align:left;vertical-align:top}
.skip{position:absolute;left:-999px}
.skip:focus{left:.5rem;top:.5rem;background:var(--fg);color:var(--bg);padding:.5rem}
a:focus-visible,button:focus-visible,input:focus-visible{outline:.15rem solid currentColor}
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
    """Completa la SQLite piloto sin borrar lo ingerido (`ingest_csv.py`)."""
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
        ("sessions_loaded", "0"),
    ):
        con.execute(
            "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    con.commit()
    return con


def _unavailable(label):
    return f"<div class=kpi><div><strong>{html.escape(label)}:</strong> dato no disponible</div></div>"


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
    rows = con.execute(
        "SELECT chamber, kind, name, source_id, url FROM commissions ORDER BY name"
    ).fetchall()
    table = "".join(
        "<tr>"
        f"<td>{html.escape(chamber)}</td><td>{html.escape(kind)}</td>"
        f"<td>{html.escape(name)}</td><td>{html.escape(source_id)}</td>"
        f"<td><a href=\"{html.escape(url)}\">fuente</a>"
        + (
            f' · <a href="comision-{html.escape(source_id)}.html">ficha</a>'
            if source_id in with_composition
            else " · <i>sin ficha (sin composición cargada)</i>"
        )
        + "</td></tr>"
        for chamber, kind, name, source_id, url in rows
    )
    index_body = f"""
<h1>Comisiones: actividad frente a coste</h1>
<p>Piloto con datos verificados. Fecha de corte: {CUTOFF}.</p>
<div class=kpis>
{_unavailable("Coste estimado publicado")}
{_unavailable("Comisiones sin actividad verificable")}
{_unavailable("Días medios sin sesión")}
</div>
<p>Cobertura del piloto: {discovered} comisiones descubiertas, {len(with_composition)} con composición cargada ({composition_rows} registros) y {approved} tarifas aprobadas. Las tarifas están pendientes de validación y no hay sesiones cargadas.</p>
<p><label>Filtrar listado <input type=search data-filter placeholder="Escribe cámara, tipo o nombre"></label></p>
<table><caption>Comisiones descubiertas en el Congreso</caption>
<thead><tr><th>Cámara</th><th>Tipo</th><th>Nombre</th><th>Código</th><th>Enlaces</th></tr></thead>
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
        _page("Comisiones: piloto", index_body, "Piloto de vigilancia de comisiones con datos verificados."),
        encoding="utf-8",
    )

    for code in with_composition:
        name = con.execute(
            "SELECT name FROM commissions WHERE source_id=?", (code,)
        ).fetchone()[0]
        members = con.execute(
            "SELECT full_name, party, role_label, role, start_date, end_date,"
            " profile_url FROM composition_raw"
            " WHERE commission_source_id=? ORDER BY full_name",
            (code,),
        ).fetchall()
        office = sum(1 for member in members if member[3])
        pending = len(members) - office
        constituted = con.execute(
            "SELECT value FROM meta WHERE key=?", (f"constituted_on_{code}",)
        ).fetchone()
        constituted = constituted[0] if constituted else None
        if constituted:
            metrics = commission_metrics(
                constituted_on=constituted, sessions=[], today=CUTOFF
            )
            estado = (
                f"Estado de actividad: {metrics['status']} porque aún no hay"
                " sesiones cargadas."
            )
            constitucion = f"Constitución: {constituted}."
            eje_ini = constituted
        else:
            estado = "Actividad: dato no disponible (sin fecha de constitución ni sesiones cargadas)."
            constitucion = "Constitución: no consta."
            eje_ini = "¿?"
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
        ficha_body = f"""
<p><a href="index.html">Volver</a></p>
<h1>{html.escape(name)} ({html.escape(code)})</h1>
<p>{constitucion} Composición cargada: {len(members)} registros, {office} con cargo normalizado y {pending} pendientes. {estado}</p>
<h2>Actividad y coste</h2>
<p>Sesiones de fondo cargadas: 0. Coste publicado: dato no disponible porque todas las tarifas están pendientes de validación.</p>
<svg viewBox="0 0 600 120" role="img" aria-label="Línea temporal sin sesiones cargadas">
<line x1="20" y1="90" x2="580" y2="90" stroke="currentColor" stroke-width="2"/>
<text x="20" y="110">{html.escape(eje_ini)}</text>
<text x="500" y="110">{html.escape(CUTOFF)}</text>
<text x="20" y="30">Sin sesiones cargadas</text>
</svg>
<h2>Composición oficial</h2>
<table><caption>Personas en cargos o adscripciones públicas</caption>
<thead><tr><th>Nombre</th><th>Grupo</th><th>Cargo</th><th>Alta</th><th>Baja</th><th>Fuente</th></tr></thead>
<tbody>{member_rows}</tbody></table>
<p>Fuente: listado oficial del Congreso y CSV de composición descargado del navegador.</p>
"""
        (web / f"comision-{code}.html").write_text(
            _page(
                f"{name}: ficha piloto",
                ficha_body,
                "Ficha piloto con composición oficial y límites.",
            ),
            encoding="utf-8",
        )

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
<p>Fecha de corte: {CUTOFF}. Este piloto no publica costes porque las 10 tarifas están en <code>pendiente_validacion</code> y no hay sesiones cargadas.</p>
<h2>Consultas reproducibles</h2>
<pre><code>SELECT COUNT(*) FROM commissions;
SELECT DISTINCT commission_source_id FROM composition_raw;
SELECT COUNT(*) FROM rate_seed WHERE status='aprobada';
SELECT chamber, role, monthly_eur, valid_from, source_url, status
FROM rate_seed ORDER BY chamber, role;</code></pre>
<h2>Cálculo cuando haya datos válidos</h2>
<p>Coste estimado = mensualidad nominal × meses × 14/12. Se muestran nominal y anualizado. Sesión de fondo = comparecencia o debate. Periodo de gracia = 90 días. Clasificación contra la mediana del mismo tipo y cámara.</p>
<h2>Semilla de tarifas</h2>
<table><caption>Tarifas oficiales pendientes de validación</caption>
<thead><tr><th>Cámara</th><th>Cargo</th><th>€/mes</th><th>Vigencia</th><th>Fuente</th><th>Estado</th></tr></thead>
<tbody>{rate_rows}</tbody></table>
<h2>Limitaciones conocidas</h2>
<ul>
<li>Senado con acceso automatizado bloqueado; sus tarifas no se han podido descargar.</li>
<li>El recurso AJAX del Congreso es inestable; la composición usada es una muestra verificada.</li>
<li>Faltan incompatibilidades entre cargos múltiples y sesiones reales.</li>
<li>Canal de corrección pendiente de buzón público; mientras tanto, los fallos deben quedar visibles.</li>
</ul>
"""
    (web / "metodologia.html").write_text(
        _page("Metodología del piloto de comisiones", method_body, "Cómo se calcula cada cifra y qué falta."),
        encoding="utf-8",
    )
    (web / "llms.txt").write_text(
        f"Piloto comisiones: {discovered} comisiones descubiertas,"
        f" {len(with_composition)} con composición cargada ({composition_rows} registros),"
        f" {approved} tarifas aprobadas.\n"
        "Coste y actividad publicados: dato no disponible.\n"
        f"Fuentes: {LISTING_SOURCE} ; CSV de composición del Congreso ; {TARIFF_SOURCES['congreso']} .\n",
        encoding="utf-8",
    )
    con.close()
    return web


if __name__ == "__main__":
    print(build())
