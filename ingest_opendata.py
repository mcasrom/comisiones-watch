#!/usr/bin/env python3
"""Ingesta de los volcados masivos del opendata -> SQLite.

Lee `data/opendata/<Nombre>.csv` (descargados por `scripts/fetch_opendata.py`)
y rellena:

  * `iniciativas`      (ProyectosDeLey / ProposicionesDeLey / PropuestasDeReforma)
  * `leyes_aprobadas`  (IniciativasLegislativasAprobadas)
  * `intervenciones`   (IntervencionesCronologicamente)

Cada fila con `COMISIONCOMPETENTE` / `ORGANO` se casa con nuestra comisión
oficial vía `matching.py` y se guarda tanto el nombre de origen como el código
resuelto y el método. Lo que no casa queda visible en el manifiesto, nunca se
descarta en silencio. Reejecutable (DELETE + INSERT por tabla).

Uso:
    python3 ingest_opendata.py --src-dir data/opendata --db data/comisiones.db
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from matching import build_index, match_organ  # noqa: E402

INICIATIVA_FILES = {
    "ProyectosDeLey": "proyecto_de_ley",
    "ProposicionesDeLey": "proposicion_de_ley",
    "PropuestasDeReforma": "propuesta_de_reforma",
}
APROBADAS_FILE = "IniciativasLegislativasAprobadas"
INTERVENCIONES_FILE = "IntervencionesCronologicamente"

LEGISLATURA = "Leg.15"

INICIATIVA_HEADER = [
    "LEGISLATURA", "SUPERTIPO", "AGRUPACION", "TIPO", "OBJETO", "NUMEXPEDIENTE",
    "FECHAPRESENTACION", "FECHACALIFICACION", "AUTOR", "TIPOTRAMITACION",
    "RESULTADOTRAMITACION", "SITUACIONACTUAL", "COMISIONCOMPETENTE", "PLAZOS",
    "PONENTES", "TRAMITACIONSEGUIDA", "INICIATIVASRELACIONADAS",
    "INICIATIVASDEORIGEN", "ENLACESBOCG", "ENLACESDS",
]
APROBADAS_HEADER = [
    "TIPO", "NUMERO_LEY", "TITULO_LEY", "NUMERO_BOLETIN", "FECHA_BOLETIN",
    "FECHA_LEY", "PDF",
]
INTERVENCIONES_HEADER = [
    "LEGISLATURA", "SUPERTIPOINICIATIVA", "TIPOINICIATIVA", "OBJETOINICIATIVA",
    "NUMEXPEDIENTE", "AUTOR", "SESION", "ORGANO", "FASE", "TIPOINTERVENCION",
    "ORADOR", "CARGOORADOR", "INICIOINTERVENCION", "FININTERVENCION",
    "ENLACEDIFERIDO", "ENLACEDESCARGADIRECTA", "ENLACETEXTOINTEGRO", "ENLACEPDF",
]

DDL = """
CREATE TABLE IF NOT EXISTS iniciativas(
  id INTEGER PRIMARY KEY,
  legislatura TEXT NOT NULL,
  dataset TEXT NOT NULL,
  tipo TEXT,
  objeto TEXT,
  num_expediente TEXT,
  fecha_presentacion TEXT,
  fecha_calificacion TEXT,
  autor TEXT,
  tipo_tramitacion TEXT,
  resultado_tramitacion TEXT,
  situacion_actual TEXT,
  comision_raw TEXT,
  comision_source_id TEXT,
  comision_match TEXT,
  ponentes INTEGER NOT NULL DEFAULT 0,
  UNIQUE(dataset, num_expediente)
);
CREATE TABLE IF NOT EXISTS leyes_aprobadas(
  id INTEGER PRIMARY KEY,
  tipo TEXT,
  numero_ley TEXT,
  titulo_ley TEXT,
  numero_boletin TEXT,
  fecha_boletin TEXT,
  fecha_ley TEXT,
  pdf TEXT
);
CREATE TABLE IF NOT EXISTS intervenciones(
  id INTEGER PRIMARY KEY,
  legislatura TEXT NOT NULL,
  organo_raw TEXT,
  commission_source_id TEXT,
  organo_match TEXT,
  sesion TEXT,
  fase TEXT,
  tipo_intervencion TEXT,
  orador TEXT,
  cargo_orador TEXT,
  num_expediente TEXT,
  inicio TEXT,
  fin TEXT
);
CREATE INDEX IF NOT EXISTS idx_interv_comision ON intervenciones(commission_source_id);
CREATE INDEX IF NOT EXISTS idx_inic_comision ON iniciativas(comision_source_id);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


class IngestOpenDataError(Exception):
    pass


def _iso_date_opt(value):
    """DD/MM/AAAA -> ISO. Devuelve `(iso, True)` o `(None, False)` si no cuadra."""
    if value is None or not str(value).strip():
        return None, True
    match = _DATE_RE.search(str(value))
    if not match:
        return None, False
    day, month, year = match.groups()
    return f"{year}-{month}-{day}", True


def _read_csv(path, expected_header):
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if reader.fieldnames != expected_header:
        raise IngestOpenDataError(
            f"{path.name}: cabecera inesperada {reader.fieldnames}"
        )
    return list(reader)


def _load_commissions(con):
    rows = con.execute("SELECT source_id, name FROM commissions").fetchall()
    if not rows:
        raise IngestOpenDataError(
            "la tabla `commissions` está vacía: ejecuta antes `ingest_csv.py`"
        )
    return [{"source_id": row[0], "name": row[1]} for row in rows]


class MatchCache:
    """Resuelve (y memoriza) el emparejado de un nombre de órgano."""

    def __init__(self, index):
        self.index = index
        self.cache = {}
        self.unmatched = {}
        self.ambiguous = {}

    def resolve(self, name):
        key = (name or "").strip()
        if key in self.cache:
            return self.cache[key]
        result = match_organ(key, self.index) if key else {
            "source_id": None,
            "how": "sin_mapear",
            "score": 0.0,
        }
        self.cache[key] = result
        if result["source_id"] is None:
            self.unmatched[key] = self.unmatched.get(key, 0) + 1
        elif result["how"] == "ambiguo":
            self.ambiguous[key] = result.get("candidatos", [])
        return result


def _ingest_iniciativas(con, src, cache):
    files = [(src / f"{name}.csv", name, dataset) for name, dataset in INICIATIVA_FILES.items()]
    present = [(p, name, ds) for p, name, ds in files if p.exists()]
    if not present:
        raise IngestOpenDataError("sin ficheros de iniciativas en el origen")
    con.execute("DELETE FROM iniciativas")
    rows_total = 0
    bad_dates = 0
    for path, name, dataset in present:
        rows = _read_csv(path, INICIATIVA_HEADER)
        for row in rows:
            present_date, ok1 = _iso_date_opt(row["FECHAPRESENTACION"])
            calif_date, ok2 = _iso_date_opt(row["FECHACALIFICACION"])
            bad_dates += int(not ok1) + int(not ok2)
            comision_raw = (row["COMISIONCOMPETENTE"] or "").strip()
            match = cache.resolve(comision_raw)
            ponentes = len([p for p in (row["PONENTES"] or "").split("\n") if p.strip()])
            con.execute(
                "INSERT INTO iniciativas(legislatura,dataset,tipo,objeto,num_expediente,"
                "fecha_presentacion,fecha_calificacion,autor,tipo_tramitacion,"
                "resultado_tramitacion,situacion_actual,comision_raw,comision_source_id,"
                "comision_match,ponentes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (row["LEGISLATURA"] or "").strip(),
                    dataset,
                    (row["TIPO"] or "").strip() or None,
                    (row["OBJETO"] or "").strip() or None,
                    (row["NUMEXPEDIENTE"] or "").strip() or None,
                    present_date,
                    calif_date,
                    (row["AUTOR"] or "").strip() or None,
                    (row["TIPOTRAMITACION"] or "").strip() or None,
                    (row["RESULTADOTRAMITACION"] or "").strip() or None,
                    (row["SITUACIONACTUAL"] or "").strip() or None,
                    comision_raw or None,
                    match["source_id"],
                    match["how"],
                    ponentes,
                ),
            )
        rows_total += len(rows)
    return {"filas": rows_total, "fechas_no_parseadas": bad_dates}


def _ingest_leyes(con, src):
    path = src / f"{APROBADAS_FILE}.csv"
    if not path.exists():
        raise IngestOpenDataError(f"falta {path.name}")
    rows = _read_csv(path, APROBADAS_HEADER)
    con.execute("DELETE FROM leyes_aprobadas")
    for row in rows:
        fecha_boletin, _ = _iso_date_opt(row["FECHA_BOLETIN"])
        fecha_ley, _ = _iso_date_opt(row["FECHA_LEY"])
        con.execute(
            "INSERT INTO leyes_aprobadas(tipo,numero_ley,titulo_ley,numero_boletin,"
            "fecha_boletin,fecha_ley,pdf) VALUES (?,?,?,?,?,?,?)",
            (
                (row["TIPO"] or "").strip() or None,
                (row["NUMERO_LEY"] or "").strip() or None,
                (row["TITULO_LEY"] or "").strip() or None,
                (row["NUMERO_BOLETIN"] or "").strip() or None,
                fecha_boletin,
                fecha_ley,
                (row["PDF"] or "").strip() or None,
            ),
        )
    return {"filas": len(rows)}


def _ingest_intervenciones(con, src, cache):
    path = src / f"{INTERVENCIONES_FILE}.csv"
    if not path.exists():
        raise IngestOpenDataError(f"falta {path.name}")
    rows = _read_csv(path, INTERVENCIONES_HEADER)
    con.execute("DELETE FROM intervenciones")
    bad_dates = 0
    for row in rows:
        sesion, ok = _iso_date_opt(row["SESION"])
        bad_dates += int(not ok)
        organo_raw = (row["ORGANO"] or "").strip()
        match = cache.resolve(organo_raw)
        con.execute(
            "INSERT INTO intervenciones(legislatura,organo_raw,commission_source_id,"
            "organo_match,sesion,fase,tipo_intervencion,orador,cargo_orador,"
            "num_expediente,inicio,fin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (row["LEGISLATURA"] or "").strip(),
                organo_raw or None,
                match["source_id"],
                match["how"],
                sesion,
                (row["FASE"] or "").strip() or None,
                (row["TIPOINTERVENCION"] or "").strip() or None,
                (row["ORADOR"] or "").strip() or None,
                (row["CARGOORADOR"] or "").strip() or None,
                (row["NUMEXPEDIENTE"] or "").strip() or None,
                (row["INICIOINTERVENCION"] or "").strip() or None,
                (row["FININTERVENCION"] or "").strip() or None,
            ),
        )
    return {"filas": len(rows), "fechas_no_parseadas": bad_dates}


def run(src_dir, db_path, legislatura=LEGISLATURA):
    src = Path(src_dir)
    db_path = Path(db_path)
    if not src.exists():
        raise IngestOpenDataError(f"no existe el directorio {src}")
    con = sqlite3.connect(db_path)
    con.executescript(DDL)
    commissions = _load_commissions(con)
    cache = MatchCache(build_index(commissions))

    manifest = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "legislatura": legislatura,
        "iniciativas": _ingest_iniciativas(con, src, cache),
        "leyes_aprobadas": _ingest_leyes(con, src),
        "intervenciones": _ingest_intervenciones(con, src, cache),
        "organos_sin_mapear": cache.unmatched,
        "organos_ambiguos": cache.ambiguous,
    }
    con.execute(
        "INSERT INTO meta(key,value) VALUES ('opendata_manifest',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps({k: manifest[k] for k in ("generado", "legislatura")}),),
    )
    con.commit()
    digest_inputs = {}
    for name in (*INICIATIVA_FILES, APROBADAS_FILE, INTERVENCIONES_FILE):
        path = src / f"{name}.csv"
        if path.exists():
            digest_inputs[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    manifest["sha256_entradas"] = digest_inputs
    out = db_path.parent / "opendata_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    con.close()
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src-dir", default=str(ROOT / "data" / "opendata"))
    parser.add_argument("--db", required=True)
    parser.add_argument("--legislatura", default=LEGISLATURA)
    args = parser.parse_args()
    try:
        manifest = run(args.src_dir, args.db, args.legislatura)
    except IngestOpenDataError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "iniciativas": manifest["iniciativas"]["filas"],
                "leyes_aprobadas": manifest["leyes_aprobadas"]["filas"],
                "intervenciones": manifest["intervenciones"]["filas"],
                "organos_sin_mapear": manifest["organos_sin_mapear"],
                "organos_ambiguos": manifest["organos_ambiguos"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
