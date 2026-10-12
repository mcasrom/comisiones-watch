# Sprint piloto — comisiones.pruebapublica.com

Estado: **Fase 0 cerrada con GO reducido; fases 1–3 pendientes**. Alcance máximo: demostrar que la ingesta real es viable con recursos justos y rigor editorial. No promete un observatorio completo.

## Resultado de la Fase 0

- Congreso: la página `/es/opendata/organos` responde con UA de navegador (`200`, ~94 KB), pero es lenta (**13–30 s**) y el flujo de composición depende de AJAX Liferay:
  `resourceIDOrganos` con `_opendata_tipoConsulta=3` y `_opendata_legislatura=15`.
  La misma petición devolvió después `500` de borde Akamai y luego `503`; `robots.txt` tampoco fue accesible.
  Conclusión: **endpoint identificado, pero no estabilidad suficiente para prometer automatismo semanal**.
- Senado: XML `ficopendataservlet?tipoFich=7&legis=15` y `robots.txt` devuelven `403` Akamai desde portátil y server. No hay alternativa abierta equivalente; queda como esqueleto + semilla manual.
- Tarifas 2026 verificadas en las páginas oficiales de transparencia: Congreso, presidente de comisión `1.712,50 €`; Senado, presidente `1.738,36 €`, con reglas explícitas de incompatibilidad/compatibilidad.
- **Corte aplicado: `GO reducido`**. Continuar solo con Congreso en modo lectura, reintentos y caché; no declarar la ingesta autónoma hasta reproducir tres ejecuciones limpias.

## Punto de partida

- `PROMPT_OPENCODE.md`: objetivo y restricciones correctos, pero sobredimensiona la autonomía.
- `schema(1).sql`: buen esqueleto. Faltan estados de tarifa, compatibilidad entre complementos y control de reprocesado.
- `collector(1).py`: solo `init`, `snapshot`, `load-rates` y un `report` mínimo. Faltan `ingest`, `compute`, `build-site`, adaptadores y tests.
- Archivos con sufijo `(1)`: renombrarlos al crear el repo de trabajo.

## Evidencia medida antes del sprint

- Congreso, `/es/opendata/organos`: accesible con UA de navegador, `200`, ~94 KB, pero tarda **13–30 s** y la exportación de composición usa flujo dinámico Liferay con `_organos_statusOpenData=true`.
- Senado, XML `ficopendataservlet?tipoFich=7&legis=15`: `403` Akamai desde portátil y server; hasta `robots.txt` está bloqueado.
- Tarifas públicas localizadas para 2026: Congreso, presidente de comisión `1.712,50 €`; Senado, presidente `1.738,36 €`; el Senado tiene reglas especiales de compatibilidad y cambios temporales.
- Servidor: hay margen en reposo, pero la memoria y la red son justas; nada pesado ni concurrente.

## Deltas mínimos de esquema tras la Fase 0

- `pay_rates.status`: `pendiente_validacion` o `aprobada`, más fecha y URL de fuente.
- Nueva tabla de compatibilidades entre complementos, porque la vista actual sumaría cargos incompatibles por separado.
- Nueva tabla/control de ejecuciones de ingesta con resultado y motivo, para que el fallo sea visible.
- No usar años ni importes sin vigencia; registrar la regla de las 14 pagas como supuesto explícito.

## Reglas del piloto

1. Primero Congreso; Senado queda como esqueleto + semilla manual hasta resolver el `403`.
2. Ninguna cifra sin consulta SQL documentada, fuente, vigencia y fecha de corte.
3. Tarifa nueva o dudosa: `pendiente_validacion`, sin publicar su coste.
4. Parser roto: fallo visible, conservar la web buena y no publicar a medias.
5. Lenguaje descriptivo: “sin sesiones de fondo registradas”; jamás acusación ni ilegalidad presunta.
6. Solo cargos públicos agregados por cargo/comisión; “dato no disponible”, nunca cero inventado.

## Fase 0 — inspección y corte (2–4 h)

1. Mapear endpoints reales del Congreso: listado, composición, cargos y exportación.
2. Guardar fixtures mínimos y documentar selectores/URLs exactas.
3. Completar semilla 2026 de tarifas Congreso/Senado con URL y vigencia.
4. Diseñar deltas mínimos del esquema: estado de tarifa, compatibilidades, control de ingesta.
5. Medir una descarga representativa: tiempo, memoria con `/usr/bin/time -v` y disco.
6. Decisión:
   - `GO Congreso`: hay endpoint estable y reproducible.
   - `GO reducido`: Congreso automático + Senado manual.
   - `NO-GO`: si el Congreso también exige sesión/JS inestable; aparcar sin construir más.

## Fase 1 — adaptador mínimo del Congreso: **completada en lectura**

- Descubre **50 comisiones** desde el HTML real mediante el identificador estable `_organos_codComision`, sin scraping de detalle.
- Clasifica secciones reales: 23 legislativas, 11 permanentes no legislativas, 8 de investigación y 8 mixtas.
- La captura de listado costó **125.386 bytes, HTTP 200, 0,24 s y 13 MB** desde el server; el análisis local tarda **0,003 s**.
- Extrae los endpoints oficiales de la ficha 301: composición, sesiones/convocatorias, iniciativas e intervenciones.
- **Vía CSV verificada (12-oct, descarga manual del dueño):** el botón «Exportar datos composición» devuelve `Composicion_<Órgano>_<leg>.csv` con `Cargo;NombreOrgano;Nombre;Grupo;FechaAlta;FechaBaja`. La muestra 301 coincide **85/85** con el JSON.
- **URL de exportación probada (`_organos_statusOpenData=true…Suborgano=301`):** sin sesión devuelve el HTML de la página, no el fichero; con sesión, `503`. Mis propias sondas de hoy han **empeorado el límite de la IP**: ahora hasta la página da `503`. Automatización aparcada varios días como mínimo; la descarga manual desde navegador sigue funcionando.
- Normaliza una muestra real de composición: **85 filas**, constitución `2023-12-04`; presidente, vicepresidencias, secretarías, portavocías y vocalías con fechas `DD/MM/AAAA`; `Adscritos` y `Letrados` quedan pendientes de diccionario.
- **Carga manual por CSV (`ingest_csv.py`):** valida cabecera exacta, órgano único conocido, fechas y filas; resuelve la comisión contra el descubrimiento, reejecutable sin duplicar, manifiesto con hash y corte, fallo visible por fichero. Probado con el CSV real 301 (85 filas). Flujo: descargar del navegador a `data/csv/` → `python3 ingest_csv.py --csv-dir data/csv --db data/comisiones.db`.
- **Contenido activado (12-oct):** 4 CSV ingeridos sin errores (Constitucional 85, Exteriores 99, Justicia 93, Defensa 101 = **378 filas**) y `build_site.py` hecho **aditivo** (ya no borra lo ingerido; genera una ficha por comisión con composición). Tests **16/16**.
- La descarga masiva de las 50 composiciones se intentó con sesión, `Referer` y limitación a 1 req/s: las fichas responden `200`, pero el recurso JSON devolvió HTML en todas. El reintento acotado posterior (tras 4 min de pausa) escaló a `503` incluso en la página: el origen está limitando nuestra IP por el volumen de hoy. Vía automática **aparcada**; no se almacenó composición masiva inválida. Si se reintenta, que sea en otra sesión y fuera de pico.
- Pruebas: **6/6 en `demo/comisiones/fase1`**. No se tocan sesiones ni tarifas todavía.

## Fase 2 — tarifas y métricas mínimas: **completada en cálculo**

- Semilla 2026 con 10 tarifas oficiales Congreso/Senado, todas en `pendiente_validacion`; la del Senado no pudo descargarse por su `403`.
- `metrics.py` calcula sesión de fondo, días sin sesión, sesiones por mes y periodo de gracia de 90 días.
- El coste devuelve nominal y equivalente anualizado para no ocultar las 14 pagas; las tarifas pendientes jamás entran en el cálculo.
- Pruebas: **11/11 en `demo/comisiones/fase1`**. Falta modelar incompatibilidades múltiples antes de publicar costes.

## Fase 3 — web mínima: **completada como prototipo no desplegado**

- Genera `index.html`, ficha 301, metodología y `llms.txt` desde SQLite piloto.
- Las cifras disponibles usan consultas documentadas; coste y actividad aparecen como dato no disponible.
- Páginas más pesada: ficha 301 con 30.078 bytes; lectura sin JavaScript y filtro progresivo.
- Pruebas: **12/12 en `demo/comisiones/fase1`**. Quedan fuera tarjetas, mapa de calor y despliegue.

## Criterios de aceptación del piloto

- Una comisión real recorre todo el flujo: fuente → snapshot → métrica → web.
- Coste, actividad y ranking se reproducen con SQL documentado.
- Parser, métricas y periodo de gracia tienen tests.
- Medición registrada de RAM, tiempo y disco dentro del presupuesto.
- Lista cerrada de unknowns y causas de fallo visibles.

## Riesgos principales

- Senado `403` persistente.
- Congreso lento o con sesión inestable.
- Agendas ambiguas y sesiones no públicas.
- Alcance editorial si el coste se presenta como cobro exacto.
- Crecer hacia tarjetas, mapas o comparativas antes de tener datos estables.
