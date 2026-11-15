# Qué se puede buscar sobre inactividad y coste

No todo lo que falta es investigable. Esta es la separación.

## 1. Actividad: qué se puede confirmar

| Fuente | Qué permite comprobar | Límite |
|---|---|---|
| **Diario de Sesiones del Congreso** | Si hubo sesión, orden del día y comparecencias | No siempre hay transcripción de todo |
| **BOCG del Congreso** | Convocatorias, constitución, iniciativas y acuerdos | No equivale a actividad efectiva |
| **Calendario/convocatorias de comisiones** | Fechas previstas y órdenes del día | Una convocatoria no prueba que se celebrara |
| **Actas** | Desarrollo de la sesión | No todas son públicas o accesibles |
| **Opendata de intervenciones** | Intervenciones transcritas | Un 0 puede ser un hueco, no una ausencia |

Consultas útiles:
- `site:congreso.es "Comisión de Investigación" "apagón" 28 de abril`
- `site:congreso.es "Pegasus" "Comisión de Investigación"`
- `site:congreso.es "Comisión de Presupuestos" convocatoria`
- `site:congreso.es "Comisión del Estatuto" convocatoria`
- `site:congreso.es "gastos reservados" comisión`

## 2. Constitución y composición

- **BOCG**: acuerdo de creación, constitución y nombres.
- **Composición oficial del Congreso**: cargos y fechas de alta/baja.
- **Senado**: BOCG y Diario de Sesiones; no hay catálogo abierto de composición.
- **Límite**: una comisión constituida no tiene por qué reunirse; la naturaleza permanente o no permanente cambia la lectura (Reglamento del Congreso, arts. 50 y 51).

## 3. Iniciativas y resultados

- **Opendata de iniciativas**: ya cruzado en la base.
- **BOCG**: texto, enmiendas y estado.
- **Diario de Sesiones**: debate y votación.
- **Límite**: la ley publicada no se atribuye por comisión en la fuente; no se inventa.

## 4. Senado: caso RTVE

Se puede buscar:
- Comisión de investigación sobre RTVE en **Senado**: constitución y convocatorias.
- **BOCG del Senado** y **Diario de Sesiones**.
- Retribuciones y complementos: régimen económico del Senado.
- La información de **Cadena SER** (12-oct-2026) como contexto, no como medición propia.

No se puede:
- Descargar composición estructurada del Senado: no hay catálogo abierto (respuesta oficial 15-nov-2026).
- Automatizar sin autorización.

## 5. Coste: qué sí y qué no

Sí:
- **Tarifas oficiales** del Congreso y del Senado.
- **Normativa**: Constitución, art. 71.4; régimen económico de las Cámaras.
- **Datos agregados** de transparencia, si se publican.

No:
- **Nóminas individuales**.
- **Justificantes de percepción**.
- **Coste real por comisión**.
- Multiplicar tarifas por meses: es una estimación, no un coste acreditado.

## 6. Conclusión operativa

- **0 fechas** = no consta actividad en la fuente. No es “no se reunió” ni “no trabajó”.
- **0 fechas + iniciativas** = posible dato incompleto; revisar actas.
- **Convocatoria sin acta** = actividad no confirmada.
- **Acta sin intervenciones** = actividad confirmada, pero no aparece en el volcado.
- **Sin nóminas** = no hay coste acreditable.

## Qué actualizar si aparece una fuente

1. Fecha, URL y página.
2. Si confirma sesión: actualizar `Fechas` y `Última`.
3. Si confirma inactividad: dejar `0` con la nota y la fuente.
4. Si confirma percepción: añadir importe solo con justificante; si no, `no consta`.
5. No convertir una ausencia en incumplimiento ni en fraude.
