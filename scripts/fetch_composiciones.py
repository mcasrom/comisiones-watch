#!/usr/bin/env python3
"""Descarga secuencial y trazable de composiciones del Congreso.

Usa el listado verificado como conjunto de comisiones, descubre el identificador
superior en cada ficha y pide el JSON oficial `searchOrgano`. Guarda cada cuerpo
crudo comprimido solo cuando cambia su hash. Ritmo: una petición por segundo.
"""
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.congreso import detail_signals, discover_commissions  # noqa: E402

BASE_URL = "https://www.congreso.es"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
SLEEP_SECONDS = 1.0
TIMEOUT = 60
COOKIE_JAR = None


def fetch(url, *, data=None, referer=None):
    """Descarga con `curl` porque el borde del Congreso responde mejor a su huella TLS.

    Mantiene cookies de sesión en el directorio de salida y respeta el ritmo de
    una petición por segundo.
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
            "--cookie-jar",
            COOKIE_JAR,
            "--cookie",
            COOKIE_JAR,
        ]
        if referer:
            command += [
                "-H",
                f"Referer: {referer}",
                "-H",
                f"Origin: {BASE_URL}",
                "-H",
                "X-Requested-With: XMLHttpRequest",
                "-H",
                "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
                "-H",
                "Accept: application/json, text/javascript, */*; q=0.01",
            ]
        if data:
            for key, value in data.items():
                command += ["--data-urlencode", f"{key}={value}"]
        command += [
            "-o",
            body_file.name,
            "-w",
            "%{http_code}\n%{url_effective}\n%{content_type}\n",
            url,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        status_text, final_url, content_type = (completed.stdout.splitlines() + ["", "", ""])[:3]
        try:
            status = int(status_text)
        except ValueError:
            status = 0
        payload = Path(body_file.name).read_bytes() if status else completed.stderr.encode()
        return status, payload, content_type.split(";")[0], final_url or url
    except Exception as exc:
        return 0, str(exc).encode(), "", url
    finally:
        Path(body_file.name).unlink(missing_ok=True)
        time.sleep(SLEEP_SECONDS)


def store_raw(raw_dir, name, payload, files):
    digest = hashlib.sha256(payload).hexdigest()
    previous = files.get(name, {})
    if previous.get("sha256") == digest and Path(previous.get("ruta", "")).exists():
        return previous["ruta"], False
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{name}-{digest[:16]}.gz"
    with gzip.open(path, "wb") as fh:
        fh.write(payload)
    return str(path), True


def main():
    global SLEEP_SECONDS
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "data" / "bruto-congreso"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=SLEEP_SECONDS,
                        help="segundos entre peticiones (goteo: 20-30 de madrugada)")
    args = parser.parse_args()
    SLEEP_SECONDS = args.sleep
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    global COOKIE_JAR
    COOKIE_JAR = str(out / ".cookies.txt")
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    listing = (ROOT / "tests" / "fixtures" / "congreso_comisiones.html").read_text(encoding="utf-8")
    commissions = discover_commissions(listing)
    selected = commissions[args.offset : args.offset + args.limit if args.limit else None]
    summary = {"ok": 0, "fallos": [], "sin_cambios": 0, "bytes": 0}
    files = manifest.setdefault("archivos", {})
    started = time.time()

    for item in selected:
        code = item["source_id"]
        status, detail, content_type, detail_url = fetch(item["url"])
        if status != 200 or "text/html" not in content_type:
            summary["fallos"].append(
                {"codigo": code, "fase": "ficha", "http": status, "tipo": content_type}
            )
            continue
        detail_path, _ = store_raw(out, f"detalle-{code}.html", detail, files)
        try:
            signals = detail_signals(detail.decode("utf-8", "ignore"))
        except ValueError as exc:
            summary["fallos"].append({"codigo": code, "fase": "ficha", "error": str(exc)})
            continue
        form = {
            "_organos_selectedLegislatura": signals["legislatura"],
            "_organos_compoHistorica": "true",
            "_organos_selectedOrganoSup": signals["sup_id"],
            "_organos_selectedSuborgano": signals["source_id"],
        }
        page_status, page_payload, page_type, page_url = fetch(
            signals["composition_url"], referer=detail_url
        )
        if page_status != 200 or "text/html" not in page_type:
            summary["fallos"].append(
                {
                    "codigo": code,
                    "fase": "pagina-composicion",
                    "http": page_status,
                    "tipo": page_type,
                }
            )
            continue
        status, payload, content_type, _ = fetch(
            signals["composition_url"], data=form, referer=page_url
        )
        try:
            json.loads(payload.decode("utf-8"))
        except ValueError:
            summary["fallos"].append(
                {
                    "codigo": code,
                    "fase": "composicion",
                    "error": "JSON inválido",
                    "http": status,
                    "tipo": content_type,
                    "bytes": len(payload),
                    "inicio": payload[:80].decode("utf-8", "ignore"),
                }
            )
            continue
        if status != 200:
            summary["fallos"].append(
                {"codigo": code, "fase": "composicion", "http": status, "tipo": content_type}
            )
            continue
        page_path, _ = store_raw(out, f"pagina-composicion-{code}.html", page_payload, files)
        path, changed = store_raw(out, f"composicion-{code}.json", payload, files)
        files[f"detalle-{code}.html"] = {"sha256": hashlib.sha256(detail).hexdigest(), "ruta": detail_path}
        files[f"pagina-composicion-{code}.html"] = {
            "sha256": hashlib.sha256(page_payload).hexdigest(),
            "ruta": page_path,
        }
        files[f"composicion-{code}.json"] = {"sha256": hashlib.sha256(payload).hexdigest(), "ruta": path}
        summary["bytes"] += len(detail) + len(page_payload) + len(payload)
        if changed:
            summary["ok"] += 1
        else:
            summary["sin_cambios"] += 1

    manifest["resumen"] = {**summary, "segundos": round(time.time() - started, 1)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["resumen"], ensure_ascii=False))
    if summary["fallos"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
