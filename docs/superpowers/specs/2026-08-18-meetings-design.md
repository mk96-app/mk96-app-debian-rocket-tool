# Recordatorios de reuniones / calendario local — diseño

## Objetivo

Añadir a la app un calendario propio, local y manual, para apuntar reuniones (fecha,
hora, repetición simple, enlace de videollamada, notas) y recibir aviso sonoro +
notificación de escritorio cuando llega la hora, con un recordatorio persistente en la
bandeja hasta que se descarte. No hay sincronización con calendarios externos (Google
Calendar, CalDAV, etc.) — eso queda fuera de alcance.

## Modelo de datos

Nueva sección `reuniones: []` en `~/.config/mk96-app-debian-rocket-tool/config.yaml`, al
mismo nivel que `reglas`. Sin credenciales ni datos sensibles, así que no toca
`secret_store.py`.

Cada reunión (dict normalizado por `normalize_meeting`):

```yaml
id: uuid                          # generado si falta, igual que normalize_rule
titulo: str
fecha_hora: "2026-08-20T10:00"    # ISO local, sin TZ (misma zona que el sistema).
                                   # Primera ocurrencia si repeticion_modo != ninguna.
repeticion_modo: ninguna | diaria | semanal | mensual
repeticion_dias: [lun, mar, mie, jue, vie, sab, dom]   # solo si semanal; lista de códigos
repeticion_fin: "2026-12-31" | null   # fecha (sin hora) tras la cual la serie no genera
                                        # más ocurrencias; null = indefinida
aviso_antes_min: 0                 # minutos de antelación del aviso; 0 = en el momento exacto
enlace: str | null                 # URL de videollamada u otra; opcional
notas: str                         # texto libre, opcional
sonido_id: str | null              # id de sonido (paleta o custom); null = sonido por
                                    # defecto de reuniones
activa: true                       # false = pausada, no genera avisos ni aparece en
                                    # "próximas" (pero no se borra)
```

`repeticion_modo: mensual` repite el mismo día del mes que `fecha_hora`. Si ese día no
existe en un mes dado (ej. día 31 en febrero), esa ocurrencia se omite ese mes (sin
recorte a fin de mes).

## Módulo `meetings.py` (lógica pura, testeable sin GLib/GTK)

Mismo enfoque que `rules.py`/`poller.py`: funciones puras sobre dicts/fechas, sin I/O.

- `normalize_meeting(raw: dict) -> dict` — aplica defaults, genera `id` si falta (igual
  patrón que `normalize_rule` en `config.py`; puede vivir en `config.py` junto a las
  demás funciones `normalize_*`, o en `meetings.py` — se decide en el plan de
  implementación según qué quede más cohesivo).
- `next_occurrence(meeting: dict, ahora: datetime) -> datetime | None` — próxima fecha/
  hora de la reunión estrictamente posterior a `ahora` (o igual, ver
  `due_meetings` más abajo), respetando `repeticion_modo`/`repeticion_dias`/
  `repeticion_fin`. Devuelve `None` si la serie ya terminó (`repeticion_fin` pasado, o
  `repeticion_modo: ninguna` con `fecha_hora` ya pasada) o si `activa` es `false`.
- `due_meetings(meetings: list, ahora: datetime, ultimo_chequeo: datetime) -> list` —
  reuniones cuyo aviso (ocurrencia − `aviso_antes_min`) cae dentro de la ventana
  `(ultimo_chequeo, ahora]`. Usar una ventana semiabierta con `ultimo_chequeo` evita
  duplicar el aviso entre ticks consecutivos del planificador. Devuelve la reunión junto
  con la ocurrencia concreta que dispara el aviso (ej. `(meeting, ocurrencia)`), porque
  la ventana/notificación necesitan mostrar la hora real de la reunión.

## Planificador

Vive en `app.py` (o un `meeting_scheduler.py` si `app.py` crece demasiado — se decide en
el plan). Un `GLib.timeout_add_seconds(30, ...)` propio, independiente del `Poller` de
Rocket.Chat: funciona sin servidor conectado y sin conexión activa.

En cada tick:
1. Carga `reuniones` de la config en memoria (ya cargada por `app.py`).
2. Llama a `due_meetings(reuniones, ahora, ultimo_chequeo)`; actualiza `ultimo_chequeo`.
3. Por cada reunión disparada:
   - reproduce sonido vía `sound_manager.play_sound` (con `sonido_id` de la reunión, o
     un sonido por defecto de reuniones nuevo en la paleta empaquetada — a añadir junto
     con el resto de sonidos, sujeto al mismo requisito CC0 de `sounds/LICENSES.md`),
   - dispara notificación de escritorio (reusar/extender `notifier.py`) con título, hora
     y, si tiene enlace, acción para abrirlo,
   - añade la reunión a un estado `pendientes` (lista en memoria en `Application`, no
     persistida) que la `Tray` pinta como recordatorio destacado hasta que el usuario la
     descarte explícitamente.

## UI: `meetings_window.py`

Ventana nueva, mismo estilo que `settings_window.py`:
- Lista de reuniones activas e inactivas, mostrando título + próxima ocurrencia
  calculada (vía `next_occurrence`) en vez de una fecha fija si es recurrente.
- Formulario añadir/editar con todos los campos del modelo; selector de sonido
  reutilizando el picker de sonido ya existente para reglas de sala (paleta +
  "elegir archivo propio").
- Borrar reunión (con confirmación, mismo patrón que borrar una regla si existe).
- Activar/desactivar sin borrar (`activa`).

## Integración en `tray.py`

- Si hay reuniones en estado `pendientes` (aviso disparado, no descartado): aparecen
  destacadas arriba del menú, con acción "Abrir enlace" (si `enlace`) y "Descartar"
  (quita de `pendientes`, no borra la reunión).
- Sección "Próximas reuniones": las 1–3 próximas por `next_occurrence`, con etiqueta +
  hora (no clicables, solo informativas — abrir el enlace antes de tiempo no aporta).
- Entrada "Reuniones..." (junto a "Configuración...") que abre `meetings_window`.

## Testing

`tests/test_meetings_logic.py`: `normalize_meeting`, `next_occurrence` (casos ninguna/
diaria/semanal/mensual, incluyendo mes sin ese día, serie terminada, reunión inactiva) y
`due_meetings` (ventana de aviso, no duplicados entre ticks, `aviso_antes_min: 0`).
Mismo enfoque sin mocks que el resto de la suite.

## Fuera de alcance (backlog)

- Sincronización con calendarios externos (Google Calendar, CalDAV, ICS import/export).
- Repetición avanzada tipo RRULE (intervalos "cada N semanas", excepciones puntuales).
- Invitar a otras personas / integración con salas de Rocket.Chat (crear reunión a partir
  de una sala, notificar a otros usuarios).
- Zonas horarias distintas a la del sistema.
