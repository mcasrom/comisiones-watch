#!/usr/bin/env python3
"""Descarga automática de los ficheros masivos del opendata del Congreso.

El Congreso publica volcados diarios en `/webpublica/opendata/<dataset>/<Nombre>__<ts>.csv`.
La página `/es/opendata/<dataset>` los lista como enlaces estáticos. Este script:
  1. descarga la página de cada dataset;
  2. extrae los enlaces `<Nombre>__<ts>.csv` y elige el más reciente por nombre;
  3. descarga cada CSV a `data/opendata/<Nombre>.csv` (nombre estable);
  4. escribe `data/opendata/manifest.json` con el origen, http, bytes y sha256.

Reejecutable: si el sha256 no cambia, no reescribe. Una petición por segundo.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.congreso import BASE_URL  # noqa: E402

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
SLEEP_SECONDS = 1.0
TIMEOUT = 120

# dataset de la página  ->  ficheros (basenames) que nos interesan
DATASETS = {
    "iniciativas": (
        "ProyectosDeLey",
        "ProposicionesDeLey",
        "PropuestasDeReforma",
        "IniciativasLegislativasAprobadas",
    ),
    "intervenciones": ("IntervencionesCronologicamente",),
}

_LINK_RE = re.compile(
    r'href="(/webpublica/opendata/(?P<dataset>[a-z]+)/'
    r'(?P<name>[A-Za-z]+)__(?P<ts>\d{14})\.csv)"'
)


def fetch(url, *, referer=None):
    """Descarga con `curl` (misma huella que la vía de composiciones)."""
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
        ]
        if referer:
            command += ["-H", f"Referer: {referer}"]
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
    except Exception as exc:  # noqa: BLE001  (un fallo debe ser visible)
        return 0, str(exc).encode(), ""
    finally:
        Path(body_file.name).unlink(missing_ok=True)
        time.sleep(SLEEP_SECONDS)


def parse_links(html, dataset, wanted):
    """Devuelve {basename: url_absoluta} con la versión más reciente."""
    latest = {}
    for match in _LINK_RE.finditer(html):
        if match.group("dataset") != dataset:
            continue
        name = match.group("name")
        if wanted and name not in wanted:
            continue
        ts = match.group("ts")
        current = latest.get(name)
        if current is None or ts > current[0]:
            latest[name] = (ts, BASE_URL + match.group(1))
    return latest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "data" / "opendata"))
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    summary = {"ok": 0, "sin_cambios": 0, "fallos": [], "bytes": 0}
    files = {}

    for dataset, wanted in DATASETS.items():
        page = f"{BASE_URL}/es/opendata/{dataset}"
        status, payload, content_type = fetch(page, referer=BASE_URL)
        if status != 200:
            summary["fallos"].append(
                {"dataset": dataset, "fase": "indice", "http": status, "tipo": content_type}
            )
            continue
        links = parse_links(payload.decode("utf-8", "replace"), dataset, wanted)
        missing = [name for name in wanted if name not in links]
        for name in missing:
            summary["fallos"].append(
                {"dataset": dataset, "fase": "indice", "error": f"sin enlace para {name}"}
            )
        for name, (ts, url) in sorted(links.items()):
            status, body, content_type = fetch(url, referer=page)
            if status != 200:
                summary["fallos"].append(
                    {"dataset": dataset, "fase": "csv", "nombre": name, "http": status}
                )
                continue
            digest = hashlib.sha256(body).hexdigest()
            path = out / f"{name}.csv"
            previous = files.get(name)
            if path.exists() and previous is None:
                old = hashlib.sha256(path.read_bytes()).hexdigest()
                if old == digest:
                    summary["sin_cambios"] += 1
                    files[name] = {
                        "origen": url,
                        "ts": ts,
                        "sha256": digest,
                        "bytes": len(body),
                    }
                    continue
            path.write_bytes(body)
            files[name] = {
                "origen": url,
                "ts": ts,
                "sha256": digest,
                "bytes": len(body),
            }
            summary["ok"] += 1
            summary["bytes"] += len(body)

    manifest = {
        "fuente": f"{BASE_URL}/es/opendata/",
        "generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "resumen": {**summary, "segundos": round(time.time() - started, 1)},
        "archivos": files,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest["resumen"], ensure_ascii=False))
    if summary["fallos"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
