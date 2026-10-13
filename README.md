# comisiones-watch

Vigilancia ciudadana de las comisiones del Congreso y del Senado: **actividad
real frente a coste estimado** de sus cargos. Datos públicos verificables,
mismo rasero para todas las comisiones y todos los grupos.

> **Estado: piloto, sin desplegar.** No hay web pública. Lo verificado hasta
> hoy: 50 comisiones del Congreso descubiertas; composición cargable por **vía
> manual CSV** (`ingest_csv.py`; probada con 4 comisiones, 378 filas) y muestra
> 301 confirmada **85/85** CSV↔JSON; semilla 2026 de 10 tarifas (todas
> **pendientes** de validación) y metodología honesta. Coste y actividad
> publicados: **dato no disponible**. Ver `docs/PROBLEMA_FUENTE_CONGRESO.md`,
> `docs/SPRINT_PILOTO.md` y `docs/HOJA_DE_RUTA.md`.

## Estructura

- `adapters/congreso.py` — descubridor del listado + constructor de endpoints
  oficiales + normalizador de composición. Solo lectura, sin red.
- `metrics.py` — cálculo puro: sesión de fondo, periodo de gracia (90 días),
  coste nominal + anualizado. Las tarifas pendientes **nunca** entran.
- `build_site.py` — genera el estático (`index.html`, ficha, metodología,
  `llms.txt`) desde SQLite piloto. Sin frameworks, lectura sin JavaScript.
- `ingest_csv.py` — **vía manual verificada** (no depende de la red): los CSV
  del exportador del navegador (`Cargo;NombreOrgano;Nombre;Grupo;FechaAlta;FechaBaja`)
  → SQLite. Reejecutable sin duplicar, fallo visible por fichero, manifiesto con hash.
- `scripts/fetch_composiciones.py` — descarga secuencial (1 req/s) con hash,
  gzip y manifiesto. Requiere `curl`.
- `collector.py`, `schema.sql` — esqueleto inicial (CLI mínimo y esquema base).
- `rates_seed.csv` — 10 tarifas oficiales 2026, **todas pendientes**.
- `tests/` — parsers con fixtures reales + métricas + web + ingesta CSV. `16/16`.
- `docs/` — sprint piloto, staging y narrativa del bloqueo de la fuente.

## Uso

```bash
python3 -m unittest discover -s tests -v
python3 build_site.py   # genera web/ + data/comisiones.db (solo revisión local)

# Vía manual verificada (CSV descargados del navegador; no toca la red):
python3 ingest_csv.py --csv-dir data/csv --db data/comisiones.db
python3 build_site.py
```

Servir en local solo para revisar:

```bash
python3 -m http.server 8137 --bind 127.0.0.1
```

## Presupuesto

~13 MB de pico medido, web de 68 KB, cron semanal secuencial con `nice -n 19`,
1 petición/segundo y `User-Agent` identificable. Nada residente.

## Goteo (fuentes inestables)

Si el Congreso limita por volumen, ingesta nocturna lenta en lugar de serie rápida:

```bash
nice -n 19 python3 scripts/fetch_composiciones.py --out data/bruto-congreso \
  --limit 8 --sleep 25
```

8 comisiones/noche ≈ ciclo completo en una semana (la composición cambia
despacio). Máximo 3 intentos por sesión; ante `503`/HTML, parar y registrar el
fallo en el manifiesto en vez de insistir.

## Rigor

- Cada cifra con fuente enlazada, vigencia y fecha de corte.
- Coste siempre como **ESTIMACIÓN**; incompatibilidades entre cargos aún sin modelar.
- Lenguaje descriptivo, nunca acusatorio. Solo cargos públicos agregados.
- Si falta un dato: “dato no disponible”, nunca un cero.
- Canal de corrección: pendiente de buzón público.

## Licencia

AGPL-3.0. Ver `LICENSE`.
