# mk96-app-debian-rocket-tool

**MK96 Debian Rocket Tool**: applet de bandeja para Ubuntu/GNOME (Wayland) que se conecta a tu
servidor [Rocket.Chat](https://rocket.chat) y hace sonar un **sonido distinto para cada chat**.
Así reconoces por el oído quién te escribe sin mirar la pantalla.

Solo suena y notifica para los chats que tú configuras como "especiales" y para las
menciones. El resto de la actividad de Rocket.Chat se ignora por completo: no es un
notificador general.

Además incluye un calendario de reuniones con recordatorios, un modo No molestar y algunas
herramientas de bandeja (presencia, marcar como leído).

## Qué hace

### Sonidos por chat y por mención

- **Reglas de sala:** asocias un sonido a una sala o mensaje directo concreto.
- **Regla de mención:** un sonido para cuando te mencionan en cualquier sala. Opcionalmente
  también para `@all` y `@here` (desactivado por defecto).
- Si hay regla de sala y de mención a la vez, gana la de sala.
- **No suena si ya lo leíste:** compara la hora del mensaje con tu última lectura en Rocket.Chat,
  así que si lo viste en el propio Rocket.Chat no vuelve a sonar.
- **Repetición del aviso**, configurable por regla: una vez, N veces o sin límite mientras el
  mensaje siga sin leer.
- **Varios servidores** Rocket.Chat a la vez, cada uno con su intervalo de sondeo (15, 30 o 60 s).

### Sonidos

- Incluye una paleta de **501 sonidos** (packs de [Kenney](https://kenney.nl), licencia CC0 /
  dominio público) organizados en seis categorías: digital, impactos, interfaz, jingles
  musicales, RPG y ciencia ficción.
- Puedes usar **sonidos propios** desde una regla. Se guardan en
  `~/.local/share/mk96-app-debian-rocket-tool/sounds/user/`, y ni las actualizaciones ni
  desinstalar el paquete los tocan.

### No molestar

- **Silencio manual** desde la bandeja: 1 hora, 4 horas o hasta que lo desactives.
- **Horario silencioso** recurrente, que admite tramos que cruzan la medianoche.
- Durante el silencio los chats no suenan ni notifican, pero siguen apareciendo en la bandeja.
  Los recordatorios de reuniones no se silencian.

### Reuniones

Un calendario local (funciona aunque no estés conectado a ningún servidor):

- Vistas **Día, Semana y Mes** (por defecto, Semana).
- Cada reunión tiene título, fecha, hora, duración, repetición, aviso previo, sonido, enlace y
  notas.
- Reuniones recurrentes. Al editar o borrar una de una serie, la app pregunta si es solo esa
  ocurrencia o toda la serie.
- Seleccionas una franja arrastrando en la rejilla y, con clic derecho, creas la reunión ahí.
  Las reuniones que coinciden en hora se dibujan lado a lado, sin bloqueos.
- El aviso llega con sonido, notificación de escritorio y un aviso persistente en la bandeja.

### Menú de la bandeja

| Entrada | Para qué sirve |
|---|---|
| Estado de conexión | Muestra si cada servidor está conectado |
| Notificaciones especiales recientes | Al hacer clic se abre el historial de esa sala |
| Configuración... | Abre la ventana de ajustes (pestañas Servidores, Alertas y Reuniones) |
| Alertas | Lista tus reglas con una casilla para activar o desactivar cada una |
| Reuniones | Muestra las próximas reuniones y da acceso a su configuración |
| Herramientas | "Marcar como leído...", cambiar tu estado (disponible, ausente, ocupado, invisible) y abrir la carpeta de sonidos propios |
| No molestar | Silencio de 1 hora, 4 horas o indefinido, y "Desactivar" |
| Salir | Cierra la aplicación |

### Ventana de chat

Historial de solo lectura de una sala y respuesta de una línea, sin abrir Rocket.Chat.

### Ventana de Configuración

- **Servidores:** URL, identificador de usuario, token personal y intervalo de sondeo. Incluye
  "Probar conexión" (comprueba lo escrito sin guardarlo), conectar, desconectar, eliminar y
  arranque automático con la sesión.
- **Alertas:** reglas de sonido por sala y por mención, y el horario silencioso.
- **Reuniones:** el calendario.

## Seguridad de las credenciales

- La URL del servidor, el identificador de usuario y el token se guardan en el **Secret Service
  de GNOME (Keyring)**. Nunca en un archivo de configuración.
- Si el Secret Service no está disponible, la app falla de forma explícita en vez de guardar nada
  en texto plano.
- La app avisa si configuras un servidor con `http://`, porque el token viajaría sin cifrar.
- Usa un token de acceso personal (Personal Access Token) de Rocket.Chat, no tu contraseña.

## Requisitos

- Ubuntu con GNOME sobre Wayland.
- Extensión de GNOME Shell `ubuntu-appindicators` activada. Viene activada en Ubuntu. En GNOME
  "vanilla" hay que instalarla aparte, y sin ella no aparece el icono en la bandeja.
- `paplay` (paquete `pulseaudio-utils`) para reproducir los sonidos, con PulseAudio o PipeWire.
  Normalmente ya viene instalado, pero el `.deb` no lo declara como dependencia.
- `python3-gi`, `gir1.2-ayatanaappindicator3-0.1`, `gir1.2-secret-1` y `python3-yaml`. Si
  instalas el `.deb` con `apt`, se instalan solos como dependencias.
- Un servidor Rocket.Chat y un token de acceso personal.

## Instalación

1. Descarga el archivo `mk96-app-debian-rocket-tool_<versión>.deb` desde la sección
   [Releases](../../releases/latest) de este repositorio.
2. Instálalo con `apt`, para que resuelva las dependencias:

   ```
   sudo apt install ./mk96-app-debian-rocket-tool_26-10-1.deb
   ```

3. Durante la instalación se pregunta si quieres que la app arranque con la sesión
   (respuesta por defecto: "Si"). Puedes cambiarlo más tarde:

   ```
   sudo dpkg-reconfigure mk96-app-debian-rocket-tool
   ```

Para actualizar, instala el `.deb` nuevo encima. Para desinstalar:
`sudo apt remove mk96-app-debian-rocket-tool`.

## Primeros pasos

1. Arranca la aplicación desde el menú de aplicaciones ("MK96 Debian Rocket Tool") o con el
   comando `mk96-app-debian-rocket-tool`.
2. En el icono de la bandeja, abre **Configuración...** y, en la pestaña **Servidores**, añade
   tu URL, tu identificador de usuario y tu token personal. Pulsa "Probar conexión" y conecta.
3. En la pestaña **Alertas**, elige un servidor y crea una regla: la sala (o la mención) y el
   sonido que quieres asociarle.

## Dónde guarda los datos

| Qué | Dónde |
|---|---|
| Reglas, reuniones y caché de nombres de sala | `~/.config/mk96-app-debian-rocket-tool/config.yaml` |
| Credenciales | Secret Service de GNOME (Keyring) |
| Sonidos propios | `~/.local/share/mk96-app-debian-rocket-tool/sounds/user/` |

## Desarrollo

Ejecutar desde el código, en la carpeta `code/`:

```
python3 -m mk96_app_debian_rocket_tool.app   # arranca la app
python3 -m pytest                       # tests (requiere python3-pytest)
```

Los tests cubren la lógica pura de cada módulo (reglas, configuración, sondeo, reuniones,
horario silencioso), sin simular D-Bus, red ni libsecret.

### Compilar el `.deb`

Requiere `debhelper`, `python3-pytest` y `python3-yaml` (los tests se ejecutan durante la
compilación):

```
./build.sh
```

El script lee la versión de `code/debian/changelog`, compila con `dpkg-buildpackage` y deja el
resultado en `versions/<versión>/`. Esa carpeta no se sube a git.

### Versionado

Las versiones siguen el esquema **`AA-M-R`**: año (dos cifras), mes y número de release dentro
de ese mes. Por ejemplo, `26-10-1` es la primera release de octubre de 2026 y `26-10-2` sería la
segunda.

Para sacar una versión nueva:

1. Añade una entrada arriba de `code/debian/changelog` con la versión nueva y sus cambios.
2. Actualiza `version` en `code/pyproject.toml` (con puntos: `26.10.1`).
3. Ejecuta `./build.sh`.
4. Crea una release en GitHub con la etiqueta `v26-10-1` y adjunta el `.deb` generado.

## Cómo funciona por dentro

La app consulta periódicamente la API REST de Rocket.Chat (una consulta por servidor conectado)
y decide qué mensajes nuevos merecen sonar según tus reglas. Se eligió REST y no WebSocket
porque el inicio de sesión de la API en tiempo real está marcado como obsoleto por Rocket.Chat.
El diseño completo y las decisiones están en [`code/DESIGN.md`](code/DESIGN.md) y en
[`docs/superpowers/`](docs/superpowers/).

## Estructura del repositorio

```
.
├── build.sh                           Compila el .deb y lo deja en versions/<versión>/
├── README.md
├── .gitignore
├── docs/superpowers/
│   ├── plans/                         Planes de implementación (sondeo REST, reuniones, calendario)
│   └── specs/                         Especificaciones de diseño de esas funciones
└── code/
    ├── DESIGN.md                      Diseño en detalle y decisiones técnicas
    ├── pyproject.toml
    ├── debian/                        Empaquetado .deb (control, changelog, scripts de instalación)
    ├── mk96_app_debian_rocket_tool/        Código de la aplicación
    │   ├── app.py                     Arranque y coordinación
    │   ├── tray.py                    Icono y menú de bandeja
    │   ├── poller.py                  Sondeo periódico de Rocket.Chat
    │   ├── rest_client.py             Llamadas a la API REST
    │   ├── rules.py                   Qué regla corresponde a cada mensaje
    │   ├── quiet_hours.py             No molestar y horario silencioso
    │   ├── sound_manager.py           Localiza y reproduce los sonidos
    │   ├── secret_store.py            Credenciales en el Secret Service
    │   ├── config.py                  Configuración no sensible (config.yaml)
    │   ├── autostart.py               Arranque con la sesión
    │   ├── notifier.py                Notificaciones de escritorio
    │   ├── async_utils.py             Trabajo en segundo plano sin bloquear la interfaz
    │   ├── dbus_utils.py              Utilidades D-Bus
    │   ├── gtk_helpers.py             Constructores de elementos de interfaz
    │   ├── settings_window.py         Ventana de Configuración (pestañas)
    │   ├── servers_window.py          Pestaña Servidores
    │   ├── alerts_window.py           Pestaña Alertas
    │   ├── alert_dialog.py            Diálogo para crear o editar una regla
    │   ├── chat_window.py             Historial de una sala y respuesta rápida
    │   ├── meetings.py                Modelo y lógica de reuniones (recurrencia, avisos)
    │   ├── meeting_scheduler.py       Temporizador que lanza los avisos
    │   ├── meetings_window.py         Pestaña Reuniones
    │   ├── meetings_calendar.py       Vistas Día, Semana y Mes
    │   ├── meeting_dialog.py          Diálogo para crear o editar una reunión
    │   ├── icons/                     Icono symbolic de la bandeja
    │   └── sounds/default/            501 sonidos CC0 en seis categorías y LICENSES.md
    └── tests/                         Tests de la lógica pura de cada módulo
```

## Limitaciones conocidas

- Solo avisa de los chats que configuras. No es un cliente completo de Rocket.Chat: la ventana
  de chat es de solo lectura, con respuesta de una línea.
- Si una sala configurada no suena, revisa que no esté archivada y que sigas siendo miembro.
- Solo funciona con GTK3, porque la librería del icono de bandeja no existe para GTK4.
- Pensada y probada para Ubuntu con GNOME sobre Wayland. En otros entornos no está probada.

## Ideas pendientes

- Reenviar las notificaciones especiales a Discord, ntfy.sh/Gotify o Telegram.
- Regla "por persona" en cualquier sala (hoy solo por sala o mensaje directo concreto, o por
  mención).
- Respuestas enriquecidas en la ventana de chat (adjuntos, hilos, indicador de escritura).

## Licencia

MIT. El texto completo está en [`code/debian/copyright`](code/debian/copyright). Los sonidos
incluidos son CC0 (dominio público); el detalle está en
[`code/mk96_app_debian_rocket_tool/sounds/default/LICENSES.md`](code/mk96_app_debian_rocket_tool/sounds/default/LICENSES.md).
