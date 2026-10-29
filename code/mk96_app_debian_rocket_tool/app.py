"""Punto de entrada: carga config/credenciales, arranca la bandeja y gestiona las
conexiones a Rocket.Chat (puede haber varios servidores conectados a la vez, cada uno con
su propio polling), conectando el motor de reglas con el sonido y las notificaciones.
También arranca el planificador de avisos de reuniones, independiente de la conexión a
Rocket.Chat.

Las peticiones de red nunca se hacen en el hilo de GTK: el polling usa su propio hilo
(ver poller.py) y el resto de acciones pasan por async_utils.run_in_thread."""

import logging
import os
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from mk96_app_debian_rocket_tool import config as config_module
from mk96_app_debian_rocket_tool import gtk_helpers, secret_store
from mk96_app_debian_rocket_tool import meetings as meetings_module
from mk96_app_debian_rocket_tool.async_utils import run_in_thread
from mk96_app_debian_rocket_tool.chat_window import ChatWindow
from mk96_app_debian_rocket_tool.gtk_helpers import notify_error, notify_message
from mk96_app_debian_rocket_tool.meeting_scheduler import MeetingScheduler
from mk96_app_debian_rocket_tool.notifier import notify_meeting_reminder, notify_special_message
from mk96_app_debian_rocket_tool.poller import Poller
from mk96_app_debian_rocket_tool.quiet_hours import (
    has_manual_silence,
    is_quiet,
    quiet_status_text,
    silence_until,
)
from mk96_app_debian_rocket_tool.rest_client import (
    PRESENCE_STATUSES,
    RestApiError,
    RestClient,
    is_insecure_url,
)
from mk96_app_debian_rocket_tool.rules import match_rule, rooms_to_mark_read
from mk96_app_debian_rocket_tool.settings_window import SettingsWindow
from mk96_app_debian_rocket_tool.sound_manager import (
    USER_SOUNDS_DIR,
    SoundPlaybackError,
    play_sound,
)
from mk96_app_debian_rocket_tool.tray import Tray, build_status_lines

log = logging.getLogger(__name__)


class Application:
    def __init__(self):
        self._config = config_module.load_config()
        # servidor_id -> {"rest_client", "poller", "connected"}
        self._connections = {}
        # rid -> (servidor_id, room_type): de qué servidor es cada sala que ha avisado
        self._room_origin = {}
        self._settings_window = None
        self._chat_windows = {}

        self._tray = Tray(
            self._open_settings,
            self._open_chat,
            gtk_helpers.open_url,
            self._ask_mark_read,
            self._set_presence,
            self._open_sounds_folder,
            self._set_quiet,
        )

        self._meeting_scheduler = MeetingScheduler(
            lambda: self._config["reuniones"], self._on_meeting_due, self._on_scheduler_tick
        )
        self._meeting_scheduler.start()
        self._on_scheduler_tick()

        active_servers = config_module.get_active_servers(self._config)
        for server in active_servers:
            self._connect(server["id"])
        if not active_servers:
            self._open_settings()

    # -- Conexión ------------------------------------------------------------------

    def _server_name(self, servidor_id: str) -> str:
        server = next((s for s in self._config["servidores"] if s["id"] == servidor_id), None)
        return server["nombre"] if server else servidor_id

    def _connect(self, servidor_id: str) -> None:
        server_config = next(
            (s for s in self._config["servidores"] if s["id"] == servidor_id), None
        )
        if server_config is None:
            return
        try:
            credentials = secret_store.load_server_credentials(servidor_id)
        except secret_store.SecretStoreUnavailable as exc:
            notify_error("Secret Service no disponible", str(exc))
            return
        if credentials is None:
            notify_error("Falta la credencial", "Este servidor no tiene credenciales guardadas.")
            return

        previous = self._connections.pop(servidor_id, None)
        if previous is not None:
            previous["poller"].stop()

        if is_insecure_url(credentials["server_url"]):
            notify_message(
                "Conexión sin cifrar",
                f"{server_config['nombre']} usa http://: el token viajaría en claro. "
                "Usa https:// si el servidor lo permite.",
                icon="dialog-warning",
            )

        config_module.set_server_active(self._config, servidor_id, True)
        config_module.save_config(self._config)

        rest_client = RestClient(
            credentials["server_url"], credentials["user_id"], credentials["token"]
        )
        poller = Poller(
            rest_client,
            server_config.get("poll_interval_s", 30),
            lambda: config_module.rules_for_server(self._config, servidor_id),
            lambda event: self._on_event(servidor_id, event),
            lambda connected: self._on_connection_status_changed(servidor_id, connected),
            self._tray.remove_recent_notification,
            lambda: self._on_auth_error(servidor_id),
        )
        self._connections[servidor_id] = {
            "rest_client": rest_client,
            "poller": poller,
            "connected": True,
            "username": None,
            "error": None,
        }
        poller.start()
        self._refresh_known_rooms(servidor_id)
        self._set_server_status(servidor_id, "conectado")
        self._update_tray_connection()
        self._refresh_tray_rules()

    def _disconnect(self, servidor_id: str) -> None:
        connection = self._connections.pop(servidor_id, None)
        if connection is not None:
            connection["poller"].stop()
        config_module.set_server_active(self._config, servidor_id, False)
        config_module.save_config(self._config)
        self._set_server_status(servidor_id, "desconectado")
        self._update_tray_connection()
        self._refresh_tray_rules()

    def _delete_server(self, servidor_id: str) -> None:
        try:
            secret_store.clear_server_credentials(servidor_id)
        except secret_store.SecretStoreUnavailable as exc:
            notify_error("No se pudo borrar la credencial", str(exc))

    def _on_connection_status_changed(self, servidor_id: str, connected: bool) -> None:
        connection = self._connections.get(servidor_id)
        if connection is None:
            return
        poller = connection["poller"]
        connection["connected"] = connected
        connection["username"] = poller.username if connected else None
        connection["error"] = None if connected else poller.last_error
        self._set_server_status(
            servidor_id,
            "conectado" if connected else "error",
            connection["username"] if connected else connection["error"],
        )
        self._update_tray_connection()
        if not connected:
            notify_error(
                f"Sin conexión con {self._server_name(servidor_id)}",
                "Se reintentará automáticamente.",
            )

    def _on_auth_error(self, servidor_id: str) -> None:
        connection = self._connections.get(servidor_id)
        error = connection["poller"].last_error if connection is not None else None
        if connection is not None:
            connection["connected"] = False
            connection["username"] = None
            connection["error"] = error
        self._set_server_status(servidor_id, "error", error)
        self._update_tray_connection()
        notify_error(
            f"Token no válido en {self._server_name(servidor_id)}",
            "El servidor rechazó las credenciales (puede que el token se haya revocado). "
            "Actualízalas en Configuración y pulsa Conectar.",
        )

    def _update_tray_connection(self) -> None:
        lines = build_status_lines(
            [
                {"nombre": self._server_name(servidor_id), **{k: c[k] for k in ("connected", "username", "error")}}
                for servidor_id, c in self._connections.items()
            ]
        )
        self._tray.set_connection_status(
            any(c["connected"] for c in self._connections.values()), lines
        )

    def _set_server_status(self, servidor_id: str, status: str, detail: str | None = None) -> None:
        if self._settings_window is not None:
            self._settings_window.set_server_status(servidor_id, status, detail)

    def _refresh_tray_rules(self) -> None:
        varios = len(self._connections) > 1
        reglas = []
        for servidor_id in self._connections:
            for rule in config_module.rules_for_server(self._config, servidor_id):
                if varios:
                    etiqueta = rule["etiqueta"] or rule.get("room_id") or "Mención"
                    rule = {**rule, "etiqueta": f"{self._server_name(servidor_id)} · {etiqueta}"}
                reglas.append(rule)
        self._tray.set_rules(reglas, self._on_toggle_rule)

    def _on_toggle_rule(self, rule_id: str, activa: bool) -> None:
        for rule in self._config["reglas"]:
            if rule["id"] == rule_id:
                rule["activa"] = activa
        config_module.save_config(self._config)
        self._refresh_tray_rules()
        if self._settings_window is not None:
            self._settings_window.set_config(self._config)

    def _refresh_known_rooms(self, servidor_id: str) -> None:
        connection = self._connections.get(servidor_id)
        if connection is None:
            return

        def done(rooms, error):
            if error is not None:
                notify_error("No se pudieron listar las salas", str(error))
            elif self._settings_window is not None:
                self._settings_window.set_known_rooms(servidor_id, rooms)

        run_in_thread(connection["rest_client"].list_rooms, done)

    # -- Eventos de Rocket.Chat ------------------------------------------------------

    def _on_event(self, servidor_id: str, event: dict) -> None:
        reglas_activas = config_module.rules_for_server(self._config, servidor_id)
        rule = match_rule(event, reglas_activas)
        if rule is None:
            return

        self._room_origin[event["rid"]] = (servidor_id, event.get("room_type") or "c")
        etiqueta = rule["etiqueta"] or event.get("sender") or "Rocket.Chat"

        # En silencio el chat sigue apareciendo en la bandeja, pero sin sonido ni aviso.
        if not is_quiet(self._config["no_molestar"], datetime.now()):
            try:
                play_sound(rule["sonido_id"])
            except SoundPlaybackError as exc:
                notify_error("No se pudo reproducir el sonido", str(exc))
            notify_special_message(etiqueta, event.get("sender"), event.get("text"))
        self._tray.add_recent_notification(etiqueta, event.get("rid"))

    def _ask_mark_read(self) -> None:
        dialog = Gtk.MessageDialog(
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            text="¿Marcar como leído?",
        )
        dialog.format_secondary_text(
            "Todos: todas las salas con mensajes sin leer. No configurados: solo las que no tienen una alerta de sala activa."
        )
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("No configurados", Gtk.ResponseType.NO)
        dialog.add_button("Todos", Gtk.ResponseType.YES)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self._mark_rooms_read(solo_no_configuradas=False)
        elif response == Gtk.ResponseType.NO:
            self._mark_rooms_read(solo_no_configuradas=True)

    def _mark_rooms_read(self, solo_no_configuradas: bool) -> None:
        jobs = [
            (
                connection["rest_client"],
                list(config_module.rules_for_server(self._config, servidor_id)),
            )
            for servidor_id, connection in self._connections.items()
            if connection["connected"]
        ]
        if not jobs:
            return

        def work():
            marcados, total, errores = 0, 0, []
            for client, reglas in jobs:
                try:
                    rids = rooms_to_mark_read(
                        client.list_subscriptions(), reglas, solo_no_configuradas
                    )
                except RestApiError as exc:
                    errores.append(f"No se pudieron leer los chats: {exc}")
                    continue
                total += len(rids)
                for rid in rids:
                    try:
                        client.mark_room_read(rid)
                        marcados += 1
                    except RestApiError as exc:
                        errores.append(str(exc))
            return marcados, total, errores

        def done(result, error):
            if error is not None:
                notify_error("Error al marcar leídos", str(error))
                return
            marcados, total, errores = result
            if errores:
                notify_error(
                    "Error al marcar leídos",
                    f"{marcados}/{total} marcados. Error: {errores[0]}",
                )
            else:
                notify_message(
                    "Chats leídos",
                    f"{marcados} chat(s) marcados." if marcados else "Nada sin leer.",
                    icon="mail-read",
                )

        run_in_thread(work, done)

    def _set_presence(self, status: str) -> None:
        clients = [
            connection["rest_client"]
            for connection in self._connections.values()
            if connection["connected"]
        ]
        if not clients:
            return

        def work():
            errores = []
            for client in clients:
                try:
                    client.set_presence(status)
                except RestApiError as exc:
                    errores.append(str(exc))
            return errores

        def done(errores, error):
            if error is not None:
                errores = [str(error)]
            if errores:
                notify_error("Error al cambiar estado", errores[0])
            else:
                notify_message("Estado", PRESENCE_STATUSES[status], icon="user-available")

        run_in_thread(work, done)

    def _open_sounds_folder(self) -> None:
        # El directorio solo existe tras añadir el primer sonido propio.
        os.makedirs(USER_SOUNDS_DIR, exist_ok=True)
        gtk_helpers.open_url(USER_SOUNDS_DIR)

    # -- No molestar -------------------------------------------------------------------

    def _set_quiet(self, duracion: str) -> None:
        """duracion: "1h", "4h", "indefinido" u "off" (ver quiet_hours.silence_until)."""
        self._config["no_molestar"]["silenciado_hasta"] = silence_until(
            datetime.now(), duracion
        )
        config_module.save_config(self._config)
        self._refresh_quiet_state()

    def _refresh_quiet_state(self) -> None:
        ahora = datetime.now()
        self._tray.set_quiet(
            quiet_status_text(self._config["no_molestar"], ahora),
            has_manual_silence(self._config["no_molestar"], ahora),
        )

    # -- Reuniones -------------------------------------------------------------------

    def _on_meeting_due(self, meeting: dict, ocurrencia: datetime, momento: str) -> None:
        sonido_id = meeting.get("sonido_id") or meetings_module.DEFAULT_MEETING_SONIDO_ID
        try:
            play_sound(sonido_id)
        except SoundPlaybackError as exc:
            notify_error("No se pudo reproducir el sonido", str(exc))

        notify_meeting_reminder(
            meeting["titulo"], ocurrencia.strftime("%H:%M"), meeting.get("enlace"), momento
        )
        self._tray.add_pending_meeting(meeting["id"], meeting["titulo"], meeting.get("enlace"))

    def _on_scheduler_tick(self) -> None:
        self._refresh_upcoming_meetings()
        self._refresh_quiet_state()

    def _refresh_upcoming_meetings(self) -> None:
        ahora = datetime.now()
        con_ocurrencia = []
        for meeting in self._config["reuniones"]:
            ocurrencia = meetings_module.next_occurrence(meeting, ahora)
            if ocurrencia is not None:
                con_ocurrencia.append((ocurrencia, meeting))
        con_ocurrencia.sort(key=lambda par: par[0])

        upcoming = [
            {
                "id": meeting["id"],
                "titulo": meeting["titulo"],
                "hora_texto": ocurrencia.strftime("%d/%m %H:%M"),
            }
            for ocurrencia, meeting in con_ocurrencia[:3]
        ]
        self._tray.set_upcoming_meetings(upcoming)

    def _on_meetings_changed(self, config: dict) -> None:
        self._config = config
        config_module.save_config(config)
        self._refresh_upcoming_meetings()

    # -- Ventana de configuración ------------------------------------------------------

    def _open_settings(self, pagina: str | None = None) -> None:
        """pagina: pestaña a mostrar ("servidores", "alertas" o "reuniones"); sin ella, la
        ventana se abre en Servidores y, si ya estaba abierta, se deja como está."""
        if self._settings_window is None:
            server_callbacks = {
                "on_config_changed": self._on_servers_config_changed,
                "on_connect": self._connect,
                "on_disconnect": self._disconnect,
                "on_delete_server": self._delete_server,
            }
            alert_callbacks = {"on_config_changed": self._on_config_changed}
            self._settings_window = SettingsWindow(
                self._config, server_callbacks, alert_callbacks, self._on_meetings_changed
            )
            self._settings_window.connect("destroy", self._on_settings_closed)
            self._sync_window_statuses(self._settings_window)
            for servidor_id in self._connections:
                self._refresh_known_rooms(servidor_id)
        if pagina is not None:
            self._settings_window.show_page(pagina)
        self._settings_window.present()

    def _on_settings_closed(self, _widget) -> None:
        self._settings_window = None

    def _sync_window_statuses(self, window) -> None:
        for servidor_id, connection in self._connections.items():
            if connection["connected"]:
                window.set_server_status(servidor_id, "conectado", connection["username"])
            else:
                window.set_server_status(servidor_id, "error", connection["error"])

    def _on_servers_config_changed(self, config: dict) -> None:
        """Alta/baja/edición de servidores: además de guardar, la ventana de alertas
        (si está abierta) debe ver la lista de servidores nueva."""
        self._on_config_changed(config)
        if self._settings_window is not None:
            self._settings_window.set_config(self._config)

    def _on_config_changed(self, config: dict) -> None:
        self._config = config
        config_module.save_config(config)
        self._refresh_tray_rules()
        self._refresh_quiet_state()

    # -- Ventana de chat ---------------------------------------------------------------

    def _open_chat(self, room_id: str) -> None:
        if room_id is None:
            return
        if room_id in self._chat_windows:
            self._chat_windows[room_id].present()
            return

        origin = self._room_origin.get(room_id)
        if origin is None:
            rule = next(
                (
                    r
                    for r in self._config["reglas"]
                    if r.get("room_id") == room_id and r["servidor_id"] in self._connections
                ),
                None,
            )
            if rule is not None:
                origin = (rule["servidor_id"], rule.get("room_type") or "c")
        if origin is None or origin[0] not in self._connections:
            return

        servidor_id, room_type = origin
        titulo = self._config["salas_cache"].get(room_id, room_id)
        window = ChatWindow(
            self._connections[servidor_id]["rest_client"], room_id, room_type, titulo
        )
        window.connect("destroy", lambda _w: self._chat_windows.pop(room_id, None))
        self._chat_windows[room_id] = window

    def shutdown(self) -> None:
        for connection in self._connections.values():
            connection["poller"].stop()
        self._meeting_scheduler.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app = Application()
    try:
        Gtk.main()
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
