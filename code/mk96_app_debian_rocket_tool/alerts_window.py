"""Panel Alertas: lista de alertas del servidor elegido en el selector superior y el
horario silencioso de No molestar. Añadir o editar una alerta se hace en alert_dialog.py.

La conexión (alta, credenciales, conectar/desconectar) se gestiona en servers_window.py;
aquí solo se ve el estado de cada servidor, y buscar salas nuevas exige que esté
conectado.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

from mk96_app_debian_rocket_tool import sound_manager
from mk96_app_debian_rocket_tool.alert_dialog import AlertDialog
from mk96_app_debian_rocket_tool.config import normalize_rule
from mk96_app_debian_rocket_tool.gtk_helpers import show_error_dialog
from mk96_app_debian_rocket_tool.sound_manager import sonido_display_name

# Tarjeta de la mención global: tinte azul translúcido, válido en tema claro y oscuro.
MENTION_CARD_CSS = Gtk.CssProvider()
MENTION_CARD_CSS.load_from_data(
    b".mention-card { background-color: alpha(#3584e4, 0.18);"
    b" border: 1px solid alpha(#3584e4, 0.55); border-radius: 6px; }"
)


class AlertsWindow(Gtk.Box):
    def __init__(self, config: dict, callbacks):
        """callbacks: dict con on_config_changed(config) y on_open_servers()."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._config = config
        self._callbacks = callbacks
        self._known_rooms_by_server = {}  # servidor_id -> [{room_id, nombre, tipo}]
        self._selected_server_id = None
        self._server_status = {}  # servidor_id -> "conectado"|"desconectado"|"error"

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pack_start(root, True, True, 0)

        selector_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        selector_row.set_border_width(8)
        selector_row.pack_start(Gtk.Label(label="Servidor:", xalign=0), False, False, 0)
        self._server_combo = Gtk.ComboBoxText()
        self._server_combo.set_hexpand(True)
        self._server_combo_handler = self._server_combo.connect(
            "changed", self._on_server_combo_changed
        )
        selector_row.pack_start(self._server_combo, True, True, 0)
        root.pack_start(selector_row, False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        # Solo la lista de alertas se desplaza: "No molestar" va fija debajo para que no
        # desaparezca al encoger la ventana a mano.
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(12)
        self._server_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.pack_start(self._server_content, True, True, 0)
        content.pack_start(self._build_quiet_section(), False, False, 0)
        root.pack_start(content, True, True, 0)

        self._refresh_server_combo()
        self.show_all()

    # -- Estado refrescado desde app.py ----------------------------------------------

    def set_server_status(self, servidor_id: str, status: str, detail: str | None = None) -> None:
        was_connected = self._server_status.get(servidor_id) == "conectado"
        self._server_status[servidor_id] = status
        self._refresh_server_combo()
        # Solo se reconstruye el formulario si cambia lo que condiciona (poder buscar
        # salas): hacerlo en cada cambio tiraría lo que se esté escribiendo.
        if servidor_id == self._selected_server_id and was_connected != (status == "conectado"):
            self._select_server(servidor_id)

    def set_known_rooms(self, servidor_id: str, rooms: list) -> None:
        self._known_rooms_by_server[servidor_id] = rooms

    @property
    def _known_rooms(self) -> list:
        """Salas del servidor seleccionado (cada servidor conectado trae las suyas)."""
        return self._known_rooms_by_server.get(self._selected_server_id, [])

    def set_config(self, config: dict) -> None:
        """Sincroniza cambios hechos fuera de esta ventana (silenciar una regla desde la
        bandeja, añadir/borrar servidores) sin perder la selección actual."""
        self._config = config
        previous = self._selected_server_id
        self._refresh_server_combo()
        if previous is not None and previous == self._selected_server_id:
            self._refresh_rules_list(previous)

    # -- Selector de servidor --------------------------------------------------------

    def _server_label(self, server: dict) -> str:
        status = self._server_status.get(server["id"], "desconectado")
        return server["nombre"] if status == "conectado" else f"{server['nombre']} (desconectado)"

    def _refresh_server_combo(self) -> None:
        self._server_combo.handler_block(self._server_combo_handler)
        self._server_combo.remove_all()
        for server in self._config["servidores"]:
            self._server_combo.append(server["id"], self._server_label(server))
        ids = [s["id"] for s in self._config["servidores"]]
        keep = self._selected_server_id if self._selected_server_id in ids else None
        if keep is None and ids:
            keep = ids[0]
        self._server_combo.set_active_id(keep)
        self._server_combo.handler_unblock(self._server_combo_handler)

        if keep != self._selected_server_id or (keep is None and not self._server_content.get_children()):
            self._select_server(keep)

    def _on_server_combo_changed(self, combo) -> None:
        servidor_id = combo.get_active_id()
        if servidor_id != self._selected_server_id:
            self._select_server(servidor_id)

    def _select_server(self, servidor_id: str | None) -> None:
        self._selected_server_id = servidor_id
        for child in self._server_content.get_children():
            self._server_content.remove(child)

        if servidor_id is None:
            self._server_content.pack_start(self._build_no_servers_hint(), False, False, 0)
        else:
            self._server_content.pack_start(self._build_rules_section(servidor_id), True, True, 0)
        self._server_content.show_all()
        if servidor_id is not None:
            self._refresh_add_button(servidor_id)

    def _build_no_servers_hint(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hint = Gtk.Label(
            label="Todavía no hay ningún servidor. Añade uno para poder crear alertas.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        open_button = Gtk.Button(label="Abrir Servidores...")
        open_button.set_halign(Gtk.Align.START)
        open_button.connect("clicked", lambda _b: self._callbacks["on_open_servers"]())
        box.pack_start(open_button, False, False, 0)
        return box

    # -- Horario silencioso (No molestar) --------------------------------------------

    def _build_quiet_section(self) -> Gtk.Frame:
        quiet = self._config["no_molestar"]
        frame = Gtk.Frame(label="No molestar")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(10)
        frame.add(box)

        schedule_check = Gtk.CheckButton(label="Horario silencioso")
        schedule_check.set_tooltip_text(
            "Sin sonido ni notificación de chats dentro de este horario (los chats siguen "
            "apareciendo en la bandeja). Los recordatorios de reuniones no se silencian. "
            "Para silenciar a mano, usa «No molestar» en el menú de la bandeja."
        )
        schedule_check.set_active(quiet["horario_activo"])
        box.pack_start(schedule_check, False, False, 0)

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        spins = {}
        for key, etiqueta in (("desde", "Desde"), ("hasta", "Hasta")):
            hours_text, minutes_text = quiet[key].split(":")
            time_box.pack_start(Gtk.Label(label=etiqueta, xalign=0), False, False, 0)
            hours_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
            hours_spin.set_value(int(hours_text))
            minutes_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
            minutes_spin.set_value(int(minutes_text))
            time_box.pack_start(hours_spin, False, False, 0)
            time_box.pack_start(Gtk.Label(label=":"), False, False, 0)
            time_box.pack_start(minutes_spin, False, False, 0)
            spins[key] = (hours_spin, minutes_spin)
        box.pack_start(time_box, False, False, 0)

        def save_quiet(_widget=None):
            quiet["horario_activo"] = schedule_check.get_active()
            for key, (hours_spin, minutes_spin) in spins.items():
                quiet[key] = f"{hours_spin.get_value_as_int():02d}:{minutes_spin.get_value_as_int():02d}"
            time_box.set_sensitive(quiet["horario_activo"])
            self._callbacks["on_config_changed"](self._config)

        time_box.set_sensitive(quiet["horario_activo"])
        schedule_check.connect("toggled", save_quiet)
        for hours_spin, minutes_spin in spins.values():
            hours_spin.connect("value-changed", save_quiet)
            minutes_spin.connect("value-changed", save_quiet)

        return frame


    # -- Lista de alertas ------------------------------------------------------------

    def _build_rules_section(self, servidor_id: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        box.pack_start(Gtk.Label(label="Mención global", xalign=0), False, False, 0)
        self._mention_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._mention_card.get_style_context().add_class("mention-card")
        self._mention_card.get_style_context().add_provider(
            MENTION_CARD_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        box.pack_start(self._mention_card, False, False, 0)

        box.pack_start(Gtk.Label(label="Alertas de sala", xalign=0), False, False, 0)
        self._rules_list = Gtk.ListBox()
        self._rules_list.set_selection_mode(Gtk.SelectionMode.NONE)
        placeholder = Gtk.Label(label="Este servidor todavía no tiene alertas de sala.")
        placeholder.set_margin_top(24)
        placeholder.set_margin_bottom(24)
        placeholder.show()
        self._rules_list.set_placeholder(placeholder)
        self._rules_list.connect("row-activated", self._on_rule_row_activated)
        rules_scroller = Gtk.ScrolledWindow()
        rules_scroller.set_shadow_type(Gtk.ShadowType.IN)
        rules_scroller.set_min_content_height(100)
        rules_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        rules_scroller.add(self._rules_list)
        box.pack_start(rules_scroller, True, True, 0)

        add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._add_button = Gtk.Button(label="+ Añadir alerta")
        self._add_button.connect("clicked", lambda _b: self._open_alert_dialog(servidor_id))
        add_row.pack_start(self._add_button, False, False, 0)
        self._add_hint = Gtk.Label(
            label="Conecta este servidor para poder crear alertas de sala.", xalign=0
        )
        add_row.pack_start(self._add_hint, False, False, 0)
        box.pack_start(add_row, False, False, 0)

        self._refresh_rules_list(servidor_id)
        return box

    def _build_rule_content(self, servidor_id: str, rule: dict) -> Gtk.Box:
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_border_width(8)

        active_check = Gtk.CheckButton()
        active_check.set_active(rule["activa"])
        active_check.set_tooltip_text("Silenciar/activar esta alerta")
        active_check.connect(
            "toggled",
            lambda widget, rule_id=rule["id"]: self._toggle_rule_active(
                servidor_id, rule_id, widget.get_active()
            ),
        )
        content.pack_start(active_check, False, False, 0)

        label = Gtk.Label(xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        texto = GLib.markup_escape_text(self._describe_rule(rule))
        if not rule["activa"]:
            label.set_markup(f'<span foreground="#9a9996">{texto} (silenciada)</span>')
        else:
            label.set_markup(texto)
        content.pack_start(label, True, True, 0)

        preview_button = Gtk.Button(label="▶")
        preview_button.set_tooltip_text("Probar este sonido")
        preview_button.connect(
            "clicked", lambda _b, sonido_id=rule["sonido_id"]: self._preview_sonido_id(sonido_id)
        )
        content.pack_start(preview_button, False, False, 0)

        edit_button = Gtk.Button(label="Editar")
        edit_button.connect(
            "clicked", lambda _b: self._open_alert_dialog(servidor_id, rule)
        )
        content.pack_start(edit_button, False, False, 0)

        remove_button = Gtk.Button(label="Quitar")
        remove_button.get_style_context().add_class("destructive-action")
        remove_button.connect(
            "clicked", lambda _b, rule_id=rule["id"]: self._remove_rule(servidor_id, rule_id)
        )
        content.pack_start(remove_button, False, False, 0)
        return content

    def _refresh_rules_list(self, servidor_id: str) -> None:
        for child in self._rules_list.get_children():
            self._rules_list.remove(child)
        for child in self._mention_card.get_children():
            self._mention_card.remove(child)

        mention = next(
            (r for r in self._config["reglas"]
             if r["servidor_id"] == servidor_id and r["tipo"] == "mencion"),
            None,
        )
        if mention is not None:
            self._mention_card.pack_start(self._build_rule_content(servidor_id, mention), False, False, 0)
        else:
            empty = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            empty.set_border_width(8)
            empty.pack_start(Gtk.Label(label="Sin configurar", xalign=0), True, True, 0)
            configure_button = Gtk.Button(label="Configurar")
            configure_button.connect(
                "clicked", lambda _b: self._open_alert_dialog(servidor_id, None, "mencion")
            )
            empty.pack_start(configure_button, False, False, 0)
            self._mention_card.pack_start(empty, False, False, 0)
        self._mention_card.show_all()

        for rule in self._config["reglas"]:
            if rule["servidor_id"] != servidor_id or rule["tipo"] == "mencion":
                continue
            row = Gtk.ListBoxRow()
            row.rule = rule
            row.add(self._build_rule_content(servidor_id, rule))
            self._rules_list.add(row)
        self._rules_list.show_all()
        self._refresh_add_button(servidor_id)

    def _refresh_add_button(self, servidor_id: str) -> None:
        """Las alertas de sala necesitan las salas del servidor, así que exigen conexión."""
        connected = self._server_status.get(servidor_id) == "conectado"
        self._add_button.set_sensitive(connected)
        self._add_hint.set_visible(not connected)

    def _on_rule_row_activated(self, _listbox, row) -> None:
        self._open_alert_dialog(self._selected_server_id, row.rule)

    def _describe_rule(self, rule: dict) -> str:
        sonido = sonido_display_name(rule["sonido_id"])
        if rule["tipo"] == "mencion":
            extra = " (+ @all/@here)" if rule.get("mencion_todos") else ""
            return f"Mención global{extra} -> {sonido}"
        nombre = self._config["salas_cache"].get(rule["room_id"], rule["room_id"])
        return f"{nombre} -> {sonido}"

    def _toggle_rule_active(self, servidor_id: str, rule_id: str, activa: bool) -> None:
        for rule in self._config["reglas"]:
            if rule["id"] == rule_id:
                rule["activa"] = activa
        self._callbacks["on_config_changed"](self._config)
        self._refresh_rules_list(servidor_id)

    def _preview_sonido_id(self, sonido_id: str) -> None:
        try:
            sound_manager.play_sound(sonido_id)
        except sound_manager.SoundPlaybackError as exc:
            show_error_dialog(self, "No se pudo reproducir el sonido", str(exc))

    # -- Añadir / editar -------------------------------------------------------------

    def _open_alert_dialog(self, servidor_id: str, rule: dict | None = None, tipo: str = "sala") -> None:
        dialog = AlertDialog(
            self.get_toplevel(), self._config, servidor_id, self._known_rooms, rule=rule, tipo=tipo
        )
        data = dialog.run_and_collect()
        if data is not None:
            self._apply_alert(servidor_id, rule, data)

    def _apply_alert(self, servidor_id: str, rule: dict | None, data: dict) -> None:
        repeat = {
            "repeticion_modo": data["repeticion_modo"],
            "repeticion_n": data["repeticion_n"],
            "repeticion_cada_polls": data["repeticion_cada_polls"],
        }
        if rule is not None:
            rule["sonido_id"] = data["sonido_id"]
            rule.update(repeat)
            if rule["tipo"] == "mencion":
                rule["mencion_todos"] = data["mencion_todos"]
        elif data["tipo"] == "mencion":
            self._config["reglas"].append(
                normalize_rule(
                    {
                        "servidor_id": servidor_id,
                        "tipo": "mencion",
                        "sonido_id": data["sonido_id"],
                        "etiqueta": "Mención",
                        "mencion_todos": data["mencion_todos"],
                        **repeat,
                    }
                )
            )
        else:
            room = next((r for r in self._known_rooms if r["room_id"] == data["room_id"]), None)
            self._config["reglas"].append(
                normalize_rule(
                    {
                        "servidor_id": servidor_id,
                        "tipo": "sala",
                        "room_id": data["room_id"],
                        "room_type": room["tipo"] if room else None,
                        "sonido_id": data["sonido_id"],
                        "etiqueta": room["nombre"] if room else data["room_id"],
                        **repeat,
                    }
                )
            )
            if room:
                self._config["salas_cache"][data["room_id"]] = room["nombre"]
        self._callbacks["on_config_changed"](self._config)
        self._refresh_rules_list(servidor_id)

    def _remove_rule(self, servidor_id: str, rule_id: str) -> None:
        self._config["reglas"] = [r for r in self._config["reglas"] if r["id"] != rule_id]
        self._callbacks["on_config_changed"](self._config)
        self._refresh_rules_list(servidor_id)
