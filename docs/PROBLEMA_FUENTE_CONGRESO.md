# Narrativa — el Congreso responde al navegador, pero no al pipeline

Fecha: 2026-10-12. Estado: vía automática **aparcada** con fallo visible.

## Lo que funciona

- El listado público `/es/comisiones` responde `200` (~125 KB) y expone los
  códigos estables `_organos_codComision`: **50 comisiones** descubiertas.
- Cada ficha expone en su JS los endpoints oficiales (`searchOrgano`,
  `opendataExport`, sesiones, iniciativas) con `codigoOrgano` y `codigoOrganoSup`.
- Una muestra real de composición (código 301) devolvió **85 filas** con cargos,
  fechas y grupos. Es la única composición válida conservada.

## Lo que falla

- El recurso AJAX `searchOrgano` es intermitente: un `POST` idéntico devolvió
  `500` de borde, después JSON válido una vez, después HTML `200` en las 50
  comisiones, y finalmente **`503` hasta en la página** tras varias series.
- El Senado está peor: XML y `robots.txt` devuelven `403` Akamai siempre.
- Patrón típico de **límite por IP tras volumen**: cada serie de reintentos
  empeoró la respuesta. No es un bug nuestro subsanable con más reintentos.

## Decisiones tomadas

1. No se almacenó ni un byte de composición masiva inválida.
2. La vía automática queda aparcada; el piloto publica solo lo verificado
   (listado + muestra 301 + tarifas pendientes + metodología honesta).
3. Si se reintenta, será en otra sesión, fuera de pico, con un máximo de
   3 intentos espaciados y el mismo registro de código/tipo/tiempo.

## Qué lo desbloquearía

- Que el recurso `searchOrgano` vuelva a responder JSON estable, o
- documentar el parámetro `formato` del recurso `opendataExport` para una
  descarga masiva en una sola petición, o
- una vía oficial alternativa (datos.gob.es solo enlaza al mismo servlet
  bloqueado).
