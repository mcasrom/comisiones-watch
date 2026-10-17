#!/usr/bin/env python3
"""Generador estático del observatorio de comisiones.

Parte de la SQLite (`ingest_csv.py` rellena composición; `ingest_opendata.py`
rellena iniciativas, leyes aprobadas e intervenciones) y produce el índice, una
ficha por comisión, la metodología y `llms.txt`.

Dimensiones publicadas por comisión: **constitución, actividad y
resultados** y **coste estimado**. El coste sigue sin publicarse mientras todas
las tarifas estén `pendiente_validacion`. Todo lo que no tiene dato se marca
como no disponible; nada se inventa. Reejecutable, sin red.
"""
import csv
import html
import json
import re
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
SITE = "https://comisiones.pruebapublica.com"
REPO = "https://github.com/mcasrom/comisiones-watch"
SOURCE = "https://www.congreso.es/es/opendata"
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
.roles{margin:0;padding-left:1.1rem}
.tabs{display:flex;flex-wrap:wrap;gap:.4rem;margin:0 0 1rem}
.tabs button,.tabs a{border:1px solid var(--line);border-radius:999px;padding:.3rem .8rem;background:var(--bg);color:var(--fg);font:inherit;cursor:pointer;text-decoration:none}
.tabs .on{background:var(--accent);color:#fff;border-color:var(--accent)}
.life{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:.4rem}
.life li{border:1px solid var(--line);border-radius:999px;padding:.2rem .6rem;font-size:.9rem}
.life .ok{border-color:#0b5}
.life .na{color:var(--muted)}
.hero{border-bottom:1px solid var(--line);padding-bottom:1rem;margin-bottom:1rem}
.hero .lead{font-size:1.05rem;margin:.3rem 0}
.hero .big{font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin:.7rem 0}
.chips .chip{padding:.15rem .55rem}
.ctas{display:flex;flex-wrap:wrap;gap:.5rem;margin:.8rem 0}
.cta{display:inline-block;border:1px solid var(--accent);border-radius:999px;padding:.35rem .9rem;text-decoration:none;color:var(--accent);font-weight:600}
.cta.primary{background:var(--accent);color:#fff}
.qa-list .item{border-bottom:1px solid var(--line);padding:.8rem 0}
.qa-list h2{font-size:1.05rem;margin:0 0 .25rem}
.qa-list p{margin:0 0 .3rem}
footer.site{border-top:1px solid var(--line);margin-top:2rem;padding:1.5rem 1rem;text-align:center;color:var(--muted);font-size:.9rem}
footer.site .wrap{max-width:68rem;margin:auto}
footer.site a{color:var(--accent)}
header.site{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line)}
header.site .wrap{max-width:68rem;margin:auto;display:flex;align-items:center;gap:.8rem;padding:.6rem 1rem;flex-wrap:wrap}
header.site .brand{font-weight:700;text-decoration:none;color:var(--fg);font-size:1.05rem}
header.site .brand .sub{color:var(--muted);font-weight:400;font-size:.85rem}
header.site nav{display:flex;flex-wrap:wrap;gap:.55rem;margin-left:auto}
header.site nav a,header.site nav button{border:0;background:none;color:var(--fg);font:inherit;font-size:.9rem;cursor:pointer;text-decoration:none;padding:.15rem .3rem}
header.site nav a:hover,header.site nav button:hover{color:var(--accent)}
header.site nav .on{color:var(--accent);font-weight:700}
.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 .4em;font-size:.8em;color:var(--muted)}
.cover{height:.5rem;background:var(--card);border:1px solid var(--line);border-radius:999px;overflow:hidden;max-width:18rem}
.cover>span{display:block;height:100%;background:var(--accent)}
"""

DISSOLUTION = "2026-10-06"
STATUS_ES = {
    "periodo_gracia": "periodo de gracia",
    "sin_actividad": "sin actividad registrada",
    "sin_clasificar": "reuniones sin comparecencia/debate identificados",
    "actividad_baja": "actividad baja",
    "actividad_normal": "actividad normal",
}
GROUP_NAMES = {
    "GP": "Grupo Parlamentario Popular (Congreso)",
    "GS": "Grupo Parlamentario Socialista (Congreso)",
    "GVOX": "Grupo Parlamentario VOX (Congreso)",
    "GSUMAR": "Grupo Parlamentario Sumar (Congreso)",
    "GJxCAT": "Grupo Parlamentario Junts per Catalunya (Congreso)",
    "GR": "Grupo Parlamentario Republicano (Congreso)",
    "SGPP": "Grupo Parlamentario Popular (Senado)",
    "SGPS": "Grupo Parlamentario Socialista (Senado)",
    "SGPIC": "Grupo Parlamentario Izquierda Confederal (Senado)",
    "SGPERB": "Grupo Parlamentario Esquerra Republicana-EH Bildu (Senado)",
    "SGPV": "Grupo Parlamentario Vasco (Senado)",
}
INCOMPLETE = {
    "307": "1 sesión registrada; posible dato incompleto",
    "311": "0 sesiones registradas; posible dato incompleto",
    "313": "0 sesiones registradas; posible dato incompleto",
    "314": "0 sesiones registradas; posible dato incompleto",
    "363": "0 sesiones registradas; posible dato incompleto",
    "364": "0 sesiones registradas; posible dato incompleto",
    "369": "0 sesiones registradas; posible dato incompleto",
}
OVERLAPS = {
    "362": "Comisión homónima/solapada: 362, 363 y 364 abordan el apagón del 28-abr-2025.",
    "363": "Comisión homónima/solapada: 362, 363 y 364 abordan el apagón del 28-abr-2025.",
    "364": "Comisión homónima/solapada: 362, 363 y 364 abordan el apagón del 28-abr-2025.",
    "311": "Comisión homónima: 311 «Comisión del Estatuto» y 313 «Comisión del Estatuto de los Diputados».",
    "313": "Comisión homónima: 311 «Comisión del Estatuto» y 313 «Comisión del Estatuto de los Diputados».",
}
DATA_LEGEND = ('<p class="muted">Estado del dato: 🟢 oficial · 🔵 derivado de datos oficiales · '
               '🟡 pendiente de validación · ⚪ no consta en la fuente · 🔴 no se publica (decisión editorial).</p>')


def _page(title, body, description, *, url="", breadcrumbs=None, og_image="/og.png", noindex=False, is_index=False):
    canonical = SITE + url if url else SITE + "/"
    og = SITE + og_image
    robots = '<meta name="robots" content="noindex,follow">' if noindex else ""
    crumb_json = ""
    if breadcrumbs:
        items = ",".join(
            '{"@type":"ListItem","position":%d,"name":%s,"item":%s}'
            % (index + 1, json.dumps(name, ensure_ascii=False), json.dumps(SITE + path, ensure_ascii=False))
            for index, (name, path) in enumerate(breadcrumbs)
        )
        crumb_json = (
            '<script type="application/ld+json">{"@context":"https://schema.org",'
            '"@type":"BreadcrumbList","itemListElement":[' + items + "]}</script>"
        )
    if is_index:
        section_nav = (
            '<button data-goto="preguntas" class="on">Preguntas</button>'
            '<button data-goto="resumen">Resumen</button>'
            '<button data-goto="comisiones">Comisiones</button>'
            '<button data-goto="cruces">Cruces</button>'
        )
    else:
        section_nav = (
            '<a href="index.html#preguntas">Preguntas</a>'
            '<a href="index.html#resumen">Resumen</a>'
            '<a href="index.html#comisiones">Comisiones</a>'
            '<a href="index.html#cruces">Cruces</a>'
        )
    header = f"""
<header class="site">
<div class="wrap">
<a class="brand" href="index.html">Comisiones <span class="sub">XV legislatura</span></a>
<span class="chip">corte {html.escape(CUTOFF)}</span>
<nav aria-label="Secciones">
{section_nav}
<a href="personas.html">Personas</a>
<a href="metodologia.html">Metodología</a>
<a href="publicable.html">Qué es publicable</a>
</nav>
</div>
</header>
"""
    footer = f"""
<footer class="site">
<div class="wrap">
<p><strong>Comisiones</strong> — observatorio de datos abiertos del Congreso de los Diputados ·
XV legislatura · fecha de corte {html.escape(CUTOFF)}.</p>
<p>
<a href="{html.escape(REPO)}" target="_blank" rel="noopener">Código en GitHub</a> ·
<a href="metodologia.html">Metodología</a> ·
<a href="publicable.html">Qué es publicable</a> ·
<a href="personas.html">Personas</a> ·
<a href="datos.csv">Descargar CSV</a> ·
<a href="{html.escape(SOURCE)}" target="_blank" rel="noopener">Fuente: Congreso</a> ·
<a href="https://pruebapublica.com" target="_blank" rel="noopener">Ecosistema Prueba Pública</a>
</p>
<p>Código abierto bajo <a href="https://www.gnu.org/licenses/agpl-3.0.html" target="_blank" rel="noopener">AGPL-3.0</a>.
Datos oficiales del Congreso; lo que falta se marca, no se estima. Sin cookies ni rastreo.</p>
</div>
</footer>
"""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{html.escape(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Comisiones">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:url" content="{html.escape(canonical)}">
<meta property="og:image" content="{html.escape(og)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(title)}">
<meta name="twitter:description" content="{html.escape(description)}">
<meta name="twitter:image" content="{html.escape(og)}">
{robots}
{crumb_json}
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#contenido">Saltar al contenido</a>
{header}
<main id="contenido">
{body}
</main>
{footer}
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


def _svg_sessions(rows, limit=15):
    """Barras horizontales de sesiones por comisión (solo las que tienen >0)."""
    rows = [(name, value) for name, value in rows if value > 0]
    rows.sort(key=lambda item: -item[1])
    rows = rows[:limit]
    if not rows:
        return '<p class="muted">Sin sesiones cargadas.</p>'
    width, bar_h, gap, left = 720, 22, 6, 270
    max_v = max(value for _, value in rows) or 1
    height = 16 + len(rows) * (bar_h + gap)
    parts = []
    for index, (name, value) in enumerate(rows):
        y = 12 + index * (bar_h + gap)
        bar_w = max(4, round(value / max_v * (width - left - 46)))
        label = html.escape(name[:46] + ("…" if len(name) > 46 else ""))
        parts.append(f'<text x="0" y="{y + 15}" font-size="12" fill="#334155">{label}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w}" height="{bar_h}" rx="3" fill="#0b5"/>')
        parts.append(f'<text x="{left + bar_w + 6}" y="{y + 15}" font-size="12" font-weight="bold" fill="#0f172a">{value}</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Sesiones por comisión (top {len(rows)})">' + "".join(parts) + "</svg>"
    )


CONGRESS_GROUPS = ["GP", "GS", "GVOX", "GSUMAR", "GR", "GJxCAT", "GMx", "GEH Bildu"]
GROUP_LABELS = {
    "GP": "Populares", "GS": "Socialistas", "GVOX": "VOX", "GSUMAR": "Sumar",
    "GR": "Republicano", "GJxCAT": "Junts", "GMx": "Mixto", "GEH Bildu": "EH Bildu",
}


def _months(start, end):
    year, month = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (year, month) <= (ey, em):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def _svg_calendar(con):
    """Heatmap comisión × mes (sesiones distintas por mes)."""
    data = {}
    for code, month, n in con.execute(
        "SELECT commission_source_id, substr(sesion,1,7), COUNT(DISTINCT sesion)"
        " FROM intervenciones WHERE commission_source_id IS NOT NULL AND sesion IS NOT NULL"
        " GROUP BY 1,2"
    ):
        data.setdefault(code, {})[month] = n
    names = {code: name for code, name in con.execute("SELECT source_id, name FROM commissions")}
    codes = sorted(data, key=lambda code: -sum(data[code].values()))
    if not codes:
        return '<p class="muted">Sin sesiones cargadas.</p>'
    months = _months("2023-08", "2026-09")
    left, top, cw, ch = 210, 30, 15, 15
    width = left + len(months) * cw + 10
    height = top + len(codes) * ch + 30
    parts = []
    for index, month in enumerate(months):
        if month.endswith("-01") or index == 0:
            parts.append(
                f'<text x="{left + index * cw}" y="12" font-size="9" fill="#64748b" '
                f'transform="rotate(-45 {left + index * cw} 12)">{month[2:]}</text>'
            )
    for row, code in enumerate(codes):
        y = top + row * ch
        label = html.escape(names.get(code, code)[:30])
        parts.append(f'<text x="0" y="{y + 11}" font-size="9" fill="#334155">{label}</text>')
        for col, month in enumerate(months):
            n = data[code].get(month, 0)
            if n:
                opacity = min(1.0, 0.20 + n / 5 * 0.80)
                fill = f'fill="#0b5" opacity="{opacity:.2f}"'
            else:
                fill = 'fill="#eef2f3"'
            parts.append(f'<rect x="{left + col * cw}" y="{y}" width="{cw - 2}" height="{ch - 2}" {fill}/>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Sesiones por comisión y mes">' + "".join(parts) + "</svg>"
    )


def _svg_approved(rows, limit=10):
    """Iniciativas aprobadas por comisión (solo comisiones con >0)."""
    rows = [(name, value) for name, value in rows if value > 0]
    rows.sort(key=lambda item: -item[1])
    rows = rows[:limit]
    if not rows:
        return '<p class="muted">Sin iniciativas aprobadas con comisión atribuida.</p>'
    width, bar_h, gap, left = 720, 22, 6, 270
    max_v = max(value for _, value in rows) or 1
    height = 16 + len(rows) * (bar_h + gap)
    parts = []
    for index, (name, value) in enumerate(rows):
        y = 12 + index * (bar_h + gap)
        bar_w = max(4, round(value / max_v * (width - left - 46)))
        label = html.escape(name[:46] + ("…" if len(name) > 46 else ""))
        parts.append(f'<text x="0" y="{y + 15}" font-size="12" fill="#334155">{label}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w}" height="{bar_h}" rx="3" fill="#2563eb"/>')
        parts.append(f'<text x="{left + bar_w + 6}" y="{y + 15}" font-size="12" font-weight="bold" fill="#0f172a">{value}</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Iniciativas aprobadas por comisión">' + "".join(parts) + "</svg>"
    )


ROLE_COLORS = {
    "presidente": "#b91c1c",
    "vicepresidente": "#ea580c",
    "secretario": "#7c3aed",
    "portavoz": "#2563eb",
    "portavoz_adjunto": "#0ea5e9",
    "vocal": "#0b5",
    "adscrito": "#94a3b8",
}
ROLE_ORDER = ["presidente", "vicepresidente", "secretario", "portavoz", "portavoz_adjunto", "vocal", "adscrito"]


def _svg_matrix(con, limit=40):
    """Matriz persona × comisión, color por rol (top N personas por nº de comisiones)."""
    rows = con.execute(
        "SELECT full_name, party, role, commission_source_id FROM composition_raw"
    ).fetchall()
    people = {}
    for person, party, role, code in rows:
        p = people.setdefault(person, {"party": party, "commissions": {}})
        current = p["commissions"].get(code)
        try:
            new_rank = ROLE_ORDER.index(role)
        except ValueError:
            new_rank = len(ROLE_ORDER)
        try:
            old_rank = ROLE_ORDER.index(current)
        except ValueError:
            old_rank = len(ROLE_ORDER)
        if code not in p["commissions"] or new_rank < old_rank:
            p["commissions"][code] = role
    codes = sorted({row[3] for row in rows})
    top = sorted(people.items(), key=lambda kv: (-len(kv[1]["commissions"]), kv[0]))[:limit]
    if not top or not codes:
        return '<p class="muted">Sin datos de composición.</p>'
    left, top_margin, cw, ch = 230, 30, 13, 13
    width = left + len(codes) * cw + 10
    height = top_margin + len(top) * ch + 40
    parts = []
    for col, code in enumerate(codes):
        parts.append(
            f'<text x="{left + col * cw + 4}" y="12" font-size="8" fill="#64748b" '
            f'transform="rotate(-90 {left + col * cw + 4} 12)">{html.escape(code)}</text>'
        )
    for row_index, (person, p) in enumerate(top):
        y = top_margin + row_index * ch
        label = f"{person[:34]} ({p['party'] or '?'})"
        parts.append(f'<text x="0" y="{y + 10}" font-size="9" fill="#334155">{html.escape(label)}</text>')
        for col, code in enumerate(codes):
            role = p["commissions"].get(code)
            if role is None:
                continue
            color = ROLE_COLORS.get(role, "#cbd5e1")
            parts.append(
                f'<rect x="{left + col * cw}" y="{y}" width="{cw - 2}" height="{ch - 2}" '
                f'fill="{color}"><title>{html.escape(person)} · {html.escape(code)} · {html.escape(role or "sin cargo")}</title></rect>'
            )
    legend = " ".join(
        f'<span style="display:inline-block;width:.7rem;height:.7rem;background:{color};margin-right:.2rem"></span>{role}'
        for role, color in ROLE_COLORS.items()
    )
    return (
        f'<p class="muted" style="font-size:.85rem">{legend}</p>'
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Personas por comisión y rol">' + "".join(parts) + "</svg>"
    )


def _svg_groups(con):
    """Miembros en comisiones vs intervenciones, por grupo del Congreso."""
    groups = set(CONGRESS_GROUPS)
    seats = {}
    for party, n in con.execute(
        "SELECT party, COUNT(DISTINCT full_name) FROM composition_raw GROUP BY party"
    ):
        if party in groups:
            seats[party] = n
    interventions = {}
    for (speaker,) in con.execute(
        "SELECT orador FROM intervenciones WHERE commission_source_id IS NOT NULL AND orador IS NOT NULL"
    ):
        match = re.search(r"\(([^)]+)\)\s*$", speaker or "")
        party = match.group(1) if match else None
        if party in groups:
            interventions[party] = interventions.get(party, 0) + 1
    order = sorted(groups, key=lambda g: -interventions.get(g, 0))
    if not any(interventions.get(g) for g in order):
        return '<p class="muted">Sin datos de intervenciones por grupo.</p>'
    max_v = max([seats.get(g, 0) for g in order] + [interventions.get(g, 0) for g in order]) or 1
    row_h, gap, left, width = 34, 10, 120, 620
    height = 10 + len(order) * (row_h + gap)
    parts = []
    for index, group in enumerate(order):
        y = 6 + index * (row_h + gap)
        label = html.escape(GROUP_LABELS.get(group, group))
        parts.append(f'<text x="0" y="{y + 13}" font-size="12" fill="#334155">{label}</text>')
        for base, value, color, tag in (
            (y, seats.get(group, 0), "#94a3b8", "miembros"),
            (y + 15, interventions.get(group, 0), "#0b5", "intervenciones"),
        ):
            bar_w = max(3, round(value / max_v * width))
            parts.append(f'<rect x="{left}" y="{base}" width="{bar_w}" height="12" rx="2" fill="{color}"/>')
            parts.append(
                f'<text x="{left + bar_w + 5}" y="{base + 10}" font-size="10" fill="#0f172a">'
                f'{value} {tag}</text>'
            )
    return (
        f'<svg viewBox="0 0 {left + width + 120} {height}" width="100%" role="img" '
        f'aria-label="Miembros e intervenciones por grupo">' + "".join(parts) + "</svg>"
    )


def _write_og(web, discovered, sessions, approved):
    """Tarjeta Open Graph 1200x630 (PIL)."""
    from PIL import Image, ImageDraw, ImageFont

    def font(path, size):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            return ImageFont.load_default()

    width, height = 1200, 630
    image = Image.new("RGB", (width, height), "#0f172a")
    draw = ImageDraw.Draw(image)
    serif = font("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", 54)
    sans = font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    bold = font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    draw.rectangle([0, 0, width, 10], fill="#0b5")
    draw.text((70, 110), "Comisiones del Congreso", font=serif, fill="#ffffff")
    draw.text((70, 190), "XV legislatura · datos abiertos", font=sans, fill="#94a3b8")
    draw.text((70, 290), f"{discovered} comisiones · {sessions} sesiones", font=bold, fill="#ffffff")
    draw.text((70, 350), f"{approved} iniciativas aprobadas", font=bold, fill="#0b5")
    draw.text((70, 460), "Actividad, comparecencias, personas y resultados", font=sans, fill="#cbd5e1")
    draw.text((70, 540), "comisiones.pruebapublica.com", font=sans, fill="#94a3b8")
    image.save(web / "og.png")


def _write_csv(web, rows, stats, coverage):
    with open(web / "datos.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            ["codigo", "camara", "tipo", "nombre", "sesiones", "iniciativas",
             "aprobadas", "comp_normalizada", "comp_total"]
        )
        for chamber, kind, name, code, _url in rows:
            info = stats.get(code, {})
            norm, total = coverage.get(code, (0, 0))
            writer.writerow(
                [code, chamber, kind, name, len(info.get("sessions", [])),
                 info.get("iniciativas", 0), info.get("aprobadas", 0), norm, total]
            )


def _write_publicable(web):
    body = f"""
<h1>Qué es publicable y qué no</h1>
<p>Este observatorio reutiliza <strong>datos oficiales</strong> de las cámaras y publica solo lo que
puede sostenerse con una fuente y con la normativa aplicable. No publica datos personales ajenos al
cargo ni información reservada. Esta página explica el criterio, de dónde salen los datos y qué dicen
los reglamentos y la protección de datos.</p>

<h2>De dónde salen los datos</h2>
<ul>
<li><strong>Composición</strong>: CSV oficial de composición de las comisiones del Congreso (XV legislatura).</li>
<li><strong>Actividad e iniciativas</strong>: opendata del Congreso de los Diputados (intervenciones e iniciativas).</li>
<li><strong>Senado</strong>: acceso automatizado bloqueado; no se ingiere (⚪ no consta).</li>
<li><strong>Coste</strong>: tarifas oficiales pendientes de validación; no se publica (🔴).</li>
</ul>
<p>Fecha de corte: <strong>{html.escape(CUTOFF)}</strong>. La XV legislatura está disuelta (6-oct-2026),
así que los datos son un estado congelado, no una foto en tiempo real.</p>

<h2>Qué publicamos</h2>
<ul>
<li>Datos de <strong>cargos públicos</strong> (nombre, grupo, cargo y fechas) tal como los publica el Congreso.</li>
<li>Métricas <strong>derivadas</strong> (sesiones, intervenciones, iniciativas, aprobadas), con su método y su estado de dato.</li>
<li>Datos de <strong>órganos</strong> (comisiones) y de su actividad.</li>
</ul>

<h2>Qué no publicamos y por qué</h2>
<ul>
<li><strong>Datos personales ajenos al cargo</strong> (contacto, vida privada, opiniones): fuera del interés público y del principio de minimización.</li>
<li><strong>Coste y complementos</strong>: no se publica mientras las tarifas estén en validación.</li>
<li><strong>Senado</strong>: acceso bloqueado; no se estima ni se rellena con terceros.</li>
<li><strong>Comisiones reservadas</strong> (por ejemplo, gastos reservados, 151): su actividad no se publica por su naturaleza.</li>
<li><strong>Etiquetas internas</strong> de normalización: no se muestran; solo el resultado.</li>
</ul>

<h2>Qué dicen los reglamentos</h2>
<ul>
<li><strong>Reglamento del Congreso de los Diputados</strong> y <strong>Reglamento del Senado</strong>: regulan la
publicidad de los trabajos de las cámaras y de sus comisiones. Este observatorio se limita a reutilizar
la información que las cámaras ya publican (<a href="https://www.congreso.es/" target="_blank" rel="noopener">congreso.es</a> ·
<a href="https://www.senado.es/" target="_blank" rel="noopener">senado.es</a>).</li>
<li><strong>Comisiones</strong>: la publicidad de convocatorias, órdenes del día y actas es la base de la
actividad que aquí se mide; no se deduce actividad no publicada.</li>
<li><strong>Protección de datos</strong>: <a href="https://eur-lex.europa.eu/eli/reg/2016/679/oj" target="_blank" rel="noopener">RGPD (UE) 2016/679</a>
y <a href="https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673" target="_blank" rel="noopener">LOPDGDD (LO 3/2018)</a>:
minimización, finalidad, exactitud, transparencia y seguridad. Solo se tratan datos de cargos públicos
en el ejercicio de su función; no se elaboran perfiles ni se tratan categorías especiales.</li>
</ul>

<h2>Correcciones y contacto</h2>
<p>Si detectas un error o un dato personal que no debería estar publicado, abre una incidencia en
<a href="{html.escape(REPO)}/issues" target="_blank" rel="noopener">GitHub</a>. Las correcciones se
registran y se explican.</p>
"""
    (web / "publicable.html").write_text(
        _page(
            "Qué es publicable y qué no — Comisiones",
            body,
            "Criterio de publicación, procedencia de los datos, reglamentos de las cámaras y protección de datos del observatorio de comisiones.",
            url="/publicable.html",
            breadcrumbs=[("Inicio", "/"), ("Qué es publicable", "/publicable.html")],
        ),
        encoding="utf-8",
    )


def _write_seo_files(web, codes):
    urls = [("/", "1.0"), ("/personas.html", "0.7"), ("/metodologia.html", "0.6"), ("/publicable.html", "0.6")]
    urls += [(f"/comision-{code}.html", "0.8") for code in sorted(codes)]
    entries = "".join(
        f"<url><loc>{SITE}{path}</loc><lastmod>{CUTOFF}</lastmod>"
        f"<changefreq>monthly</changefreq><priority>{priority}</priority></url>"
        for path, priority in urls
    )
    (web / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + entries
        + "</urlset>\n",
        encoding="utf-8",
    )
    (web / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n",
        encoding="utf-8",
    )
    key_path = Path("/var/www/indexnow/indexnow.key")
    if key_path.exists():
        (web / "indexnow.key").write_text(
            key_path.read_text(encoding="utf-8").strip() + "\n", encoding="utf-8"
        )


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

    coverage = {}
    for code, total, norm in con.execute(
        "SELECT commission_source_id, COUNT(*),"
        " SUM(CASE WHEN role IS NOT NULL THEN 1 ELSE 0 END)"
        " FROM composition_raw GROUP BY commission_source_id"
    ):
        coverage[code] = (int(norm or 0), int(total or 0))
    rows = con.execute(
        "SELECT chamber, kind, name, source_id, url FROM commissions ORDER BY name"
    ).fetchall()
    table_rows = []
    for chamber, kind, name, source_id, url in rows:
        info = stats.get(source_id, {})
        sessions = len(info.get("sessions", []))
        iniciativas = info.get("iniciativas", 0)
        norm, total = coverage.get(source_id, (0, 0))
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(chamber)}</td><td>{html.escape(kind)}</td>"
            f"<td>{html.escape(name)}</td><td>{html.escape(source_id)}</td>"
            f"<td>{norm}/{total}</td>"
            f"<td>{sessions}</td>"
            f"<td>{iniciativas}</td>"
            f"<td><a href=\"comision-{html.escape(source_id)}.html\">ficha</a>"
            f' · <a href="{html.escape(url)}">fuente</a></td></tr>'
        )
    table = "".join(table_rows)
    chart = _svg_sessions(
        [(name, len(stats.get(source_id, {}).get("sessions", []))) for _, _, name, source_id, _ in rows]
    )
    groups_chart = _svg_groups(con)
    (web / "calendario.svg").write_text(_svg_calendar(con), encoding="utf-8")
    calendar_chart = (
        '<img src="calendario.svg" alt="Sesiones por comisión y mes" loading="lazy" '
        'style="max-width:100%;height:auto">'
    )
    approved_chart = _svg_approved(
        [(name, stats.get(source_id, {}).get("aprobadas", 0)) for _, _, name, source_id, _ in rows]
    )
    (web / "matriz.svg").write_text(_svg_matrix(con), encoding="utf-8")
    matrix_chart = (
        '<img src="matriz.svg" alt="Personas por comisión y rol" loading="lazy" '
        'style="max-width:100%;height:auto">'
    )
    group_counts = {}
    for (speaker,) in con.execute(
        "SELECT orador FROM intervenciones WHERE commission_source_id IS NOT NULL AND orador IS NOT NULL"
    ):
        match = re.search(r"\(([^)]+)\)\s*$", speaker or "")
        if match and match.group(1) in GROUP_LABELS:
            group_counts[match.group(1)] = group_counts.get(match.group(1), 0) + 1
    top_group, top_group_n = max(group_counts.items(), key=lambda kv: kv[1], default=("—", 0))
    top_appr_name, top_appr_n = max(
        ((name, stats.get(code, {}).get("aprobadas", 0)) for _, _, name, code, _ in rows),
        key=lambda item: item[1], default=("—", 0),
    )
    no_sessions = [name for _, _, name, code, _ in rows if not stats.get(code, {}).get("sessions")]
    total_aprobadas = sum(s.get("aprobadas", 0) for s in stats.values())
    investig = [
        (name, len(stats.get(code, {}).get("sessions", [])), stats.get(code, {}).get("aprobadas", 0))
        for _, kind, name, code, _ in rows if kind == "investigacion"
    ]
    no_sessions_html = ", ".join(html.escape(name) for name in no_sessions) or "ninguna"
    investig_html = "".join(
        f"<li>{html.escape(name)} · {sesiones} sesiones · {aprobadas} aprobadas</li>"
        for name, sesiones, aprobadas in investig
    )
    faq = [
        (
            "¿Cuántas comisiones hay?",
            f"<b>{discovered}</b> comisiones descubiertas; <b>{len(with_composition)}</b> con composición cargada ({composition_rows} registros).",
            f"{discovered} comisiones descubiertas; {len(with_composition)} con composición cargada.",
            ("goto", "comisiones"),
            "Ver comisiones",
        ),
        (
            "¿Qué comisiones no se reunieron?",
            f"<b>{len(no_sessions)}</b> sin sesiones en el opendata (posible dato incompleto en algunas): {no_sessions_html}.",
            f"{len(no_sessions)} comisiones sin sesiones en el opendata (posible dato incompleto en algunas).",
            ("goto", "comisiones"),
            "Ver comisiones",
        ),
        (
            "¿Quién participa más?",
            f"El grupo con más intervenciones es <b>{html.escape(GROUP_LABELS.get(top_group, top_group))}</b> ({top_group_n}); el ranking por persona, con denominadores, está en <a href=\"personas.html\">Personas</a>. «Participa» = intervenciones, no asistencia.",
            f"El grupo con más intervenciones es {GROUP_LABELS.get(top_group, top_group)} ({top_group_n}). Participar = intervenciones, no asistencia.",
            ("href", "personas.html"),
            "Buscar persona",
        ),
        (
            "¿Qué comisiones de investigación llegaron a conclusiones?",
            "⚪ la fuente no publica dictamen/conclusiones por comisión. Se muestra su actividad y sus iniciativas aprobadas: "
            + investig_html,
            "La fuente no publica dictamen ni conclusiones por comisión.",
            ("goto", "comisiones"),
            "Ver comisiones",
        ),
        (
            "¿Qué comisión aprobó más iniciativas?",
            f"<b>{html.escape(top_appr_name)}</b> ({top_appr_n} aprobadas). La ley publicada no se atribuye por comisión (⚪ no consta).",
            f"{top_appr_name} ({top_appr_n} iniciativas aprobadas).",
            ("goto", "resumen"),
            "Ver gráficos",
        ),
        (
            "¿Cuánto trabajo hay en total?",
            f"<b>{total_sesiones}</b> sesiones, <b>{total_iniciativas}</b> iniciativas y <b>{total_aprobadas}</b> aprobadas con comisión atribuida.",
            f"{total_sesiones} sesiones, {total_iniciativas} iniciativas y {total_aprobadas} aprobadas.",
            ("goto", "resumen"),
            "Ver gráficos",
        ),
    ]

    def _faq_link(target, label):
        kind, value = target
        if kind == "href":
            return f'<a href="{value}">{html.escape(label)} →</a>'
        return f'<a href="#" data-goto="{value}">{html.escape(label)} →</a>'

    faq_items = "".join(
        f'<div class="item"><h2>{html.escape(question)}</h2>'
        f"<p>{answer}</p>{_faq_link(target, label)}</div>"
        for question, answer, _plain, target, label in faq
    )
    faq_json = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": plain},
            }
            for question, _answer, plain, _target, _label in faq
        ],
    }
    _write_og(web, discovered, total_sesiones, total_aprobadas)
    _write_csv(web, rows, stats, coverage)
    index_body = f"""
<section id="preguntas">
<div class="hero">
<h1>Comisiones del Congreso: 6 preguntas con respuesta</h1>
<p class="lead">XV legislatura, disuelta el 6-oct-2026. <span class="big">{discovered} comisiones · {total_sesiones} sesiones · {total_aprobadas} iniciativas aprobadas</span>.</p>
<div class="chips">
<span class="chip"><b>{discovered}</b> comisiones</span>
<span class="chip"><b>{total_sesiones}</b> sesiones</span>
<span class="chip"><b>{total_iniciativas}</b> iniciativas</span>
<span class="chip"><b>{total_aprobadas}</b> aprobadas</span>
<span class="chip"><b>{total_leyes}</b> leyes (sin atribuir)</span>
</div>
<div class="ctas">
<a class="cta primary" href="#" data-goto="comisiones">Explorar comisiones</a>
<a class="cta" href="personas.html">Buscar persona</a>
</div>
<p class="muted">Fecha de corte: {CUTOFF}. Lo que falta se marca (⚪), no se estima.</p>
</div>
<div class="qa-list">
{faq_items}
</div>
<h2>Calendario de actividad <span class=chip>🔵 derivado</span></h2>
<p class="muted">Cada celda = sesiones distintas de esa comisión en ese mes. Se ve cuándo dejó de reunirse cada una.</p>
{calendar_chart}
{DATA_LEGEND}
<script type="application/ld+json">{json.dumps(faq_json, ensure_ascii=False)}</script>
</section>
<section id="resumen" hidden>
<h2>Resumen: actividad y resultados</h2>
<p>Congreso de los Diputados, XV legislatura (disuelta el 6-oct-2026). Fecha de corte: {CUTOFF}.
Datos verificados de fuentes oficiales; lo que falta se marca, no se estima.</p>
<div class=kpis>
{_kpi("Comisiones", discovered)}
{_kpi("Con composición", len(with_composition), f"{composition_rows} registros")}
{_kpi("Sesiones (XV)", total_sesiones)}
{_kpi("Iniciativas (XV)", total_iniciativas, "por comisión competente")}
{_kpi("Leyes aprobadas", total_leyes)}
</div>
<p class="muted">Las sesiones se cuentan por fechas distintas de reunión del órgano en el
volcado de intervenciones ({total_intervenciones:,} intervenciones cargadas). Las iniciativas
son las que tienen cada comisión como competente. El coste no se publica mientras las
tarifas estén pendientes de validación.</p>
{DATA_LEGEND}
<h2>Sesiones por comisión <span class=chip>🔵 derivado</span></h2>
<p class="muted">Top 15 por número de fechas de reunión. La lista completa, en la pestaña «Comisiones».</p>
{chart}
<h2>Grupos: miembros en comisiones vs intervenciones <span class=chip>🔵 derivado</span></h2>
<p class="muted">«Miembros» = personas distintas con cargo en comisiones (proxy, no escaños de la Cámara). «Intervenciones» = participación, no asistencia.</p>
{groups_chart}
<h2>Iniciativas aprobadas por comisión <span class=chip>🔵 derivado</span></h2>
<p class="muted">Iniciativas competencia de la comisión con resultado «Aprobado…». La ley publicada no se atribuye por comisión (⚪ no consta).</p>
{approved_chart}
</section>
<section id="comisiones" hidden>
<h2>Comisiones</h2>
<p><label>Filtrar listado <input type=search data-filter placeholder="Escribe cámara, tipo o nombre"></label></p>
<table><caption>Comisiones del Congreso</caption>
<thead><tr><th>Cámara</th><th>Tipo</th><th>Nombre</th><th>Código</th><th>Comp. normalizada</th><th>Sesiones</th><th>Iniciativas</th><th>Enlaces</th></tr></thead>
<tbody>{table}</tbody></table>
</section>
<section id="cruces" hidden>
<h2>Cruces: personas × comisiones <span class=chip>🔵 derivado</span></h2>
<p class="muted">Top 40 personas por número de comisiones. Cada celda = cargo en esa comisión; el color indica el rol (leyenda arriba). Los códigos de columna son los de la comisión.</p>
{matrix_chart}
</section>
<p><a href="personas.html">Personas y comisiones</a> · <a href="metodologia.html">Metodología y límites</a></p>
<script>
const secs={{preguntas:document.getElementById('preguntas'),resumen:document.getElementById('resumen'),comisiones:document.getElementById('comisiones'),cruces:document.getElementById('cruces')}};
function showTab(k){{if(!secs[k])return;for(const s in secs)secs[s].hidden=s!==k;document.querySelectorAll('header.site nav [data-goto]').forEach(b=>b.classList.toggle('on',b.dataset.goto===k));}}
document.querySelectorAll('[data-goto]').forEach(b=>b.addEventListener('click',e=>{{e.preventDefault();showTab(b.dataset.goto);if(history.replaceState)history.replaceState(null,'','#'+b.dataset.goto);}}));
if(location.hash)showTab(location.hash.slice(1));
const q=document.querySelector('[data-filter]');
if(q){{q.addEventListener('input',()=>{{const needle=q.value.toLowerCase();for(const row of document.querySelectorAll('#comisiones tbody tr')){{row.hidden=needle && !row.textContent.toLowerCase().includes(needle);}}}});}}
</script>
"""
    (web / "index.html").write_text(
        _page(
            "Comisiones del Congreso: actividad, comparecencias y resultados (XV legislatura)",
            index_body,
            "Qué comisiones hay, cuáles se reunieron, quién participa y qué se aprobó en la XV legislatura. Datos oficiales con fecha de corte y cobertura declarada.",
            url="/",
            is_index=True,
        ),
        encoding="utf-8",
    )

    for code in sorted(stats):
        _write_ficha(con, web, code, stats)

    _write_personas(con, web)
    _write_metodologia(con, web, stats, total_leyes)
    _write_publicable(web)
    _write_seo_files(web, sorted(stats))
    (web / "llms.txt").write_text(
        f"Observatorio de comisiones del Congreso (XV legislatura, corte {CUTOFF}).\n"
        f"{discovered} comisiones descubiertas; {len(with_composition)} con composición"
        f" ({composition_rows} registros).\n"
        f"{total_sesiones} sesiones, {total_iniciativas} iniciativas y {total_leyes}"
        " leyes aprobadas cargadas del opendata.\n"
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
    sessions_n = len(sessions)
    per_month_all = metrics.get("sessions_per_month") if metrics else None
    if sessions:
        sessions_note = (
            f"{sessions_n} reuniones"
            + (f" ({per_month_all}/mes)" if per_month_all is not None else "")
            + f"; {comparecencias} con comparecencia identificada; última el {last_session}."
        )
    else:
        sessions_note = "Sin reuniones cargadas de esta comisión."
    if metrics:
        status_note = (
            f"Actividad: {STATUS_ES.get(metrics['status'], metrics['status'])}"
            f" ({metrics['substantive_per_month']} sesiones sustantivas/mes)."
        )
    else:
        status_note = ""
    speakers = info["speakers"]
    comparecencia_note = (
        " (la fuente no identifica comparecencias en esta comisión)"
        if sessions and comparecencias == 0 else ""
    )
    coverage_pct = round(office / len(members) * 100) if members else 0
    overlap_html = (f'<p class="muted">⚠️ {html.escape(OVERLAPS[code])}</p>' if code in OVERLAPS else "")
    reserved_html = (
        '<p><span class="chip">🔴 Órgano reservado</span> Comisión de control de los créditos '
        'destinados a gastos reservados: por su naturaleza, su actividad no se publica.</p>'
        if code == "151" else ""
    )
    incomplete_html = (
        f'<p><span class="chip">⚪ Posible dato incompleto</span> {html.escape(INCOMPLETE[code])}. '
        'No implica que la comisión no se reuniera; pendiente de auditar contra las actas oficiales.</p>'
        if code in INCOMPLETE else ""
    )
    present_groups = sorted({member[1] for member in members if member[1] in GROUP_NAMES})
    glossary_html = ""
    if present_groups:
        glossary_html = (
            '<p class="muted">Grupos: '
            + " · ".join(f"<b>{html.escape(c)}</b>: {html.escape(GROUP_NAMES[c])}" for c in present_groups)
            + ".</p>"
        )

    def _end(value):
        if not value:
            return "en curso / no consta"
        if value == DISSOLUTION:
            return f"{value} (disolución)"
        return value

    def _party(code_party):
        if code_party and code_party in GROUP_NAMES:
            return f'<abbr title="{html.escape(GROUP_NAMES[code_party])}">{html.escape(code_party)}</abbr>'
        return html.escape(code_party or "no consta")

    grouped = {}
    for person, party, label, role, start, end, profile in members:
        p = grouped.setdefault(
            person,
            {"parties": set(), "roles": [], "start": None, "end": None, "profile": None},
        )
        if party:
            p["parties"].add(party)
        p["roles"].append((label, role, start, end))
        if start and (p["start"] is None or start < p["start"]):
            p["start"] = start
        if end and (p["end"] is None or end > p["end"]):
            p["end"] = end
        if profile and not p["profile"]:
            p["profile"] = profile

    def _roles_cell(roles):
        if len(roles) == 1:
            label, role, start, end = roles[0]
            return html.escape(label or "no consta") + (f" ({html.escape(role)})" if role else "")
        items = "".join(
            "<li>"
            + html.escape(label or "no consta")
            + (f" ({html.escape(role)})" if role else "")
            + f" · {html.escape(start or 'no consta')} → {html.escape(_end(end))}</li>"
            for label, role, start, end in sorted(roles, key=lambda item: (item[2] or "", item[0] or ""))
        )
        return f"<ul class=roles>{items}</ul>"

    member_rows = "".join(
        "<tr>"
        f"<td>{html.escape(person)}</td>"
        f"<td>{' '.join(_party(x) for x in sorted(p['parties'])) or 'no consta'}</td>"
        f"<td>{_roles_cell(p['roles'])}</td>"
        f"<td>{html.escape(p['start'] or 'no consta')}</td>"
        f"<td>{html.escape(_end(p['end']))}</td>"
        f"<td>{f'<a href=\"{html.escape(p['profile'])}\">ficha</a>' if p['profile'] else 'no consta'}</td></tr>"
        for person, p in sorted(grouped.items())
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
<p><a href="index.html">Volver</a> · <a href="personas.html">Personas</a></p>
<h1>{html.escape(name)} ({html.escape(code)})</h1>
<p>{constitucion} Composición cargada: <b>{len(members)}</b> registros; <b>{office}</b> con cargo
normalizado (<b>{coverage_pct} %</b>) y {pending_roles} sin normalizar.</p>
<div class="cover" title="Composición normalizada: {office}/{len(members)}"><span style="width:{coverage_pct}%"></span></div>
{overlap_html}
{reserved_html}
{incomplete_html}
{DATA_LEGEND}
<h2>Reuniones <span class="chip">🔵 derivado</span></h2>
<p>{html.escape(sessions_note)} {html.escape(status_note)}</p>
<p>Comparecencias identificadas: <b>{comparecencias}</b>{html.escape(comparecencia_note)} ·
Oradores distintos: <b>{speakers}</b>. «Participa» aquí significa <b>intervenciones</b>, no asistencia.</p>
<svg viewBox="0 0 600 90" role="img" aria-label="Periodo cubierto por las fuentes">
<line x1="20" y1="60" x2="580" y2="60" stroke="currentColor" stroke-width="2"/>
<circle cx="20" cy="60" r="5" fill="currentColor"/>
<circle cx="580" cy="60" r="5" fill="currentColor"/>
<text x="20" y="80">{html.escape(eje_ini)}</text>
<text x="500" y="80">{html.escape(CUTOFF)}</text>
<text x="20" y="30">{html.escape(f"{len(sessions)} fechas de reunión cargadas" if sessions else 'Sin reuniones cargadas')}</text>
</svg>
<h2>Actividad <span class="chip">🔵 derivado</span></h2>
{trabajos}
<table><caption>Iniciativas por tipo</caption>
<thead><tr><th>Tipo</th><th>Total</th></tr></thead>
<tbody>{tipo_rows or '<tr><td colspan="2">Sin dato (⚪)</td></tr>'}</tbody></table>
<h2>Resultados <span class="chip">🔵 derivado</span></h2>
<table><caption>Iniciativas por situación</caption>
<thead><tr><th>Situación</th><th>Total</th></tr></thead>
<tbody>{situacion_rows or '<tr><td colspan="2">Sin dato (⚪)</td></tr>'}</tbody></table>
<h2>Ciclo de vida <span class="chip">🔵 derivado</span></h2>
<ol class="life">
<li class="{'ok' if constituted else 'na'}">Constituida: {constituted or '⚪ no consta'}</li>
<li class="{'ok' if sessions else 'na'}">Sesiones: {sessions_n}</li>
<li class="{'ok' if comparecencias else 'na'}">Comparecencias identificadas: {comparecencias}</li>
<li class="{'ok' if info['iniciativas'] else 'na'}">Iniciativas: {info['iniciativas']}</li>
<li class="{'ok' if info['aprobadas'] else 'na'}">Aprobadas: {info['aprobadas']}</li>
<li class="na">Dictamen/conclusiones: ⚪ no consta</li>
<li class="na">Ley publicada por comisión: ⚪ no consta</li>
</ol>
<h2>Composición oficial <span class="chip">🟢 oficial</span></h2>
<table><caption>Personas en cargos o adscripciones públicas</caption>
<thead><tr><th>Nombre</th><th>Grupo</th><th>Cargo</th><th>Alta</th><th>Baja</th><th>Fuente</th></tr></thead>
<tbody>{member_rows}</tbody></table>
{glossary_html}
<details><summary><b>Qué no mostramos y por qué</b></summary>
<ul>
<li><b>Coste</b>: 🔴 no se publica mientras las tarifas estén en validación.</li>
<li><b>Comparecencias</b>: ⚪ el opendata no siempre identifica la fase; se cuenta la sesión como reunión y solo se marca cuando la fuente lo dice.</li>
<li><b>Leyes aprobadas por comisión</b>: ⚪ la fuente no atribuye las leyes a una comisión.</li>
<li><b>Senado</b>: ⚪ acceso automatizado bloqueado; su composición no se ingiere. Las siglas SG… son grupos del Senado.</li>
<li><b>Bajas</b>: la fecha de baja igual a la disolución ({html.escape(DISSOLUTION)}) indica el fin de legislatura, no una baja individual.</li>
</ul>
</details>
<p>Fuente: listado oficial del Congreso, CSV de composición, e iniciativas e
intervenciones del opendata del Congreso.</p>
"""
    (web / f"comision-{code}.html").write_text(
        _page(
            f"{name}: actividad y resultados",
            ficha_body,
            "Ficha de comisión: constitución, actividad, resultados y composición.",
            url=f"/comision-{code}.html",
            breadcrumbs=[("Inicio", "/"), ("Comisiones", "/"), (name, f"/comision-{code}.html")],
        ),
        encoding="utf-8",
    )


def _person_slug(name):
    import re
    import unicodedata
    value = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "persona"


def _write_personas(con, web):
    """Página de personas: una fila por persona, con sus comisiones (sin duplicar)."""
    names = {code: name for code, name in con.execute("SELECT source_id, name FROM commissions")}
    rows = con.execute(
        "SELECT full_name, party, commission_source_id, profile_url FROM composition_raw"
    ).fetchall()
    people = {}
    for person, party, code, profile in rows:
        p = people.setdefault(person, {"parties": set(), "commissions": set(), "profile": None})
        if party:
            p["parties"].add(party)
        p["commissions"].add(code)
        if profile and not p["profile"]:
            p["profile"] = profile
    body_rows = []
    for person, p in sorted(people.items(), key=lambda kv: (-len(kv[1]["commissions"]), kv[0])):
        slug = _person_slug(person)
        groups = " ".join(sorted(p["parties"])) or "no consta"
        items = "".join(
            f'<li><a href="comision-{html.escape(code)}.html">{html.escape(names.get(code, code))}</a></li>'
            for code in sorted(p["commissions"], key=lambda c: names.get(c, c))
        )
        body_rows.append(
            f'<tr id="p-{slug}">'
            f"<td><b>{html.escape(person)}</b></td>"
            f"<td>{html.escape(groups)}</td>"
            f"<td>{len(p['commissions'])}</td>"
            f"<td><details><summary>ver {len(p['commissions'])}</summary><ul>{items}</ul></details></td>"
            "</tr>"
        )
    body = f"""
<p><a href="index.html">Volver</a></p>
<h1>Personas</h1>
<p>{len(people)} personas con al menos un cargo o adscripción en las comisiones cargadas.
«N comisiones» cuenta cada comisión una vez, aunque la persona haya tenido varios cargos en ella.</p>
<p><label>Buscar persona <input type=search data-filter placeholder="Nombre o grupo"></label></p>
<table><caption>Personas y comisiones</caption>
<thead><tr><th>Persona</th><th>Grupo(s)</th><th>N comisiones</th><th>Comisiones</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody></table>
<script>
const q=document.querySelector('[data-filter]');
if(q){{q.addEventListener('input',()=>{{const n=q.value.toLowerCase();for(const r of document.querySelectorAll('tbody tr')){{r.hidden=n && !r.textContent.toLowerCase().includes(n);}}}});}}
</script>
<p><a href="metodologia.html">Metodología y límites</a></p>
"""
    (web / "personas.html").write_text(
        _page(
            "Personas: cargos y comisiones",
            body,
            "Personas con cargo o adscripción en las comisiones del Congreso, con sus comisiones.",
            url="/personas.html",
            breadcrumbs=[("Inicio", "/"), ("Personas", "/personas.html")],
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
<li><b>Actividad</b>: iniciativas cuya comisión competente es la comisión
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
            url="/metodologia.html",
            breadcrumbs=[("Inicio", "/"), ("Metodología", "/metodologia.html")],
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    print(build())
