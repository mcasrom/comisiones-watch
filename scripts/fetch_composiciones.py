#!/usr/bin/env python3
"""Descarga automática de composiciones del Congreso en CSV oficial.

Vía verificada (16-oct-2026), sin cookies ni JavaScript:
  1. POST `resourceIDOrganos` (tipoConsulta=3, legislatura) -> lista de órganos
     con su código oficial (`_organos_selectedSuborgano`) y su nombre completo.
  2. POST `opendataExport` por comisión -> CSV con la cabecera oficial, byte a
     byte igual al exportado a mano desde el navegador.

Guarda `data/csv/<código>.csv` (consumible por `ingest_csv.py`) y un manifiesto
con sha256, filas y http. Ritmo: una petición por segundo. Reejecutable.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.congreso import (  # noqa: E402
    BASE_URL,
    RESOURCE_ID,
    RESOURCE_PATH,
    composition_csv_request,
    parse_organ_export,
    validate_discovery,
    validate_export_csv,
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
SLEEP_SECONDS = 1.0
TIMEOUT = 60
LEGISLATURA_ID = {"XIII": "13", "XIV": "14", "XV": "15", "XVI": "16"}
INDEX_URL = urljoin(BASE_URL, RESOURCE_PATH) + (
    "?p_p_id=opendata&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view"
    f"&p_p_resource_id={RESOURCE_ID}&p_p_cacheability=cacheLevelPage"
)


def fetch(url, *, data=None, referer=None):
    """Descarga con `curl` (mejor huella TLS ante el borde del Congreso).

    Sin cookies ni sesión: `resourceIDOrganos` y `opendataExport` responden a un
    POST limpio. Respeta el ritmo de una petición por segundo.
    """
    body_file = tempfile.NamedTemporaryFile(delete=False)
    body_file.close()
    try:
        command = [
            "curl",
            "-sS",
            "-L",
            "--max-time",
            str(TIMEOUT),
            "-A",
            USER_AGENT,
            "-H",
            "X-Requested-With: XMLHttpRequest",
            "-H",
            "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
        ]
        if referer:
            command += ["-H", f"Referer: {referer}", "-H", f"Origin: {BASE_URL}"]
        for key, value in (data or {}).items():
            command += ["--data-urlencode", f"{key}={value}"]
        command += [
            "-o",
            body_file.name,
            "-w",
            "%{http_code}\n%{content_type}\n",
            url,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        status_text, content_type = (completed.stdout.splitlines() + ["", ""])[:2]
        try:
            status = int(status_text)
        except ValueError:
            status = 0
        payload = (
            Path(body_file.name).read_bytes() if status else completed.stderr.encode()
        )
        return status, payload, content_type.split(";")[0]
    except Exception as exc:  # noqa: BLE001  (un fallo debe ser visible, no silencioso)
        return 0, str(exc).encode(), ""
    finally:
        Path(body_file.name).unlink(missing_ok=True)
        time.sleep(SLEEP_SECONDS)


def _data_rows(payload):
    text = payload.decode("utf-8-sig", "replace")
    return max(0, sum(1 for line in text.splitlines() if line.strip()) - 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "data" / "csv"))
    parser.add_argument("--legislatura", default="XV")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    legislatura_id = LEGISLATURA_ID.get(args.legislatura.upper(), args.legislatura)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    previous = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "archivos", {}
            )
        except ValueError:
            previous = {}
    started = time.time()

    status, payload, content_type = fetch(
        INDEX_URL,
        data={"_opendata_tipoConsulta": "3", "_opendata_legislatura": legislatura_id},
        referer=urljoin(BASE_URL, RESOURCE_PATH),
    )
    if status != 200:
        print(json.dumps({"fase": "indice", "http": status, "tipo": content_type}))
        raise SystemExit(1)
    try:
        records = parse_organ_export(json.loads(payload.decode("utf-8")))
        validate_discovery(records)
    except (ValueError, UnicodeDecodeError) as exc:
        print(json.dumps({"fase": "indice", "error": str(exc)}))
        raise SystemExit(1)

    selected = records[args.offset : args.offset + args.limit if args.limit else None]
    summary = {"ok": 0, "sin_cambios": 0, "fallos": [], "filas": 0, "bytes": 0}
    files = {}
    for record in selected:
        try:
            code, url, form = composition_csv_request(
                record["export_url"], args.legislatura
            )
        except ValueError as exc:
            summary["fallos"].append(
                {"codigo": record["source_id"], "fase": "peticion", "error": str(exc)}
            )
            continue
        status, payload, content_type = fetch(url, data=form, referer=record["export_url"])
        if status != 200:
            summary["fallos"].append(
                {"codigo": code, "fase": "csv", "http": status, "tipo": content_type}
            )
            continue
        try:
            validate_export_csv(payload)
        except ValueError as exc:
            summary["fallos"].append(
                {
                    "codigo": code,
                    "fase": "csv",
                    "error": str(exc),
                    "inicio": payload[:80].decode("utf-8", "ignore"),
                }
            )
            continue
        digest = hashlib.sha256(payload).hexdigest()
        rows = _data_rows(payload)
        path = out / f"{code}.csv"
        if path.exists() and previous.get(code, {}).get("sha256") == digest:
            summary["sin_cambios"] += 1
        else:
            path.write_bytes(payload)
            summary["ok"] += 1
        files[code] = {
            "nombre": record["name"],
            "sha256": digest,
            "filas": rows,
            "ruta": str(path),
        }
        summary["filas"] += rows
        summary["bytes"] += len(payload)

    manifest = {
        "legislatura": args.legislatura,
        "fuente": INDEX_URL,
        "generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "resumen": {**summary, "segundos": round(time.time() - started, 1)},
        "archivos": files,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest["resumen"], ensure_ascii=False))
    if summary["fallos"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
