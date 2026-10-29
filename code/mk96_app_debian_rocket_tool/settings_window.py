"""Ventana Configuración: una sola ventana con tres pestañas (Servidores, Alertas y
Reuniones). Servidores es la que se abre por defecto. Cada pestaña es un panel
independiente (servers_window.py, alerts_window.py, meetings_window.py)."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from mk96_app_debian_rocket_tool.alerts_window import AlertsWindow
from mk96_app_debian_rocket_tool.meetings_window import MeetingsWindow
from mk96_app_debian_rocket_tool.servers_window import ServersWindow


# Tamaño de la ventana al mostrar cada pestaña (se aplica al cambiar de pestaña).
# Reuniones pide el del calendario, que se ajusta a la pantalla.
SERVERS_SIZE = (660, 560)
ALERTS_SIZE = (660, 780)


PAGES = ("servidores", "alertas", "reuniones")


class SettingsWindow(Gtk.Window):
    def __init__(self, config: dict, server_callbacks, alert_callbacks, on_meetings_changed):
        """alert_callbacks no incluye on_open_servers: lo aporta esta ventana (cambia de pestaña)."""
        super().__init__(title="Configuración - mk96-app-debian-rocket-tool")
        self._sizes = (SERVERS_SIZE, ALERTS_SIZE, MeetingsWindow.default_size())
        self.set_default_size(*self._sizes[0])

        self.servers = ServersWindow(config, server_callbacks)
        self.alerts = AlertsWindow(
            config, {**alert_callbacks, "on_open_servers": lambda: self._notebook.set_current_page(0)}
        )
        self.meetings = MeetingsWindow(config, on_meetings_changed)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        self._notebook = Gtk.Notebook()
        for panel, titulo in (
            (self.servers, "Servidores"),
            (self.alerts, "Alertas"),
            (self.meetings, "Reuniones"),
        ):
            self._notebook.append_page(panel, Gtk.Label(label=titulo))
        self._notebook.connect("switch-page", self._on_switch_page)
        root.pack_start(self._notebook, True, True, 0)

        # Puramente decorativo: cierra la ventana igual que la X, pero da la sensación
        # de "he terminado y confirmado" en vez de dejar la sensación de "no hice nada".
        accept_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        accept_box.set_border_width(8)
        accept_button = Gtk.Button(label="Aceptar")
        accept_button.connect("clicked", lambda _b: self.close())
        accept_box.pack_end(accept_button, False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)
        root.pack_start(accept_box, False, False, 0)

        self.show_all()
        self._notebook.set_current_page(0)

    def show_page(self, nombre: str) -> None:
        """nombre: "servidores", "alertas" o "reuniones"."""
        self._notebook.set_current_page(PAGES.index(nombre))

    def set_server_status(self, servidor_id: str, status: str, detail: str | None = None) -> None:
        self.servers.set_server_status(servidor_id, status, detail)
        self.alerts.set_server_status(servidor_id, status, detail)

    def set_config(self, config: dict) -> None:
        self.alerts.set_config(config)

    def set_known_rooms(self, servidor_id: str, rooms: list) -> None:
        self.alerts.set_known_rooms(servidor_id, rooms)

    def _on_switch_page(self, _notebook, _page, page_num: int) -> None:
        self.resize(*self._sizes[page_num])
