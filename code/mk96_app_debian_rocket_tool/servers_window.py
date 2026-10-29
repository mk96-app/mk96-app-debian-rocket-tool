"""Panel Servidores: lista de servidores Rocket.Chat guardados (con indicador de estado
de conexión) y, a la derecha, el formulario de conexión del servidor seleccionado
(nombre, URL, user id, token, intervalo, conectar/desconectar/eliminar). Debajo de la
lista está el arranque automático con la sesión.

Puede haber varios servidores conectados a la vez (cada uno con su polling). Las alertas
(reglas de sonido, No molestar) se configuran en alerts_window.py.
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from mk96_app_debian_rocket_tool import autostart, secret_store
from mk96_app_debian_rocket_tool.async_utils import run_in_thread
from mk96_app_debian_rocket_tool.config import normalize_server
from mk96_app_debian_rocket_tool.gtk_helpers import show_error_dialog
from mk96_app_debian_rocket_tool.rest_client import (
    RestApiError,
    check_connection,
    describe_connection_error,
    validate_server_url,
)

STATUS_COLORS = {
    "conectado": "#2ec27e",
    "desconectado": "#9a9996",
    "error": "#e01b24",
}


def probe_ok_text(username: str) -> str:
    return f"Conexión correcta: @{username}"


def server_status_text(status: str | None, detail: str | None) -> tuple:
    """(texto, color) del estado de conexión de un servidor: color True/False/"gris"/None =
    verde/rojo/gris/neutro. `detail` es el usuario si está conectado, o el error si falló."""
    if status == "conectado":
        if detail:
            return f"Conexión abierta:\n@{detail}", True
        return "Conectando...", None
    if status == "error":
        return detail or "Sin conexión.", False
    if status == "desconectado":
        return "Conexión cerrada", "gris"
    return "", None


def delete_confirmation_text(nombre: str, n_reglas: int) -> tuple:
    """(título, cuerpo) del diálogo de confirmación al eliminar un servidor."""
    if n_reglas == 0:
        reglas = ""
    elif n_reglas == 1:
        reglas = "su regla de alerta y "
    else:
        reglas = f"sus {n_reglas} reglas de alerta y "
    return (
        f"¿Eliminar el servidor «{nombre}»?",
        f"Se borrarán {reglas}las credenciales guardadas. No se puede deshacer.",
    )


class ServersWindow(Gtk.Box):
    def __init__(self, config: dict, callbacks):
        """callbacks: dict con on_config_changed(config), on_connect(servidor_id),
        on_disconnect(servidor_id), on_delete_server(servidor_id)."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._config = config
        self._callbacks = callbacks
        self._selected_server_id = None
        self._server_status = {}  # servidor_id -> "conectado"|"desconectado"|"error"
        self._server_detail = {}  # servidor_id -> usuario (conectado) o mensaje de error
        self._status_label = None  # estado real de la conexión (solo en servidores guardados)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pack_start(root, True, True, 0)

        # Rejilla compartida por la lista (izquierda) y el formulario (derecha): los
        # separadores de ambos lados y la fila "Inicio automático" / "Probar conexión"
        # caen siempre en la misma fila, alineados, sea cual sea la altura del formulario.
        self._grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self._grid.set_border_width(12)
        root.pack_start(self._grid, True, True, 0)
        self._build_server_list_panel()
        self._form_widgets = []

        if config["servidores"]:
            self._selected_server_id = config["servidores"][0]["id"]
        self._refresh_server_list()
        self.show_all()

    # -- Estado de conexión, refrescado desde app.py -----------------------------

    def set_server_status(self, servidor_id: str, status: str, detail: str | None = None) -> None:
        self._server_status[servidor_id] = status
        self._server_detail[servidor_id] = detail
        self._refresh_server_list()

    # -- Lista lateral de servidores ------------------------------------------------

    def _build_server_list_panel(self) -> None:
        # Fila 0 (izquierda): lista de servidores con "Añadir servidor" bajo ella.
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._server_list = Gtk.ListBox()
        self._server_list.connect("row-selected", self._on_server_row_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_size_request(200, -1)
        scroller.set_min_content_height(120)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self._server_list)
        left.pack_start(scroller, True, True, 0)
        add_button = Gtk.Button(label="+ Añadir servidor")
        add_button.connect("clicked", lambda _b: self._select_server(None))
        left.pack_start(add_button, False, False, 0)
        self._grid.attach(left, 0, 0, 1, 1)

        # Fila 1: un separador por columna, a la misma altura.
        self._grid.attach(Gtk.Separator(), 0, 1, 1, 1)
        self._grid.attach(Gtk.Separator(), 1, 1, 1, 1)

        # Fila 2 (izquierda): inicio automático, a la altura de "Probar conexión".
        autostart_check = Gtk.CheckButton(label="Inicio automático")
        autostart_check.set_valign(Gtk.Align.CENTER)
        autostart_check.set_active(autostart.is_enabled())
        autostart_check.connect("toggled", self._on_autostart_toggled)
        autostart_check.set_tooltip_text(
            "Arranca la aplicación sola al iniciar sesión en el escritorio, para que el "
            "icono de la bandeja esté siempre. No cambia qué servidores se conectan."
        )
        self._grid.attach(autostart_check, 0, 2, 1, 1)

    def _on_autostart_toggled(self, check) -> None:
        try:
            autostart.set_enabled(check.get_active())
        except OSError as exc:
            show_error_dialog(self, "No se pudo cambiar el arranque automático", str(exc))
            check.handler_block_by_func(self._on_autostart_toggled)
            check.set_active(not check.get_active())
            check.handler_unblock_by_func(self._on_autostart_toggled)

    def _refresh_server_list(self) -> None:
        for child in self._server_list.get_children():
            self._server_list.remove(child)

        for server in self._config["servidores"]:
            row = Gtk.ListBoxRow()
            row.servidor_id = server["id"]
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            content.set_border_width(4)

            status = self._server_status.get(server["id"], "desconectado")
            dot = Gtk.Label(label="●")
            color = STATUS_COLORS[status]
            dot.set_markup(f'<span foreground="{color}">●</span>')
            content.pack_start(dot, False, False, 0)
            content.pack_start(Gtk.Label(label=server["nombre"], xalign=0), True, True, 0)

            row.add(content)
            self._server_list.add(row)

        self._server_list.show_all()

        if self._selected_server_id is not None:
            for row in self._server_list.get_children():
                if row.servidor_id == self._selected_server_id:
                    self._server_list.select_row(row)

    def _on_server_row_selected(self, _listbox, row) -> None:
        if row is not None:
            self._select_server(row.servidor_id)

    # -- Formulario de conexión -----------------------------------------------------

    def _select_server(self, servidor_id: str | None) -> None:
        self._selected_server_id = servidor_id
        for widget in self._form_widgets:
            self._grid.remove(widget)

        fields, test_row, action_row = self._build_connection_section(servidor_id)
        self._form_widgets = [fields, test_row, action_row]
        self._grid.attach(fields, 1, 0, 1, 1)
        # Fila 1 = separador. Debajo, de arriba abajo: prueba y guardar/eliminar.
        self._grid.attach(test_row, 1, 2, 1, 1)
        self._grid.attach(action_row, 1, 3, 1, 1)
        self._grid.show_all()

    def _build_connection_section(self, servidor_id: str | None) -> tuple:
        """Devuelve (campos, fila de prueba, fila de acciones) para la columna derecha de la
        rejilla; la fila 1 es el separador. La fila de estado con Conectar/Desconectar va
        arriba del todo, dentro de los campos."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_hexpand(True)
        # Conectar/Desconectar, Probar y Guardar con el mismo ancho: la columna de botones
        # queda alineada y los textos de estado empiezan todos en el mismo punto.
        self._button_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        existing_server = next(
            (s for s in self._config["servidores"] if s["id"] == servidor_id), None
        )
        credentials = None
        if existing_server is not None:
            try:
                credentials = secret_store.load_server_credentials(servidor_id)
            except secret_store.SecretStoreUnavailable as exc:
                show_error_dialog(self, "No se pudo leer la credencial guardada", str(exc))

        self._status_label = None
        if existing_server is not None:
            box.pack_start(self._build_status_row(servidor_id), False, False, 6)

        box.pack_start(Gtk.Label(label="Nombre del servidor", xalign=0), False, False, 0)
        self._name_entry = Gtk.Entry()
        self._name_entry.set_text(existing_server["nombre"] if existing_server else "")
        self._name_entry.set_placeholder_text("Trabajo, Personal...")
        box.pack_start(self._name_entry, False, False, 0)

        box.pack_start(Gtk.Label(label="URL del servidor", xalign=0), False, False, 0)
        self._server_entry = Gtk.Entry()
        self._server_entry.set_text(credentials["server_url"] if credentials else "")
        self._server_entry.set_placeholder_text("https://chat.miempresa.com")
        box.pack_start(self._server_entry, False, False, 0)

        box.pack_start(Gtk.Label(label="User Id", xalign=0), False, False, 0)
        self._user_id_entry = Gtk.Entry()
        self._user_id_entry.set_text(credentials["user_id"] if credentials else "")
        self._user_id_entry.set_placeholder_text("Mi cuenta > Personal Access Tokens")
        box.pack_start(self._user_id_entry, False, False, 0)

        box.pack_start(Gtk.Label(label="Personal Access Token", xalign=0), False, False, 0)
        self._token_entry = Gtk.Entry()
        self._token_entry.set_visibility(False)
        self._token_entry.set_text(credentials["token"] if credentials else "")
        self._token_entry.set_placeholder_text("Personal Access Token")
        self._token_entry.set_icon_from_icon_name(
            Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic"
        )
        self._token_entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Mostrar token")
        self._token_entry.connect("icon-press", self._on_token_icon_pressed)
        box.pack_start(self._token_entry, False, False, 0)

        box.pack_start(Gtk.Label(label="Comprobar mensajes nuevos cada:", xalign=0), False, False, 0)
        self._poll_interval_combo = Gtk.ComboBoxText()
        self._poll_interval_combo.append("15", "15 segundos")
        self._poll_interval_combo.append("30", "30 segundos")
        self._poll_interval_combo.append("60", "60 segundos")
        self._poll_interval_combo.set_active_id(
            str(existing_server.get("poll_interval_s", 30)) if existing_server else "30"
        )
        box.pack_start(self._poll_interval_combo, False, False, 0)

        # Fila de prueba: botón (Probar conexión) a la izquierda y su resultado a la
        # derecha, igual que la fila de estado (Conectar/Desconectar + texto).
        test_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._test_button = Gtk.Button(label="Probar conexión")
        self._test_button.set_tooltip_text(
            "Comprueba la URL, el User Id y el token escritos aquí, sin guardar nada."
        )
        self._test_button.connect("clicked", lambda _b: self._test_connection())
        self._button_group.add_widget(self._test_button)
        test_row.pack_start(self._test_button, False, False, 0)

        self._test_result = Gtk.Label(xalign=0)
        self._test_result.set_line_wrap(True)
        # Sin un ancho mínimo, GTK mide la altura de una etiqueta que se parte como si
        # tuviera una letra por línea y estira la ventana con un hueco de más.
        self._test_result.set_width_chars(18)
        self._test_result.set_max_width_chars(30)
        self._test_result.set_selectable(True)
        test_row.pack_start(self._test_result, True, True, 0)
        # Un resultado viejo (p.ej. un ✔) no debe sobrevivir a editar lo probado.
        for entry in (self._server_entry, self._user_id_entry, self._token_entry):
            entry.connect("changed", lambda _e: self._set_test_result(""))

        # Guardar (acción principal) a la izquierda y Eliminar a la derecha, aparte.
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        if existing_server is not None:
            delete_button = Gtk.Button(label="Eliminar servidor")
            delete_button.get_style_context().add_class("destructive-action")
            delete_button.connect("clicked", lambda _b: self._confirm_delete(servidor_id))
            action_row.pack_end(delete_button, False, False, 0)

        save_button = Gtk.Button(label="Guardar")
        save_button.get_style_context().add_class("suggested-action")
        save_button.connect("clicked", lambda _b: self._save_server(servidor_id))
        self._button_group.add_widget(save_button)
        action_row.pack_start(save_button, False, False, 0)
        return box, test_row, action_row

    def _build_status_row(self, servidor_id: str) -> Gtk.Box:
        """Botón Conectar/Desconectar a la izquierda y, a su derecha, el estado real de la
        conexión (verde/rojo/gris)."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._status_label = Gtk.Label(xalign=0)
        self._status_label.set_line_wrap(True)
        self._status_label.set_width_chars(18)
        self._status_label.set_max_width_chars(30)
        self._status_label.set_selectable(True)
        self._render_status_label(servidor_id)

        if self._server_status.get(servidor_id) == "conectado":
            toggle = Gtk.Button(label="Desconectar")
            toggle.connect("clicked", lambda _b: self._callbacks["on_disconnect"](servidor_id))
        else:
            toggle = Gtk.Button(label="Conectar")
            toggle.connect("clicked", lambda _b: self._callbacks["on_connect"](servidor_id))
        self._button_group.add_widget(toggle)
        row.pack_start(toggle, False, False, 0)
        row.pack_start(self._status_label, True, True, 0)
        return row

    def _on_token_icon_pressed(self, entry, icon_pos, _event) -> None:
        if icon_pos != Gtk.EntryIconPosition.SECONDARY:
            return
        show = not entry.get_visibility()
        entry.set_visibility(show)
        entry.set_icon_from_icon_name(
            Gtk.EntryIconPosition.SECONDARY,
            "view-conceal-symbolic" if show else "view-reveal-symbolic",
        )
        entry.set_icon_tooltip_text(
            Gtk.EntryIconPosition.SECONDARY, "Ocultar token" if show else "Mostrar token"
        )

    def _set_colored(self, label: Gtk.Label, text: str, ok: bool | None) -> None:
        color = {True: "#2ec27e", False: "#e01b24", "gris": "#9a9996", None: None}[ok]
        escaped = GLib.markup_escape_text(text)
        label.set_markup(f'<span foreground="{color}">{escaped}</span>' if color else escaped)

    def _set_test_result(self, text: str, ok: bool | None = None) -> None:
        """Resultado de una prueba manual: se muestra hasta que se edite el formulario."""
        self._set_colored(self._test_result, text, ok)

    def _render_status_label(self, servidor_id: str) -> None:
        text, ok = server_status_text(
            self._server_status.get(servidor_id, "desconectado"),
            self._server_detail.get(servidor_id),
        )
        self._set_colored(self._status_label, text, ok)

    def _test_connection(self) -> None:
        server_url = self._server_entry.get_text().strip()
        user_id = self._user_id_entry.get_text().strip()
        token = self._token_entry.get_text().strip()

        faltan = [
            nombre
            for nombre, valor in (("la URL", server_url), ("el User Id", user_id), ("el token", token))
            if not valor
        ]
        if faltan:
            self._set_test_result(f"Falta rellenar {', '.join(faltan)}.", ok=False)
            return
        url_error = validate_server_url(server_url)
        if url_error:
            self._set_test_result(url_error, ok=False)
            return

        self._test_button.set_sensitive(False)
        self._set_test_result("Probando...")
        # El resultado llega cuando el formulario puede haberse reconstruido (otro servidor
        # elegido): solo se pinta si el botón sigue siendo el de esta prueba.
        button = self._test_button

        def done(username, error):
            if self._test_button is not button:
                return
            button.set_sensitive(True)
            if isinstance(error, RestApiError):
                self._set_test_result(describe_connection_error(error), ok=False)
            elif error is not None:
                self._set_test_result(f"Error inesperado: {error}", ok=False)
            else:
                self._set_test_result(probe_ok_text(username), ok=True)

        run_in_thread(lambda: check_connection(server_url, user_id, token), done)

    def _save_server(self, servidor_id: str | None) -> None:
        nombre = self._name_entry.get_text().strip()
        server_url = self._server_entry.get_text().strip()
        user_id = self._user_id_entry.get_text().strip()
        token = self._token_entry.get_text().strip()
        if not (nombre and server_url and user_id and token):
            return

        poll_interval_s = int(self._poll_interval_combo.get_active_id())

        is_new = servidor_id is None
        if is_new:
            server = normalize_server(
                {"nombre": nombre, "activo": False, "poll_interval_s": poll_interval_s}
            )
            servidor_id = server["id"]
            self._config["servidores"].append(server)
        else:
            for server in self._config["servidores"]:
                if server["id"] == servidor_id:
                    server["nombre"] = nombre
                    server["poll_interval_s"] = poll_interval_s

        try:
            secret_store.save_server_credentials(servidor_id, server_url, user_id, token)
        except secret_store.SecretStoreUnavailable as exc:
            show_error_dialog(self, "No se pudo guardar la credencial", str(exc))
            return

        self._callbacks["on_config_changed"](self._config)
        self._selected_server_id = servidor_id
        self._refresh_server_list()
        self._select_server(servidor_id)

    def _confirm_delete(self, servidor_id: str) -> None:
        nombre = next(
            (s["nombre"] for s in self._config["servidores"] if s["id"] == servidor_id), servidor_id
        )
        n_reglas = sum(1 for r in self._config["reglas"] if r["servidor_id"] == servidor_id)
        titulo, cuerpo = delete_confirmation_text(nombre, n_reglas)
        dialog = Gtk.MessageDialog(
            transient_for=self.get_toplevel(),
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            text=titulo,
        )
        dialog.format_secondary_text(cuerpo)
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        delete_button = dialog.add_button("Eliminar", Gtk.ResponseType.OK)
        delete_button.get_style_context().add_class("destructive-action")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self._delete_server(servidor_id)

    def _delete_server(self, servidor_id: str) -> None:
        self._callbacks["on_disconnect"](servidor_id)
        self._callbacks["on_delete_server"](servidor_id)
        self._config["servidores"] = [
            s for s in self._config["servidores"] if s["id"] != servidor_id
        ]
        self._config["reglas"] = [
            r for r in self._config["reglas"] if r["servidor_id"] != servidor_id
        ]
        self._server_status.pop(servidor_id, None)
        self._callbacks["on_config_changed"](self._config)
        self._selected_server_id = None
        self._refresh_server_list()
        self._select_server(None)
