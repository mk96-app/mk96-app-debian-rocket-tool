# Vistas de calendario (Día/Semana/Mes) para reuniones — diseño

## Objetivo

Sustituir la lista plana "Reuniones guardadas" de `MeetingsWindow` por tres vistas de
calendario navegables -Día, Semana y Mes- que muestren las reuniones en su hueco
temporal real (timeline por horas en Día/Semana, cuadrícula tipo calendario en Mes), en
vez de una lista de texto. Para que Día/Semana puedan dibujar un bloque con tamaño
proporcional, se añade una duración a cada reunión.

Fuera de alcance: sincronización con calendarios externos (ya excluido en el diseño
base), aviso de "fin de reunión" basado en la duración, y recordar entre sesiones qué
vista/periodo estaba abierto.

## Modelo de datos

Nuevo campo en cada reunión (`normalize_meeting` en `meetings.py`):

```yaml
duracion_min: 30   # minutos. Entero > 0. Reuniones guardadas antes de esta feature no
                    # tienen este campo -normalize_meeting le pone 30 por defecto
                    # (mismo valor que ya usamos para redondear la hora propuesta).
```

En el formulario de añadir/editar, un `Gtk.SpinButton` "Duración (min)" junto al campo
Hora: rango 5-480, paso 5, valor inicial 30 (igual patrón que `_aviso_spin`).

La duración es puramente visual: no cambia `meeting_scheduler.py` ni `due_meetings`/
`startup_due_meetings`, que siguen basándose solo en `fecha_hora` + `aviso_antes_min`.

## Lógica pura nueva (`meetings.py`, testeada con pytest)

Mismo criterio que el resto del módulo: funciones puras sobre dicts/fechas, sin GTK.

- `occurrences_in_range(meeting: dict, start: datetime, end: datetime) -> list[datetime]`
  — todas las ocurrencias de `meeting` en `[start, end)`, respetando
  `repeticion_modo`/`repeticion_dias`/`repeticion_fin`/`activa` (delega en
  `next_occurrence`, no duplica la lógica de recurrencia). Implementación: avanzar un
  cursor desde `start`, llamando a `next_occurrence(meeting, cursor)` y empujando el
  cursor a `ocurrencia + 1 minuto` tras cada hallazgo, hasta que `next_occurrence`
  devuelva `None` o la ocurrencia caiga fuera de `end`. Reunión inactiva -> lista vacía
  (ya lo garantiza `next_occurrence`).

- `assign_lanes(intervalos: list[tuple[datetime, datetime, Any]]) -> list[tuple[Any, int, int]]`
  — recibe una lista de `(inicio, fin, item)` (mismo día o misma columna) y devuelve,
  por cada `item`, en qué "carril" dibujarlo y cuántos carriles hay en total en ese
  grupo de solapes: `(item, carril, total_carriles)`. Algoritmo voraz clásico de
  colocación de intervalos solapados: ordenar por inicio; mantener una lista de
  "carriles ocupados hasta" (`fin` del último intervalo puesto en cada carril);
  para cada intervalo, usar el primer carril cuyo último `fin` sea <= su `inicio`, o
  abrir uno nuevo; `total_carriles` de un grupo de intervalos mutuamente conectados
  por solape es el máximo de carriles usados en ese grupo (todos los items de un mismo
  grupo comparten ese total, para que las columnas resultantes midan lo mismo).

- Ayuda de rango para Semana: `week_bounds(dia: date) -> tuple[date, date]` — devuelve
  `(lunes, lunes + 7 días)` de la semana que contiene `dia`. Mes se resuelve inline
  donde se usa (primer día del mes y primer día del mes siguiente), no hace falta una
  función dedicada.

## Estructura de `MeetingsWindow`

Se quita `self._list`/`_refresh_list`/`ListBox` de "Reuniones guardadas". En su lugar,
de arriba abajo:

1. **Selector de vista**: `Gtk.StackSwitcher` (o 3 `Gtk.RadioButton` en modo botón) con
   "Día", "Semana", "Mes".
2. **Barra de navegación**: `[<]  {texto del periodo}  [>]   [Hoy]`. El texto del
   periodo depende de la vista (ver cada sección). `<`/`>` retroceden/avanzan un
   día/semana/mes según la vista activa; "Hoy" recoloca el periodo mostrado sobre la
   fecha actual sin cambiar de vista.
3. **Área de contenido**: un `Gtk.Stack` con las tres vistas (Día/Semana/Mes); cambiar
   el selector cambia la página visible del stack. Cada vista se reconstruye entera
   (`for child in container.get_children(): container.remove(child)` + reconstrucción)
   cada vez que cambia el periodo, la vista, o `_on_config_changed` -mismo patrón que
   `_refresh_list` ya usaba, solo que ahora aplicado a la vista activa.
4. El formulario de añadir/editar y sus botones **no cambian**: pinchar un bloque de
   reunión en cualquiera de las tres vistas llama a `_load_meeting_into_form(meeting)`
   exactamente igual que hacía el `EventBox` de cada fila de la lista.

Estado nuevo en `__init__`: `self._vista_actual = "dia"` y `self._fecha_referencia =
date.today()` (el día/semana/mes que se está mirando; para semana y mes basta con
derivar el lunes/mes a partir de este `date`). Al abrir la ventana siempre se arranca en
Día mostrando hoy (no se persiste entre sesiones, según lo acordado).

## Vista Día

`Gtk.Grid` de dos columnas: la izquierda es el eje de horas (una etiqueta "07:00",
"07:30", ... "21:00" cada dos filas), la derecha es el área de bloques. Granularidad de
fila = 30 min (28 filas para cubrir 07:00-21:00), coincidiendo con el redondeo de hora
por defecto y el paso del `SpinButton` de duración.

Para el día mostrado: `occurrences_in_range(meeting, inicio_dia, fin_dia)` sobre todas
las reuniones activas, con `fin = ocurrencia + duracion_min`. Se pasa el resultado por
`assign_lanes` (todas las reuniones de ese día son "una columna"); cada reunión se
`grid.attach()` ocupando `ceil(duracion_min / 30)` filas, en la sub-columna que le tocó según `assign_lanes`, con ancho `1 / total_carriles` de
la columna derecha -el mecanismo GTK concreto (sub-grid homogéneo por franja de solape
vs. otra alternativa) se decide en el plan de implementación, igual que ya se hizo con
`normalize_meeting` en el diseño base.
Cada bloque es un `Gtk.Button`/`EventBox` con el título (y hora si cabe), que al
pincharse carga la reunión en el formulario -igual contrato que hoy.

Texto del periodo en la barra de navegación: `"lunes, 20 de agosto de 2026"` (nombre del
día en español, vía tabla local igual que `DIA_LABELS`, para no depender de locale del
sistema).

## Vista Semana

Mismo `Gtk.Grid` de timeline que Día, pero con 8 columnas: eje de horas + 7 columnas
(lunes a domingo), cada una con su propia cabecera de fecha ("lun 18", "mar 19", ...).
Por cada uno de los 7 días se calcula `occurrences_in_range` + `assign_lanes` de forma
independiente (los carriles no se comparten entre columnas de días distintos).

Texto del periodo: `"18 - 24 de agosto de 2026"` (rango lunes-domingo); si el rango
cruza de mes, `"29 ago - 4 sep 2026"`.

## Vista Mes

`Gtk.Grid` de 7 columnas (lun-dom) x 6 filas fijas (cubre cualquier mes, algunas celdas
de la primera/última fila caen en el mes anterior/siguiente y se muestran atenuadas,
igual que hace `Gtk.Calendar`). Cada celda es una `Gtk.Box` vertical: número del día
arriba, y debajo un `Gtk.Label`/botón por cada reunión de ese día con texto compacto
`"HH:MM Título"` (usa `occurrences_in_range` para todo el mes visible, agrupando por
`ocurrencia.date()`). Sin límite de cuántas entradas caben por celda -la fila de la
cuadrícula crece verticalmente si un día tiene muchas reuniones (no se implementa un
"+N más").

Texto del periodo: `"agosto de 2026"`.

## Casos límite

- **Reunión fuera de 07:00-21:00**: se recorta visualmente en Día/Semana anclándola al
  borde superior o inferior de la timeline (fila 0 o última fila) con un pequeño
  indicador (▲/▼ en el bloque) en vez de ocultarla o exigir ampliar el rango. En Mes no
  aplica (no hay eje horario).
- **`duracion_min` que no llega a media hora** (ej. 5 min): ocupa igualmente 1 fila
  completa (mínimo visual de 30 min), para que el bloque siga siendo legible y
  pinchable.
- **Reunión inactiva (`activa: false`)**: no aparece en ninguna vista (mismo criterio
  que ya aplica `next_occurrence`/"Próximas reuniones").
- **Mes con reunión recurrente diaria**: aparece en las ~30 celdas correspondientes;
  `occurrences_in_range` ya lo resuelve sin caso especial.

## Testing

- `occurrences_in_range` y `assign_lanes`: pytest puro (sin GTK), cubriendo: serie sin
  repetición dentro/fuera de rango, semanal con varios días marcados, mensual con día
  inexistente en algún mes del rango, reunión inactiva, solapes de 2 y 3 reuniones
  (incluyendo un solape parcial en cadena que separa en más de 2 carriles).
- Cableado GTK (construcción de las 3 vistas, navegación, click-to-edit): sin tests
  automáticos, igual criterio que el resto de `meetings_window.py`. Se verifica a mano
  con el mismo método usado para el autoformateo y el calendario emergente -Xvfb +
  eventos de teclado/señales simuladas- antes de darlo por bueno.
