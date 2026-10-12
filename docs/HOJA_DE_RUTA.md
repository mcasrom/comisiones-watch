# Hoja de ruta — cómo seguir (12-oct-2026)

Estado: **piloto local, sin desplegar**. 4 comisiones con composición verificada
(Constitucional 85, Exteriores 99, Justicia 93, Defensa 101 = 378 filas),
listado de 50, semilla de 10 tarifas (todas pendientes), 0 sesiones. Tests 16/16.

## Flujo de trabajo actual

```bash
# 1. Descargar CSV del navegador a data/csv/
# 2. Ingerir (valida, manifiesto con hash, idempotente):
python3 ingest_csv.py --csv-dir data/csv --db data/comisiones.db
# 3. Regenerar la web (aditiva: no borra lo ingerido):
python3 build_site.py
# 4. Tests:
python3 -m unittest discover -s tests -v
# 5. Revisar en local:
python3 -m http.server 8137 --bind 127.0.0.1  # en web/
```

Descarga inicial: ~50 CSV una vez. Después: revisión mensual (el pipeline marca
qué cambió entre cortes).

## Lo que falta para publicar, por orden

1. **Canal de corrección** (decisión del dueño: buzón o formulario). Sin esto no
   hay publicación: un proyecto de datos público debe poder recibir errores.
2. **Cobertura**: 4 de 50 comisiones. O se descargan más CSV, o se publica una
   v0.1 explícitamente parcial (decisión del dueño).
3. **Tarifas aprobadas + incompatibilidades**: validar vigencia y fuente de la
   semilla 2026 y modelar cargos múltiples. Sin esto no hay ni una cifra.
4. **Sesiones reales** con clasificación de fondo (bloqueado: AJAX del Congreso
   inestable, Senado en 403; ver `PROBLEMA_FUENTE_CONGRESO.md`).
5. **Infra**: repo listo; falta DNS gris→naranja, nginx estático, cron semanal,
   sitemap/IndexNow, GSC y 3 ejecuciones limpias.

## Automatización

- Congreso: aparcada tras limitar la IP (`503`). Goteo preparado
  (`--limit 8 --sleep 25`, de madrugada); reintentar en otra sesión fuera de pico.
- Senado: bloqueado (`403` general, medido también desde casa). Vía principal:
  carta enviada el 12-oct (`informacion@senado.es`, plazo 5 días–1 mes).
- Carga manual por CSV mientras tanto (este flujo).

## Decisiones pendientes del dueño

- Buzón de corrección: ¿cuál?
- Alcance de publicación: ¿50 comisiones o v0.1 parcial?
- Umbral del filtro publicado y renombrados (ver sprint A si aplica).
