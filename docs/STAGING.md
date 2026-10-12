# Staging interno — comisiones.pruebapublica.com

Estado: **paquete piloto listo solo para revisión local**. No hay DNS, nginx, cron ni despliegue público.

## Cómo se ve ahora

Servidor local temporal, solo `127.0.0.1`:

- `http://127.0.0.1:8137/index.html`
- `http://127.0.0.1:8137/comision-301.html`
- `http://127.0.0.1:8137/metodologia.html`
- `http://127.0.0.1:8137/llms.txt`

Contenido del piloto:

- `web/`: 68 KB.
- `data/comisiones.db`: 72 KB.
- 50 comisiones descubiertas.
- Composición real cargada solo para la Comisión Constitucional, código 301.
- 10 tarifas oficiales en `pendiente_validacion`; cero tarifas aprobadas.
- Cero sesiones cargadas; coste y actividad publicados como dato no disponible.
- Tests: 12/12.

## Paquete staging

Fuente de verdad para una futura promoción:

- `demo/comisiones/fase1/adapters/congreso.py`
- `demo/comisiones/fase1/metrics.py`
- `demo/comisiones/fase1/build_site.py`
- `demo/comisiones/fase1/rates_seed.csv`
- `demo/comisiones/fase1/tests/`
- Salida generada de revisión: `demo/comisiones/fase1/web/`
- Base piloto de revisión: `demo/comisiones/fase1/data/comisiones.db`

Los ficheros iniciales `collector(1).py`, `schema(1).sql` y `README(1).md` quedan como referencia histórica; al crear el repo hay que normalizar sus nombres y completar los comandos ausentes.

## Qué falta para la activación completa

### Contenido mínimo publicable

1. Composición completa del Congreso actual, con diccionario de cargos.
2. Sesiones reales con clasificación de fondo y huecos declarados.
3. Tarifas aprobadas con vigencia, fuente, compatibilidades y criterio de 14 pagas.
4. Canal de corrección y registro de cambios.
5. Tres ejecuciones semanales limpias con medición de RAM, tiempo y disco.

### Activación técnica pendiente

1. Crear el repo público `mcasrom/comisiones-watch`.
2. Instalar en `/home/deploy/comisiones-watch` sin procesos residentes.
3. Crear el DNS en gris, emitir el certificado y pasarlo a naranja.
4. Configurar nginx estático, recargar con `nginx -t` y purgar Cloudflare.
5. Programar el cron semanal con `nice -n 19`, logs y avisos ante fallo silencioso.
6. Publicar `sitemap.xml`, `robots.txt`, `llms.txt`, tarjeta social y enviar el sitemap a Search Console.
7. Medir la ejecución completa con `/usr/bin/time -v` y documentar el informe final.

Nada de esta sección se ha ejecutado todavía.
