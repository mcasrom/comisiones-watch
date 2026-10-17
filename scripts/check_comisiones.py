#!/usr/bin/env python3
"""check_comisiones.py — watchdog del microservicio de comisiones.

Avisa por Telegram si el pipeline deja de actualizarse o si faltan datos.
Solo avisa al **cambiar de estado** (evita spam). `--dry` imprime sin enviar.
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "comisiones.db")
LOG = "/home/deploy/scripts/comisiones_goteo.log"
STATE = "/home/deploy/scripts/state/check_comisiones.json"
ENV = "/home/deploy/nearme-osint/.env"
MAX_HOURS = 36
MIN_INTERVENCIONES = 1000


def _env(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
                if match:
                    out[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _telegram(text):
    env = _env(ENV)
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[check] sin credenciales Telegram", file=sys.stderr)
        return False
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
        return True
    except Exception as exc:  # noqa: BLE001 - el watchdog no debe caer
        print(f"[check] Telegram fallo: {exc}", file=sys.stderr)
        return False


def _last_ok(path):
    last = None
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                match = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC\] comisiones OK", line)
                if match:
                    last = match.group(1)
    except OSError:
        pass
    return last


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="imprime sin enviar ni guardar estado")
    args = parser.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    issues = []

    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        commissions = con.execute("SELECT COUNT(*) FROM commissions").fetchone()[0]
        intervenciones = con.execute("SELECT COUNT(*) FROM intervenciones").fetchone()[0]
        max_sesion = con.execute("SELECT MAX(sesion) FROM intervenciones").fetchone()[0]
        con.close()
    except Exception as exc:  # noqa: BLE001
        commissions = intervenciones = 0
        max_sesion = None
        issues.append(f"no puedo leer la BD: {exc}")

    if commissions == 0:
        issues.append("0 comisiones en la BD")
    if intervenciones < MIN_INTERVENCIONES:
        issues.append(f"intervenciones bajas: {intervenciones}")

    try:
        mtime = datetime.datetime.fromtimestamp(
            os.path.getmtime(DB), datetime.timezone.utc
        ).replace(tzinfo=None)
        age_hours = (now - mtime).total_seconds() / 3600
        if age_hours > MAX_HOURS:
            issues.append(f"BD sin actualizar hace {age_hours:.1f} h")
    except OSError:
        issues.append("no existe data/comisiones.db")

    last = _last_ok(LOG)
    if not last:
        issues.append("sin ningún 'comisiones OK' en el log")
    else:
        try:
            age = (now - datetime.datetime.strptime(last, "%Y-%m-%d %H:%M")).total_seconds() / 3600
            if age > MAX_HOURS:
                issues.append(f"última ejecución OK hace {age:.1f} h ({last} UTC)")
        except ValueError:
            issues.append(f"fecha de log no parseable: {last}")

    try:
        previous = json.load(open(STATE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        previous = {}
    changed = previous.get("issues") != issues
    print(
        f"[check] issues={issues} | changed={changed} | comisiones={commissions} "
        f"intervenciones={intervenciones} max_sesion={max_sesion}"
    )
    if args.dry:
        return 0

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    if changed:
        if issues:
            _telegram("🔴 COMISIONES — watchdog: " + "; ".join(issues))
        else:
            _telegram("🟢 COMISIONES — watchdog: pipeline al día (sin incidencias).")
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"issues": issues}, handle)
        os.replace(tmp, STATE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
