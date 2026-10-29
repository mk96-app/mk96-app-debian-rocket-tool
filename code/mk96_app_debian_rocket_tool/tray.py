"""Icono de bandeja (AyatanaAppIndicator3) con el estado de conexión, las notificaciones
especiales recientes, los avisos de reuniones (pendientes y próximas) y el acceso a las
ventana de configuración (servidores, alertas y reuniones).
"""

import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3, Gtk

from mk96_app_debian_rocket_tool.gtk_helpers import make_action_item, make_checkbox_item
from mk96_app_debian_rocket_tool.rest_client import PRESENCE_STATUSES

APP_ID = "mk96-app-debian-rocket-tool"
ICON_NAME = "mk96-app-debian-rocket-tool-symbolic"
ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")
MAX_RECENT_ITEMS = 10


def add_to_recent(recent: list, etiqueta: str, rid: str, max_items: int = MAX_RECENT_ITEMS) -> list:
    """Añade/actualiza la notificación de una sala al principio de la lista. Una misma
    sala (rid) nunca ocupa más de una entrada -si ya tenía una, se reemplaza y sube al
    principio en vez de apilarse encima de la anterior."""
    sin_esa_sala = [entry for entry in recent if entry["rid"] != rid]
    return ([{"etiqueta": etiqueta, "rid": rid}] + sin_esa_sala)[:max_items]


def remove_from_recent(recent: list, rid: str) -> list:
    """Quita la notificación de una sala, p.ej. al leerla u abrirla."""
    return [entry for entry in recent if entry["rid"] != rid]


def add_pending_meeting(pending: list, entry: dict, max_items: int = MAX_RECENT_ITEMS) -> list:
    """Añade/actualiza el aviso pendiente de una reunión (entry: {id, titulo, enlace}).
    Igual que add_to_recent, una misma reunión nunca ocupa más de una entrada y la lista
    se recorta a max_items para que los avisos sin descartar no crezcan sin límite."""
    sin_esa = [e for e in pending if e["id"] != entry["id"]]
    return ([entry] + sin_esa)[:max_items]


def remove_pending_meeting(pending: list, meeting_id: str) -> list:
    """Quita el aviso pendiente de una reunión, p.ej. al descartarlo."""
    return [entry for entry in pending if entry["id"] != meeting_id]


def build_status_lines(connections: list) -> list:
    """Líneas de estado de la parte alta del menú, una por servidor conectado
    ({nombre, connected, username, error}): "Conectado: @usuario", "Conectando a X..." o
    "X: error".
    Texto plano: el menú lo dibuja GNOME Shell y no admite colores. Con más de un
    servidor se añade el nombre para distinguirlos."""
    if not connections:
        return ["Desconectado"]
    varios = len(connections) > 1
    lines = []
    for conn in connections:
        if not conn["connected"]:
            lines.append(f"{conn['nombre']}: {conn['error'] or 'sin conexión'}")
        elif conn["username"]:
            sufijo = f" · {conn['nombre']}" if varios else ""
            lines.append(f"Conectado: @{conn['username']}{sufijo}")
        else:
            lines.append(f"Conectando a {conn['nombre']}...")
    return lines


class Tray:
    def __init__(
        self,
        on_open_settings,
        on_open_chat,
        on_open_meeting_link,
        on_mark_read,
        on_set_presence,
        on_open_sounds_folder,
        on_set_quiet,
    ):
        self._on_open_settings = on_open_settings
        self._on_open_chat = on_open_chat
        self._on_open_meeting_link = on_open_meeting_link
        self._on_mark_read = on_mark_read
        self._on_set_presence = on_set_presence
        self._on_open_sounds_folder = on_open_sounds_folder
        self._on_set_quiet = on_set_quiet
        self._quiet_text = None  # texto del silencio vigente (manual o por horario), o None
        self._quiet_manual = False  # hay un silencio manual que "Desactivar" puede quitar
        self._connected = False
        self._status_lines = ["Desconectado"]
        self._recent = []  # lista de dicts {etiqueta, rid}, más reciente primero
        self._rules = []  # reglas del servidor conectado, para el submenú "Silenciar"
        self._on_toggle_rule = None
        self._pending_meetings = []  # avisos disparados sin descartar: {id, titulo, enlace}
        self._upcoming_meetings = []  # próximas 1-3, solo informativas: {id, titulo, hora_texto}

        self._menu = Gtk.Menu()
        self._indicator = AyatanaAppIndicator3.Indicator.new(
            APP_ID, ICON_NAME, AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self._indicator.set_icon_theme_path(ICONS_DIR)
        self._indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_menu(self._menu)

        self.rebuild_menu()

    def set_connection_status(self, connected: bool, lines: list) -> None:
        """connected: hay algún servidor conectado (habilita las herramientas que
        necesitan uno). lines: ver build_status_lines."""
        if (connected, lines) == (self._connected, self._status_lines):
            return
        self._connected = connected
        self._status_lines = lines
        self.rebuild_menu()

    def set_quiet(self, text: str | None, manual: bool) -> None:
        """Estado de No molestar. Se llama en cada tick de reuniones (30 s): si nada ha
        cambiado no se reconstruye el menú."""
        if (text, manual) == (self._quiet_text, self._quiet_manual):
            return
        self._quiet_text = text
        self._quiet_manual = manual
        self.rebuild_menu()

    def add_recent_notification(self, etiqueta: str, rid: str) -> None:
        self._recent = add_to_recent(self._recent, etiqueta, rid)
        self.rebuild_menu()

    def remove_recent_notification(self, rid: str) -> None:
        self._recent = remove_from_recent(self._recent, rid)
        self.rebuild_menu()

    def _on_recent_notification_clicked(self, rid: str) -> None:
        # Al abrir el chat desde aquí, la damos por vista: se quita de la lista.
        self.remove_recent_notification(rid)
        self._on_open_chat(rid)

    def set_rules(self, rules: list, on_toggle_rule) -> None:
        """rules: reglas del servidor conectado. on_toggle_rule(rule_id, activa: bool)."""
        self._rules = rules
        self._on_toggle_rule = on_toggle_rule
        self.rebuild_menu()

    def add_pending_meeting(self, meeting_id: str, titulo: str, enlace: str | None) -> None:
        self._pending_meetings = add_pending_meeting(
            self._pending_meetings, {"id": meeting_id, "titulo": titulo, "enlace": enlace}
        )
        self.rebuild_menu()

    def _dismiss_pending_meeting(self, meeting_id: str) -> None:
        self._pending_meetings = remove_pending_meeting(self._pending_meetings, meeting_id)
        self.rebuild_menu()

    def set_upcoming_meetings(self, upcoming: list) -> None:
        """upcoming: 1-3 próximas reuniones, ya ordenadas: [{id, titulo, hora_texto}].
        Se llama en cada tick (30 s): si nada ha cambiado no se reconstruye el menú, que
        está exportado por D-Bus y es caro de rehacer."""
        if upcoming == self._upcoming_meetings:
            return
        self._upcoming_meetings = upcoming
        self.rebuild_menu()

    def rebuild_menu(self) -> None:
        for child in self._menu.get_children():
            self._menu.remove(child)

        for line in self._status_lines:
            status_item = Gtk.MenuItem(label=line)
            status_item.set_sensitive(False)
            self._menu.append(status_item)
        if self._quiet_text:
            quiet_status = Gtk.MenuItem(label=f"🔕 {self._quiet_text}")
            quiet_status.set_sensitive(False)
            self._menu.append(quiet_status)
        self._menu.append(Gtk.SeparatorMenuItem())

        if self._pending_meetings:
            for entry in self._pending_meetings:
                label_item = Gtk.MenuItem(label=f"🔔 {entry['titulo']}")
                label_item.set_sensitive(False)
                self._menu.append(label_item)
                if entry["enlace"]:
                    self._menu.append(
                        make_action_item(
                            "  Abrir enlace",
                            lambda enlace=entry["enlace"]: self._on_open_meeting_link(enlace),
                        )
                    )
                self._menu.append(
                    make_action_item(
                        "  Descartar",
                        lambda meeting_id=entry["id"]: self._dismiss_pending_meeting(meeting_id),
                    )
                )
            self._menu.append(Gtk.SeparatorMenuItem())

        if self._recent:
            for entry in self._recent:
                self._menu.append(
                    make_action_item(
                        entry["etiqueta"],
                        lambda rid=entry["rid"]: self._on_recent_notification_clicked(rid),
                    )
                )
        else:
            empty_item = Gtk.MenuItem(label="Sin notificaciones especiales todavía")
            empty_item.set_sensitive(False)
            self._menu.append(empty_item)
        self._menu.append(Gtk.SeparatorMenuItem())

        self._menu.append(make_action_item("Configuración...", lambda: self._on_open_settings()))
        self._menu.append(Gtk.SeparatorMenuItem())
        alerts_item = Gtk.MenuItem(label="Alertas")
        alerts_submenu = Gtk.Menu()
        for rule in self._rules:
            etiqueta = rule["etiqueta"] or rule.get("room_id") or "Mención"
            alerts_submenu.append(
                make_checkbox_item(
                    etiqueta,
                    rule["activa"],
                    lambda activa, rule_id=rule["id"]: self._on_toggle_rule(rule_id, activa),
                )
            )
        if self._rules:
            alerts_submenu.append(Gtk.SeparatorMenuItem())
        alerts_submenu.append(
            make_action_item("⚙ Configurar alertas...", lambda: self._on_open_settings("alertas"))
        )
        alerts_item.set_submenu(alerts_submenu)
        self._menu.append(alerts_item)

        meetings_item = Gtk.MenuItem(label="Reuniones")
        meetings_submenu = Gtk.Menu()
        for entry in self._upcoming_meetings:
            info_item = Gtk.MenuItem(label=f"{entry['hora_texto']} - {entry['titulo']}")
            info_item.set_sensitive(False)
            meetings_submenu.append(info_item)
        if not self._upcoming_meetings:
            empty_item = Gtk.MenuItem(label="Sin reuniones próximas")
            empty_item.set_sensitive(False)
            meetings_submenu.append(empty_item)
        meetings_submenu.append(Gtk.SeparatorMenuItem())
        meetings_submenu.append(
            make_action_item("⚙ Configurar reuniones...", lambda: self._on_open_settings("reuniones"))
        )
        meetings_item.set_submenu(meetings_submenu)
        self._menu.append(meetings_item)
        self._menu.append(Gtk.SeparatorMenuItem())

        tools_item = Gtk.MenuItem(label="Herramientas")
        tools_submenu = Gtk.Menu()
        mark_read_item = make_action_item("Marcar como leído...", self._on_mark_read)
        # Sin servidor conectado no hay suscripciones que marcar.
        mark_read_item.set_sensitive(self._connected)
        tools_submenu.append(mark_read_item)

        tools_submenu.append(
            make_action_item("Carpeta de sonidos", self._on_open_sounds_folder)
        )
        tools_item.set_submenu(tools_submenu)
        self._menu.append(tools_item)

        presence_item = Gtk.MenuItem(label="Estado")
        presence_submenu = Gtk.Menu()
        for status, etiqueta in PRESENCE_STATUSES.items():
            presence_submenu.append(
                make_action_item(etiqueta, lambda status=status: self._on_set_presence(status))
            )
        presence_item.set_submenu(presence_submenu)
        presence_item.set_sensitive(self._connected)
        self._menu.append(presence_item)

        quiet_item = Gtk.MenuItem(label="No molestar")
        quiet_submenu = Gtk.Menu()
        for duracion, etiqueta in (
            ("1h", "Durante 1 hora"),
            ("4h", "Durante 4 horas"),
            ("indefinido", "Hasta que lo desactive"),
        ):
            quiet_submenu.append(
                make_action_item(etiqueta, lambda duracion=duracion: self._on_set_quiet(duracion))
            )
        quiet_submenu.append(Gtk.SeparatorMenuItem())
        off_item = make_action_item("Desactivar", lambda: self._on_set_quiet("off"))
        off_item.set_sensitive(self._quiet_manual)
        quiet_submenu.append(off_item)
        quiet_item.set_submenu(quiet_submenu)
        self._menu.append(quiet_item)
        self._menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Salir")
        quit_item.connect("activate", lambda _w: Gtk.main_quit())
        self._menu.append(quit_item)

        self._menu.show_all()
