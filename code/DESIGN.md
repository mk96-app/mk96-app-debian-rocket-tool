# MK96 Debian Rocket Tool — diseño actual

Applet de bandeja para GNOME (Ubuntu, Wayland) que se conecta a un servidor Rocket.Chat
propio y asigna **sonidos distintivos** a salas/DMs concretos y a las menciones, para
reconocer por el oído de quién llega una notificación sin mirar la pantalla. Solo genera
sonido/notificación para chats explícitamente configurados como "especiales" — el resto de
la actividad de Rocket.Chat se ignora por completo (no es un notificador general).

## Requisitos de sistema

- `python3-gi` (PyGObject).
- `gir1.2-ayatanaappindicator3-0.1` — icono de bandeja (extensión GNOME Shell
  `ubuntu-appindicators` necesaria en GNOME vanilla, viene por defecto en Ubuntu).
- `gir1.2-secret-1` — Secret Service (GNOME Keyring) para guardar credenciales.
- `python3-yaml` — config no sensible.
- `paplay` (PulseAudio/PipeWire) — reproducción de sonidos.
- `python3-pytest` para los tests.

## Ejecutar y testear

```
python3 -m mk96_app_debian_rocket_tool.app   # arranca la app
python3 -m pytest                        # corre los tests de lógica pura
```

## Arquitectura

- **`poller.py`** — polling periódico (GLib) sobre la REST API de Rocket.Chat, **una
  instancia por servidor conectado**. Las peticiones corren en un hilo
  (`async_utils.run_in_thread`) y los callbacks vuelven siempre al hilo principal; solo
  hay un sondeo en vuelo a la vez. Tras un fallo de red reintenta con backoff exponencial
  (`backoff_ticks`); un 401 (`AuthError`) detiene el polling y avisa de token inválido. Las
  salas cuyo historial falló se reintentan aunque el delta de suscripciones no las traiga.
  Detalle del sondeo:
  `subscriptions.get` en modo delta para detectar salas con actividad, e
  historial (`channels.history`/`im.history` con cursor `oldest`, paginado) para los
  mensajes nuevos de las salas que interesan a alguna regla. Decide si un
  mensaje ya fue leído comparando su `ts` contra el `ls` de la suscripción -así
  no suena si ya lo leíste en el propio Rocket.Chat. Intervalo configurable por
  servidor (15/30/60s); repetición de aviso configurable por regla (una vez / N
  veces / infinito) mientras el mensaje siga sin leer.
- **`rules.py`** — función pura `match_rule(evento, reglas)`. Reglas de tipo `sala` (por
  `room_id`) o `mencion` (global); una regla de sala coincidente tiene prioridad. La regla
  de mención puede incluir `@all`/`@here` (`mencion_todos`, desactivado por defecto).
- **`quiet_hours.py`** — lógica pura de No molestar: silencio manual temporal desde la
  bandeja (1 h / 4 h / indefinido) y horario silencioso recurrente (admite tramos que
  cruzan la medianoche). Durante el silencio los chats no suenan ni notifican pero siguen
  apareciendo en la bandeja; los recordatorios de reuniones no se silencian.
- **`autostart.py`** — arranque con la sesión por usuario (`~/.config/autostart/`, con
  override `Hidden=true` si el paquete instaló el de sistema vía debconf).
- **`async_utils.py`** — `run_in_thread(work, on_done)`: trabajo bloqueante fuera del hilo
  de GTK, resultado entregado en el hilo principal.
- **`sound_manager.py`** — resuelve un `sonido_id` a fichero (busca primero en la carpeta de
  sonidos propios del usuario, luego en la paleta empaquetada) y lo reproduce con `paplay`
  vía `subprocess` (mismo enfoque "shell-out a CLI" que usa `pactl` en mk96-app-debian-switchboard).
- **`secret_store.py`** — wrapper sobre libsecret para URL del servidor, user id y token.
  Si el Secret Service no está disponible, falla explícitamente (sin fallback inseguro a
  texto plano).
- **`config.py`** — `~/.config/mk96-app-debian-rocket-tool/config.yaml`: lista de reglas y caché
  de nombres de sala. Nunca guarda credenciales.
- **`rest_client.py`** — todas las llamadas REST: listar salas, historial (con cursor
  `oldest`), suscripciones (`subscriptions.get`, para el polling de `poller.py`), enviar
  mensaje. El PAT se usa directamente como `X-Auth-Token`/`X-User-Id`, sin login previo.
- **`tray.py`** — menú AppIndicator: estado de conexión, notificaciones especiales
  recientes (abren `chat_window` al hacer clic), submenús "Alertas" y "Reuniones" (con acceso directo a su pestaña de
  Configuración), "Configuración...",
  "No molestar", "Salir".
- **`settings_window.py`** — ventana "Configuración": `Gtk.Notebook` con los paneles
  Servidores (por defecto), Alertas y Reuniones, y un botón "Aceptar" común.
- **`servers_window.py`** — panel "Servidores": lista de servidores con estado de
  conexión, formulario de conexión (URL + user id + PAT + intervalo), "Probar conexión"
  (`rest_client.check_connection`: prueba lo escrito, sin guardar, en un hilo), conectar /
  desconectar / eliminar, y arranque automático con la sesión.
- **`alerts_window.py`** — panel "Alertas": selector de servidor + reglas de sonido (sala +
  sonido, con selector de archivo para sonidos propios; regla de mención global con
  `@all`/`@here`) y horario silencioso de No molestar. No gestiona conexiones: buscar
  salas nuevas exige que el servidor esté conectado. Pensada para fusionarse más adelante
  con `servers_window.py` como pestañas de una sola ventana de ajustes.
- **`chat_window.py`** — historial de solo lectura de una sala + respuesta de una línea.
- **`meetings.py`** — calendario local de reuniones: modelo de datos y lógica pura de
  recurrencia (`next_occurrence`) y de qué reunión debe avisar en cada tick
  (`due_meetings`). Sin GLib ni GTK, testeada como el resto de la lógica del proyecto.
- **`meeting_scheduler.py`** — temporizador GLib (30s) que llama a `due_meetings` e
  invoca sonido + notificación + aviso persistente en bandeja; funciona sin servidor
  Rocket.Chat conectado.
- **`meetings_calendar.py`** — construye las vistas de calendario Día/Semana/Mes
  (`Gtk.Grid`/`Gtk.Box`) a partir de las funciones puras de solapes/rejilla de
  `meetings.py` (`occurrences_in_range`, `assign_lanes`, `filas_para_bloque`,
  `posicion_columna`); no repite lógica de recurrencia ni de solapes, solo la dibuja.
  Las reuniones inactivas se siguen mostrando (atenuadas con la clase CSS
  `meeting-off`, gris) y siguen siendo clicables, para que la única vía de reactivarlas o
  borrarlas -las vistas de calendario- nunca las deje inalcanzables.
- **`meetings_window.py`** — panel solo de calendario: selector/navegación de vistas
  Día/Semana/Mes (delegadas en `meetings_calendar.py`) y botón "+ Nueva reunión". En
  Día/Semana el clic izquierdo (arrastrando) selecciona una franja de la rejilla (filas de
  30 min, dentro de un día) y el clic derecho sobre ella ofrece crear una reunión con ese
  inicio y duración; el resaltado y la marca roja de la hora actual (exacta al minuto, se
  mueve cada 20 s) se pintan con cairo en el `draw` de cada hueco. Con clic derecho en una
  reunión, un hueco o un día (Mes) se abre un popover (clic fuera lo cierra); "+N más" del mes salta a la
  vista Día: hueco → "Añadir reunión aquí"; reunión →
  Editar / Activar-Desactivar / Eliminar, y en una serie se pregunta "solo esta o toda la
  serie". Las reuniones que coinciden en hora no se validan ni se bloquean: se dibujan en
  carriles lado a lado (las inactivas, atenuadas). Vista por defecto: Semana. Los diálogos se abren con `GLib.idle_add`, fuera del
  manejador del clic, para que reciban el foco.
- **Ocurrencias sueltas** (`meetings.py`): `meeting["excepciones"]` = `{"YYYY-MM-DDTHH:MM":
  "borrada"|"inactiva"}`. Solo se aplican en `next_occurrence` (por donde pasan avisos,
  bandeja y calendario), con un bucle que termina siempre; el calendario usa
  `ocurrencias_visibles` para seguir viendo las inactivas. Editar la serie conserva las
  excepciones salvo que cambie fecha_hora/repetición (`reunion_editada`). Reactivar una
  serie desactivada es siempre de toda la serie: no hay excepciones "activa".
- **`meeting_dialog.py`** — diálogo modal de alta/edición (Cancelar / Guardar, y Borrar
  con confirmación al editar): título, fecha, hora, duración, repetición, aviso previo,
  sonido, enlace y notas. La validación está en `validate_meeting_form` (pura).

## Almacenamiento y persistencia

- **Secretos**: Secret Service (`gir1.2-secret-1`). Nunca en `config.yaml`.
- **Config no sensible**: `~/.config/mk96-app-debian-rocket-tool/config.yaml`.
- **Reuniones**: `reuniones` en el mismo `config.yaml` -sin credenciales, así que no
  pasa por Secret Service.
- **Sonidos de usuario**: `~/.local/share/mk96-app-debian-rocket-tool/sounds/user/` — el
  paquete Debian nunca escribe ni limpia ahí, así que sobrevive a actualizaciones,
  reinstalaciones o `apt purge` seguido de reinstalación.
- **Sonidos empaquetados**: `mk96_app_debian_rocket_tool/sounds/` (instalados junto al paquete
  Python) — paleta CC0, ver `sounds/LICENSES.md` para el registro de licencias exigido
  antes de añadir cualquier fichero.

## Empaquetado `.deb` (`debian/`)

Mismo patrón que mk96-app-debian-switchboard: paquete Debian nativo
(`debian/source/format: 3.0 (native)`), dos carpetas hermanas `code/` y `versions/`.
`./build.sh` desde la raíz lee la versión de `debian/changelog`, compila con
`dpkg-buildpackage -us -uc -b` y mueve el resultado a `versions/<versión>/`. Autoarranque
configurable por debconf (`mk96-app-debian-rocket-tool.templates`/`.config`, `postinst`/`postrm`
gestionan `/etc/xdg/autostart/`).

## Historial: por qué REST y no WebSocket

La primera versión usaba la Realtime API (WebSocket/DDP) de Rocket.Chat. Se
descartó en favor del polling REST actual porque el `login` DDP (necesario
para autenticar el socket) es justo el mecanismo que Rocket.Chat marca como
deprecado y sin mantenimiento activo, con comportamiento dependiente de 2FA y
sin manejo de errores fiable. El polling sobre REST usa endpoints estables y
activamente mantenidos. Detalle completo del análisis y del diseño en
`docs/superpowers/specs/2026-08-14-rest-polling-design.md`.

También relevante para las reglas de tipo `sala`: si una sala configurada no
dispara sonido, lo primero a revisar es su preferencia de notificación en
Rocket.Chat (aunque el polling no depende de las push notifications como sí
dependía el WebSocket, conviene descartar primero que la sala esté archivada o
que el usuario ya no sea miembro).

## Testing

`tests/` cubre la lógica pura de cada módulo (motor de reglas, parseo/normalización de
config, resolución de `sonido_id`, decisiones de polling/repetición de `poller.py`) sin
mocks de D-Bus/red/libsecret — mismo enfoque que mk96-app-debian-switchboard.

## Backlog (no implementado)

- Reenvío de notificaciones especiales a Discord (webhook), ntfy.sh/Gotify o Telegram (bot
  personal).
- Regla "por persona en cualquier sala" (hoy solo por sala/DM concreto o mención global).
- Respuestas enriquecidas en `chat_window` (adjuntos, hilos, indicador de escritura).
