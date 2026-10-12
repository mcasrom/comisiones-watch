#!/usr/bin/env python3
"""Vigilancia de comisiones parlamentarias: CLI mínimo y de bajo consumo.

Comandos:
  init                      crea la base de datos con schema.sql
  snapshot URL [--source S] descarga una URL (1 petición), guarda el cuerpo
                            comprimido solo si cambió el hash
  load-rates FICHERO.csv    carga tarifas (chamber,role,monthly_eur,valid_from,valid_to,source_url)
  report [--html SALIDA]    ranking por coste estimado y actividad

Diseño para un servidor justo de recursos: sin dependencias obligatorias
(solo biblioteca estándar; `requests` es opcional), sin proceso residente,
una petición cada RATE_LIMIT_S segundos.
"""
import argparse
import csv
import gzip
import hashlib
import html
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "comisiones.db"
RAW_DIR = BASE / "data" / "raw"
RATE_LIMIT_S = 1.0
USER_AGENT = "comisiones-watch/0.1 (proyecto de transparencia; contacto en el repositorio)"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def cmd_init(_args):
    con = connect()
    con.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))
    con.commit()
    print(f"Base de datos lista en {DB_PATH}")


def cmd_snapshot(args):
    req = urllib.request.Request(args.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    digest = hashlib.sha256(body).hexdigest()
    con = connect()
    seen = con.execute(
        "SELECT 1 FROM raw_snapshots WHERE url=? AND sha256=?", (args.url, digest)
    ).fetchone()
    if seen:
        print("Sin cambios desde la última descarga; no se guarda de nuevo.")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{digest[:16]}.gz"
    with gzip.open(path, "wb") as fh:
        fh.write(body)
    con.execute(
        "INSERT INTO raw_snapshots(source,url,fetched_at,sha256,path) VALUES (?,?,?,?,?)",
        (args.source, args.url, datetime.now(timezone.utc).isoformat(), digest, str(path)),
    )
    con.commit()
    print(f"Guardado {len(body)} bytes en {path}")
    time.sleep(RATE_LIMIT_S)


def cmd_load_rates(args):
    con = connect()
    n = 0
    with open(args.csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            con.execute(
                "INSERT INTO pay_rates(chamber,role,monthly_eur,valid_from,valid_to,source_url)"
                " VALUES (?,?,?,?,?,?)",
                (row["chamber"], row["role"], float(row["monthly_eur"]),
                 row["valid_from"], row.get("valid_to") or None, row["source_url"]),
            )
            n += 1
    con.commit()
    print(f"{n} tarifas cargadas")


def fetch_ranking(con):
    cur = con.execute(
        "SELECT chamber, kind, name, constituted_on, days_since_constituted, sessions_total,"
        " sessions_substantive, last_session, est_eur, eur_per_substantive"
        " FROM v_ranking ORDER BY (sessions_substantive = 0) DESC, est_eur DESC"
    )
    return [d[0] for d in cur.description], cur.fetchall()


def cmd_report(args):
    con = connect()
    cols, rows = fetch_ranking(con)
    if not rows:
        print("Sin comisiones cargadas todavía.")
        return
    for r in rows:
        print(" | ".join("" if v is None else str(v) for v in r))
    if args.html:
        head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape('' if v is None else str(v))}</td>" for v in r) + "</tr>"
            for r in rows
        )
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        Path(args.html).write_text(
            "<!doctype html><meta charset=utf-8><title>Comisiones</title>"
            "<p>Coste ESTIMADO (tarifa × meses). Generado: " + stamp + "</p>"
            f"<table border=1 cellpadding=4><tr>{head}</tr>{body}</table>",
            encoding="utf-8",
        )
        print(f"Informe HTML en {args.html}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    s = sub.add_parser("snapshot")
    s.add_argument("url")
    s.add_argument("--source", default="manual")
    s.set_defaults(fn=cmd_snapshot)
    r = sub.add_parser("load-rates")
    r.add_argument("csv")
    r.set_defaults(fn=cmd_load_rates)
    rep = sub.add_parser("report")
    rep.add_argument("--html")
    rep.set_defaults(fn=cmd_report)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
