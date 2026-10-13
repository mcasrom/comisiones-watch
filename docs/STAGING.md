# Staging — comisiones.pruebapublica.com

Estado (13-oct-2026): **piloto con repo público y cron de goteo instalado; sin DNS,
nginx ni web pública**. La vía CSV está versionada y probada. Actualizado tras
conciliar el estado del servidor con el repo (el servidor iba un commit por detrás
de `origin/main`; ya sincronizado en `664ebc0`).

## Cómo se ve ahora

- **Repo público**: `mcasrom/comisiones-watch` (rama `main`, AGPL-3.0).
- **Instalación**: `/home/deploy/comisiones-watch` (sin procesos residentes), **al día con `origin/main`**.
- Revisión local en `127.0.0.1` (`index.html`, `comision-301.html`, `metodologia.html`, `llms.txt`).

Contenido del piloto:

- 50 comisiones descubiertas.
- **Composición cargable por vía manual CSV** (`ingest_csv.py`): probada con 4
  comisiones (**378 filas**, 0 errores); muestra 301 confirmada **85/85** CSV↔JSON.
- 10 tarifas oficiales en `pendiente_validacion`; **cero tarifas aprobadas**.
- Cero sesiones cargadas; coste y actividad = «dato no disponible».
- Tests: **16/16**.
- `data/` y `web/` están en `.gitignore` (no se versiona contenido generado).

## Fuente de verdad

El propio repo público es la fuente de verdad. Los ficheros iniciales
`collector(1).py`, `schema(1).sql`, `README(1).md` quedan como referencia histórica.

## Qué falta para la activación completa

### Contenido mínimo publicable (pendiente)

1. Composición completa del Congreso actual, con diccionario de cargos.
2. Sesiones reales con clasificación de fondo y huecos declarados.
3. Tarifas aprobadas con vigencia, fuente, compatibilidades y criterio de 14 pagas.
4. Canal de corrección y registro de cambios.
5. Tres ejecuciones semanales limpias con medición de RAM, tiempo y disco.

### Activación técnica

1. ~~Crear el repo público `mcasrom/comisiones-watch`.~~ **Hecho** (12-oct).
2. ~~Instalar en `/home/deploy/comisiones-watch` sin procesos residentes.~~ **Hecho** (sincronizado a `origin/main` el 13-oct).
3. Crear el DNS en gris, emitir el certificado y pasarlo a naranja. **Pendiente.**
4. Configurar nginx estático, recargar con `nginx -t` y purgar Cloudflare. **Pendiente.**
5. Cron: **goteo nocturno instalado** (`30 3 * * *` →
   `/home/deploy/scripts/comisiones_goteo.sh`, 8 comisiones/noche, `--sleep 25`,
   aviso Telegram ante fallo) — **auto-aparcado hasta 2026-10-14** para enfriar el
   límite de IP del origen. Web pública y cron de publicación: **pendiente**.
6. Publicar `sitemap.xml`, `robots.txt`, `llms.txt`, tarjeta social y enviar el
   sitemap a Search Console. **Pendiente.**
7. Medir la ejecución completa con `/usr/bin/time -v` y documentar el informe final. **Pendiente.**

## Bloqueo de la fuente (resumen)

- Congreso: recurso `searchOrgano` intermitente (500/503/HTML); los reintentos
  agotan el límite por IP. Senado: `403` Akamai sistemático. Detalle en
  `docs/PROBLEMA_FUENTE_CONGRESO.md`. Vía automática **aparcada**; **plan B = vía
  manual CSV** (sigue funcionando desde el navegador).
- Carta de reutilización enviada al Senado (12-oct, Resend, `delivered`); borrador
  equivalente para Congreso/datos.gob.es.
