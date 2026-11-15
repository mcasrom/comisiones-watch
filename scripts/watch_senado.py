#!/usr/bin/env python3
"""Vigilancia del catálogo de datos abiertos del Senado.

No descarga composición ni intenta saltarse el bloqueo. Solo consulta páginas
públicas de catálogo/transparencia y avisa si aparece una entrada relacionada
con composición de comisiones, miembros, cargos o fechas de alta/baja.

Uso:
  python3 scripts/watch_senado.py --dry
  python3 scripts/watch_senado.py
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STATE = Path('/home/deploy/scripts/state/watch_senado.json')
ENV_CANDIDATES = [BASE/'.env', Path('/home/deploy/nearme-osint/.env')]
URLS = [
    'https://www.senado.es/web/opendata/index.html',
    'https://www.senado.es/web/opendata/',
    'https://www.senado.es/web/opendata/catalogo/index.html',
    'https://www.senado.es/web/transparencia/index.html',
]
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36')
TERMS = ('composición de las comisiones', 'composicion de las comisiones',
         'composición de comisiones', 'composicion de comisiones',
         'miembros de las comisiones', 'miembros de comisiones',
         'cargos de las comisiones', 'cargos de comisiones',
         'altas y bajas', 'alta y baja', 'datos abiertos', 'catálogo de datos')

def _env(path):
    out = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$', line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return out

def _telegram(text):
    env = _env(ENV_CANDIDATES[0]) if ENV_CANDIDATES[0].exists() else _env(ENV_CANDIDATES[1])
    token, chat = env.get('TELEGRAM_BOT_TOKEN'), env.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        print('[senado] sin credenciales Telegram', file=sys.stderr)
        return False
    data = urllib.parse.urlencode({'chat_id': chat, 'text': text,
                                   'disable_web_page_preview': 'true'}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f'https://api.telegram.org/bot{token}/sendMessage', data=data), timeout=15)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f'[senado] Telegram fallo: {exc}', file=sys.stderr)
        return False

def candidates(html: str):
    low = html.lower()
    found = [t for t in TERMS if t in low]
    # Solo cuentan si aparecen junto a una palabra de estructura/comisiones.
    if not found:
        return []
    if not any(k in low for k in ('comisi', 'órgano', 'organo', 'miembro', 'cargo')):
        return []
    return sorted(set(found))

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Accept-Language': 'es-ES,es;q=0.9'})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read(500000).decode('utf-8', 'replace')
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, ''
    except Exception as exc:  # noqa: BLE001
        return 0, f'ERR {exc}'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    previous = {}
    try:
        previous = json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        pass
    results, all_candidates = [], {}
    for url in URLS:
        status, body = fetch(url)
        found = candidates(body) if status == 200 else []
        results.append({'url': url, 'http': status, 'candidates': found})
        if found:
            all_candidates[url] = found
    old = previous.get('candidates', {})
    new = {u: v for u, v in all_candidates.items() if u not in old or old[u] != v}
    summary = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
               'results': results, 'candidates': all_candidates,
               'new': new, 'sha256': hashlib.sha256(json.dumps(all_candidates, sort_keys=True).encode()).hexdigest()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.dry:
        return 0
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, STATE)
    if new:
        lines = ['🟢 SENADO — posible entrada de composición de comisiones:']
        for u, terms in new.items():
            lines.append(f'· {u} · {", ".join(terms)}')
        _telegram('\n'.join(lines))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
