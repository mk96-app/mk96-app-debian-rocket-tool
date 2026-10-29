# Sustitución de WS/DDP por polling REST + recordatorios configurables

## Contexto y motivación

`rc_client.py` implementa la conexión Realtime API (DDP sobre WebSocket) de
Rocket.Chat, suscrita a `stream-notify-user/<uid>/notification` para recibir
eventos en tiempo real. Se descarta este enfoque por varias razones
acumuladas durante el análisis del proyecto:

- El `login` DDP con `resume` (necesario para autenticar el socket) es
  justo el mecanismo que Rocket.Chat marca como **deprecado y sin
  mantenimiento activo** ("Method Calls" de la Realtime API) — su
  comportamiento puede cambiar sin aviso entre versiones. Desde la 8.0.0,
  además, los method calls siempre se resuelven por HTTP internamente,
  aunque técnicamente se invoquen sobre el socket.
- El PAT usado como `resume` token puede fallar en silencio si la cuenta
  tiene 2FA activo y el PAT no se creó con "Ignorar autenticación de dos
  factores" marcado — y el código actual no distingue ese fallo de un
  login correcto (`_on_status_changed(True)` se dispara al recibir
  `connected`, antes de confirmar el `login`).
- El formato exacto del payload de `stream-notify-user` (`payload.mention`,
  etc.) nunca se validó contra un servidor real — riesgo abierto documentado
  en el `DESIGN.md` original.
- Es una app de un único usuario para sonidos de aviso: la latencia de
  polling (15-60s) no tiene coste real de UX frente a la fragilidad del
  camino WS.

Se sustituye por polling puro sobre la REST API oficial (activamente
mantenida), y se aprovecha el cambio para añadir dos capacidades que no
existían: intervalo de poll configurable por servidor, y repetición
configurable del aviso mientras un mensaje siga sin leer.

## Cómo se determina "leído"

Rocket.Chat expone en `subscriptions.get` el campo `ls` (last seen) por
sala: el timestamp hasta el que el usuario ha leído esa sala, actualizado
por **cualquier** cliente real de Rocket.Chat (web/móvil/desktop) cuando
abre la sala. Nuestras llamadas de solo lectura (GET) nunca modifican `ls`.

Comparando el timestamp de un mensaje (`msg.ts`) contra `ls`:

- `msg.ts > ls` → no leído en ningún cliente → candidato a sonar.
- `msg.ts <= ls` → ya leído (en la propia app de Rocket.Chat, por ejemplo)
  → no sonar, y si había un recordatorio pendiente para esa sala, se
  cancela.

Esto resuelve de forma nativa el caso de "estoy respondiendo en Rocket.Chat
y no quiero que además me suene aquí": en el siguiente poll, `ls` ya habrá
avanzado por delante del mensaje.

## Modelo de datos (`config.py`)

### Servidor

Nuevo campo:

```yaml
poll_interval_s: 30   # uno de {15, 30, 60}, por defecto 30
```

### Regla

Nuevos campos (con valores por defecto que preservan el comportamiento
actual — sonar una vez):

```yaml
repeticion_modo: una_vez        # "una_vez" | "n_veces" | "infinito"
repeticion_n: null               # entero >=1, solo si modo == "n_veces".
                                  # Es el TOTAL de sonidos para ese aviso
                                  # (incluye el primero), no repeticiones
                                  # adicionales.
repeticion_cada_polls: 1          # entero >=1, cada cuántos ciclos de poll
                                  # del servidor se repite. Solo relevante
                                  # si modo != "una_vez". El intervalo
                                  # efectivo en segundos es siempre
                                  # `repeticion_cada_polls * poll_interval_s`
                                  # del servidor de esa regla — múltiplo
                                  # garantizado por construcción, sin
                                  # necesidad de validar nada.
```

`normalize_server` y `normalize_rule` se actualizan para rellenar estos
campos con sus valores por defecto si faltan (igual que ya hacen con
`activa`, `etiqueta`, etc.).

## Componentes

### `poller.py` (nuevo, sustituye a `rc_client.py`)

Responsable de:

1. Un temporizador GLib (`GLib.timeout_add_seconds(poll_interval_s, ...)`)
   que dispara un "tick" de poll.
2. Mantener, por sala, un cursor en memoria (`ultimo_ts_procesado`) y un
   posible estado de recordatorio pendiente:
   `{rid: {"regla_id": ..., "count": int, "last_sound_tick": int}}`.
3. Un contador de ticks transcurridos (para comparar contra
   `repeticion_cada_polls`).
4. Exponer los mismos callbacks que `RocketChatClient` ofrecía
   (`on_event`, `on_status_changed`) para minimizar cambios en `app.py`,
   más un evento por cada repetición (no solo la primera detección).

Toda la lógica de decisión (¿toca sonar?, ¿toca repetir?, ¿está leído?) se
extrae a funciones puras testeables sin red, en el propio `poller.py` o en
`rules.py` según corresponda — siguiendo el patrón ya establecido en el
proyecto (funciones puras + wrapper con efectos).

Funciones puras nuevas propuestas:

- `is_message_read(msg_ts, last_seen_ts) -> bool`
- `should_fetch_room(subscription, reglas_activas, hay_regla_mencion) -> bool`
  — decide si vale la pena pedir el historial de esa sala (evita peticiones
  para salas que no interesan a ninguna regla).
- `should_repeat(pending_state, regla, tick_actual) -> bool`
  — dado el estado de recordatorio de una sala y la config de repetición
  de su regla, decide si toca volver a sonar en este tick.

### `rest_client.py` (ampliación)

- `list_subscriptions(updated_since: str | None) -> dict` — envuelve
  `GET subscriptions.get` (con `date=updated_since` si se proporciona,
  para pedir solo lo cambiado).
- `room_history(room_id, tipo, count=50, oldest=None)` — se añade el
  parámetro `oldest` (ISO timestamp) para pedir solo mensajes posteriores
  a un cursor, en vez de siempre los últimos 50.

### `app.py`

- Sustituye la instanciación de `RocketChatClient` por `Poller`.
- `_on_event` se reutiliza tal cual para el aviso inicial; se añade que
  las repeticiones también pasen por el mismo camino (mismo sonido,
  misma notificación de escritorio) — no hace falta lógica nueva aquí,
  el `Poller` ya decide cuándo re-emitir el evento.

### `settings_window.py`

- Selector de intervalo de poll (15/30/60s) en la sección de conexión del
  servidor.
- En el editor de regla: selector de modo de repetición
  (una vez / N veces / infinito), campo numérico para N (solo visible si
  modo = "n_veces"), y campo numérico para "cada cuántos polls" (solo
  visible si modo != "una_vez").

## Flujo de datos (cada tick de poll)

1. `subscriptions.get?date=<último_poll>` → lista de subs cambiadas desde
   el poll anterior.
2. Para cada sub cambiada: `should_fetch_room` decide si esa sala interesa
   (tiene una regla `sala` activa para su `rid`, o hay alguna regla
   `mención` activa — en cuyo caso cualquier sala es candidata). Si no
   interesa a ninguna regla, se ignora sin gastar una petición de
   historial.
3. Para las salas que sí interesan: `room_history(rid, tipo, oldest=cursor_actual_de_esa_sala)`.
4. Para cada mensaje nuevo devuelto:
   - Si `sender == propio_usuario` → se ignora (no hay que notificarse a
     uno mismo).
   - Se evalúa `match_rule` (sin cambios) para decidir si hay regla
     aplicable.
   - Si hay regla y `is_message_read(msg.ts, sub.ls)` es `False` → es la
     primera detección de este aviso: sonar, notificar, y si
     `repeticion_modo != "una_vez"` crear estado de recordatorio pendiente
     para esa sala.
   - Se avanza el cursor de la sala al `ts` del mensaje más nuevo visto,
     se haya sonado o no.
5. Para las salas con recordatorio pendiente de ticks anteriores: si en
   este tick `sub.ls` ya alcanzó/superó el mensaje pendiente → se borra el
   estado (ya está leído, se acabaron los recordatorios). Si sigue sin
   leer, `should_repeat` decide si toca sonar de nuevo según
   `repeticion_cada_polls` y `repeticion_modo`/`repeticion_n`.

## Arranque y casos límite

- Al conectar (primer poll tras arrancar la app o reconectar), no hay
  cursor previo: se toma como línea base el estado actual (`ls` de cada
  sub relevante) sin disparar ningún sonido retroactivo por historial ya
  existente. Solo se notifican mensajes que lleguen a partir de ese
  momento.
- Si una petición HTTP falla (red caída, servidor no responde), se
  registra el fallo (mismo patrón `notify_error` que ya usa `app.py` para
  errores de listar salas) y se reintenta en el siguiente tick sin perder
  el cursor ni el estado de recordatorios acumulado hasta ese punto.
- El estado de recordatorios pendientes y los cursores por sala viven en
  memoria del proceso, igual que la conexión WS actual tampoco persistía
  su estado entre reinicios de la app — un reinicio antes de leer un
  mensaje reinicia también su contador de repeticiones.
- Si el usuario desactiva una regla desde la bandeja mientras tiene un
  recordatorio pendiente para su sala, el siguiente tick deja de repetir
  (la regla ya no está en `reglas_activas`).

## Testing

Se mantiene el enfoque actual (funciones puras, sin mocks de red/D-Bus):

- `is_message_read`, `should_fetch_room`, `should_repeat`: tests unitarios
  puros con distintas combinaciones de `ts`/`ls`/estado/config.
- `normalize_server`/`normalize_rule`: casos con y sin los nuevos campos,
  verificando los valores por defecto.
- `rest_client.room_history` con `oldest`: verificar que se añade el
  parámetro a la query cuando se proporciona.
- Se elimina `tests/test_rc_client_logic.py` (o se adapta lo reutilizable)
  y se añade `tests/test_poller_logic.py`.

## Fuera de alcance (backlog)

- Persistir el estado de recordatorios pendientes entre reinicios de la
  app.
- Repetición configurable también para la regla de "mención" de forma
  independiente por sala (hoy comparte el mismo estado por sala que la
  regla de tipo "sala" que aplique, según la prioridad ya existente en
  `rules.py`).
