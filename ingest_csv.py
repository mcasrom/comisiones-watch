#!/usr/bin/env python3
"""Ingesta manual de composiciones: CSV descargados del navegador -> SQLite.

Uso:
    python3 ingest_csv.py --csv-dir data/csv --db data/comisiones.db

Cada CSV debe tener la cabecera exacta del exportador oficial:
    Cargo;NombreOrgano;Nombre;Grupo;FechaAlta;FechaBaja
La comisión se resuelve por `NombreOrgano` contra el descubrimiento del listado.
Un fichero con error hace fallar la ejecución (fallo visible); lo ya cargado se
conserva y el manifiesto registra el motivo. Reejecutable sin duplicar.
"""
import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from adapters.congreso import (  # noqa: E402
    _iso_date,
    canonical_role,
    discover_commissions,
)

EXPECTED_HEADER = ["Cargo", "NombreOrgano", "Nombre", "Grupo", "FechaAlta", "FechaBaja"]

DDL = """
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


class IngestError(Exception):
    pass


def load_discovery():
    listing = (ROOT / "tests" / "fixtures" / "congreso_comisiones.html").read_text(
        encoding="utf-8"
    )
    return {item["name"]: item for item in discover_commissions(listing)}


def ingest_file(path, discovery, con):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError(f"{path.name}: no es un CSV legible ({exc})")
    reader = csv.DictReader(text.splitlines(), delimiter=";")
    if reader.fieldnames != EXPECTED_HEADER:
        raise IngestError(f"{path.name}: cabecera inesperada {reader.fieldnames}")
    rows = list(reader)
    if not rows:
        raise IngestError(f"{path.name}: sin filas")
    organs = {row["NombreOrgano"].strip() for row in rows}
    if len(organs) != 1:
        raise IngestError(f"{path.name}: mezcla varios órganos {sorted(organs)}")
    organ = organs.pop()
    if organ not in discovery:
        raise IngestError(f"{path.name}: órgano desconocido {organ!r}")
    commission = discovery[organ]
    parsed = []
    for lineno, row in enumerate(rows, start=2):
        name = (row["Nombre"] or "").strip()
        label = (row["Cargo"] or "").strip()
        if not name or not label:
            raise IngestError(f"{path.name}:{lineno}: fila sin nombre o cargo")
        try:
            start = _iso_date(row["FechaAlta"])
            end = _iso_date(row["FechaBaja"])
        except ValueError as exc:
            raise IngestError(f"{path.name}:{lineno}: {exc}")
        role = canonical_role(label)
        parsed.append(
            (
                commission["source_id"],
                name,
                (row["Grupo"] or "").strip() or None,
                "",
                label,
                role,
                start,
                end,
                None,
                int(role is None),
            )
        )
    con.execute(
        "INSERT INTO commissions VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(source_id) DO UPDATE SET "
        "chamber=excluded.chamber, kind=excluded.kind, name=excluded.name, "
        "section=excluded.section, url=excluded.url, legislatura=excluded.legislatura",
        (
            commission["source_id"],
            commission["chamber"],
            commission["kind"],
            commission["name"],
            commission["section"],
            commission["url"],
            commission["legislatura"],
        ),
    )
    con.execute(
        "DELETE FROM composition_raw WHERE commission_source_id=?",
        (commission["source_id"],),
    )
    con.executemany(
        "INSERT INTO composition_raw VALUES (NULL,?,?,?,?,?,?,?,?,?,?)", parsed
    )
    return {
        "fichero": path.name,
        "sha256": digest,
        "comision": organ,
        "codigo": commission["source_id"],
        "filas": len(parsed),
        "pendientes_diccionario": sum(1 for row in parsed if row[5] is None),
    }


def run(csv_dir, db_path, cutoff=None):
    csv_dir = Path(csv_dir)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cutoff = cutoff or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    discovery = load_discovery()
    con = sqlite3.connect(db_path)
    con.executescript(DDL)
    files = sorted(csv_dir.glob("*.csv"))
    if not files:
        raise IngestError(f"sin CSV en {csv_dir}")
    manifest = {"corte": cutoff, "ficheros": [], "errores": []}
    for path in files:
        try:
            manifest["ficheros"].append(ingest_file(path, discovery, con))
            con.commit()
        except IngestError as exc:
            con.rollback()
            manifest["errores"].append(str(exc))
    out = db_path.parent / "ingest_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-dir", required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    try:
        manifest = run(args.csv_dir, args.db)
    except IngestError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "ficheros": len(manifest["ficheros"]),
                "filas": sum(f["filas"] for f in manifest["ficheros"]),
                "errores": manifest["errores"],
            },
            ensure_ascii=False,
        )
    )
    if manifest["errores"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
