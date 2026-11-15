# comisiones-watch

Vigilancia ciudadana de las comisiones del Congreso (el Senado no ofrece datos abiertos de composición): **actividad
real frente a coste estimado** de sus cargos. Datos públicos verificables,
mismo rasero para todas las comisiones y todos los grupos.

> **Estado: desplegado** en <https://comisiones.pruebapublica.com>.
> 50 órganos del Congreso, 860 fechas de actividad, 225 iniciativas y 3.489 registros
> de composición. Las coincidencias ambiguas **no se atribuyen**: quedan como
> «sin atribuir» (43 intervenciones de las comisiones de investigación solapadas).
> Datos congelados en la XV legislatura, corte **2026-10-12**. El Senado confirmó el 15-nov-2026 que no tiene un catálogo abierto de composición de comisiones ni una vía de descarga masiva autorizada; por eso la composición es solo del Congreso. PNL,
> comparecencias solicitadas y coste siguen sin datos suficientes; se marcan,
> no se estiman. Tests: **32/32**.

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
- `tests/` — parsers con fixtures reales + métricas + web + ingesta CSV. `32/32`.
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

## Datos abiertos y rendimiento

- `/datos.csv` — una fila por comisión.
- `/data/datos.json` — mismo dataset con corte, URLs y estado de cada comisión.
- `/data/version.json` — corte, fecha de generación y **SHA-256** del JSON.
- `/data/personas.json` — personas, grupos y comisiones; `personas.html` es una
  página ligera (**~10 KB**) que busca y pagina en cliente sobre ese JSON.
- Actividad baja calculada con **mediana de pares**; las coincidencias ambiguas
  quedan **sin atribuir** y no suman fechas de actividad a ninguna comisión.
- Senado, PNL, comparecencias solicitadas, subcomisiones y coste siguen fuera:
  no hay fuente suficiente y no se estiman. En el Senado, la limitación es de origen: no hay catálogo abierto de composición de comisiones ni autorización de acceso masivo (respuesta oficial 15-nov-2026).

## Rigor

- Cada cifra con fuente enlazada, vigencia y fecha de corte.
- Coste siempre como **ESTIMACIÓN**; incompatibilidades entre cargos aún sin modelar.
- Lenguaje descriptivo, nunca acusatorio. Solo cargos públicos agregados.
- Si falta un dato: “dato no disponible”, nunca un cero.
- Canal de corrección: pendiente de buzón público.

## Licencia

AGPL-3.0. Ver `LICENSE`.

## Vigilancia del Senado

`scripts/watch_senado.py` consulta semanalmente el catálogo/transparencia del Senado y avisa solo si aparece una entrada nueva de composición de comisiones. No descarga datos ni evita el bloqueo. Programado los lunes a las 09:25; log en `/home/deploy/scripts/watch_senado.log`.

## Cruces y responsabilidad

La pestaña **Cruces** incluye tres lecturas:

- **Quién dirige:** presidencias, vicepresidencias y secretarías por grupo.
- **Quién acumula responsabilidades:** tabla de personas por número de comisiones y cargos directivos, con filtro.
- **Responsabilidad frente a actividad:** dispersión entre comisiones e intervenciones registradas.

Advertencia: acumular cargos no mide dedicación; las intervenciones no son asistencia ni calidad del trabajo. Solo se atribuyen cuando el nombre coincide exactamente.

## Actividad, inactividad y coste público

La página `/inactividad.html` recupera la pregunta fundacional: si una comisión puede mantener cargos y complementos sin actividad efectiva. Distingue constitución formal, funcionamiento y percepción económica; no calcula costes con tarifas teóricas y no atribuye fraude. Incluye comisiones sin actividad registrada, actividad testimonial, actividad interrumpida y dos casos de contexto (Presupuestos y Senado/RTVE).

## Inactividad e investigación

- **Inactividad:** comisiones sin actividad registrada, actividad testimonial e interrumpida; coste acreditado `s/d`.
- **Investigación:** actividad y cargos de las comisiones de investigación; sin dictamen ni conclusiones en la fuente.
- **Cruces:** cargos directivos por grupo, acumulación y dispersión responsabilidad-actividad; no es un ranking de trabajo.

**Coste:** no se calcula. No hay nóminas ni justificantes públicos; una tarifa oficial no prueba un pago. El indicador queda como `no calculable`, no como estimación.

## Caso de origen: Senado / RTVE

Ficha manual en `/caso-senado-rtve.html`. No forma parte de los 8 casos del Congreso: el Senado no ofrece catálogo abierto de composición. Se marca como fuente periodística y no se eleva a dato oficial ni a conclusión propia.
