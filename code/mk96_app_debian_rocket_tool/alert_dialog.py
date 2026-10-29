"""Diálogo para añadir o editar una alerta (regla de sala o regla de mención global).

Lo abre alerts_window.py; aquí solo se recogen y validan los datos -guardarlos en la
configuración lo hace la ventana que lo abre.
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from mk96_app_debian_rocket_tool import sound_manager
from mk96_app_debian_rocket_tool.config import find_room_rule
from mk96_app_debian_rocket_tool.gtk_helpers import open_sound_picker, show_error_dialog
from mk96_app_debian_rocket_tool.sound_manager import sonido_display_name

ROOM_GROUP_ORDER = ("c", "p", "d")
ROOM_GROUP_LABELS = {"c": "Canales", "p": "Privados", "d": "Mensajes directos"}


def validate_alert(tipo: str, room, sonido_id, duplicate_room: bool):
    """Devuelve (titulo, mensaje) del primer problema que impide guardar, o None."""
    if tipo == "sala":
        if room is None:
            return (
                "Falta elegir una sala",
                "Usa el buscador o 'Ver todas...' y selecciona una sala/persona de la "
                "lista -escribir el nombre a mano no basta.",
            )
        if duplicate_room:
            return (
                "Ya existe una alerta para esta sala",
                "Edítala desde la lista de alertas en vez de crear otra.",
            )
    if not sonido_id:
        return "Falta el sonido", "Usa 'Elegir sonido...' antes de guardar la alerta."
    return None


def repeat_values(modo: str, n: int, cada: int):
    """(repeticion_modo, repeticion_n, repeticion_cada_polls) tal y como se guardan."""
    return modo, (n if modo == "n_veces" else None), (cada if modo != "una_vez" else 1)


class AlertDialog(Gtk.Dialog):
    def __init__(self, parent, config: dict, servidor_id: str, known_rooms: list,
                 rule: dict | None = None, tipo: str = "sala"):
        """rule=None crea una alerta nueva del `tipo` indicado; con una regla existente
        la edita (el tipo y la sala quedan fijos)."""
        editing = rule is not None
        super().__init__(
            title="Editar alerta" if editing else (
                "Nueva alerta" if tipo == "sala" else "Configurar mención global"
            ),
            transient_for=parent,
            modal=True,
        )
        self.set_default_size(480, 1)

        self._config = config
        self._servidor_id = servidor_id
        self._known_rooms = known_rooms
        self._rule = rule
        self._tipo = rule["tipo"] if editing else tipo
        self._selected_room = None
        self._sonido_id = rule["sonido_id"] if editing else None
        self._suppress_room_popover = False

        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        save_button = self.add_button("Guardar", Gtk.ResponseType.OK)
        save_button.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_border_width(14)
        self.get_content_area().pack_start(grid, True, True, 0)

        row = 0
        # -- Sala (solo tipo "sala") --
        self._room_widgets = []
        room_label = Gtk.Label(label="Sala o persona:", xalign=0)
        grid.attach(room_label, 0, row, 1, 1)
        self._room_widgets.append(room_label)
        if editing and rule["tipo"] == "sala":
            nombre = config["salas_cache"].get(rule["room_id"], rule["room_id"])
            fixed = Gtk.Label(label=nombre, xalign=0)
            fixed.set_hexpand(True)
            grid.attach(fixed, 1, row, 2, 1)
            self._room_widgets.append(fixed)
            self._room_search_entry = None
        else:
            self._room_search_entry = Gtk.Entry()
            self._room_search_entry.set_placeholder_text("Escribe para buscar...")
            self._room_search_entry.set_hexpand(True)
            self._room_search_entry.connect("changed", self._on_room_search_changed)
            self._room_search_entry.connect("focus-out-event", self._on_room_search_focus_out)
            grid.attach(self._room_search_entry, 1, row, 1, 1)
            browse_button = Gtk.Button(label="Ver todas...")
            browse_button.connect("clicked", lambda _b: self._open_room_picker())
            grid.attach(browse_button, 2, row, 1, 1)
            self._room_widgets += [self._room_search_entry, browse_button]
            self._build_room_popover()
        row += 1

        # -- Sonido --
        grid.attach(Gtk.Label(label="Sonido:", xalign=0), 0, row, 1, 1)
        self._sound_label = Gtk.Label(
            label=sonido_display_name(self._sonido_id) if self._sonido_id else "(ninguno)",
            xalign=0,
        )
        self._sound_label.set_hexpand(True)
        grid.attach(self._sound_label, 1, row, 1, 1)
        sound_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        choose_button = Gtk.Button(label="Elegir sonido...")
        choose_button.connect("clicked", lambda _b: self._choose_sound())
        sound_buttons.pack_start(choose_button, False, False, 0)
        self._preview_button = Gtk.Button(label="▶ Probar")
        self._preview_button.set_sensitive(self._sonido_id is not None)
        self._preview_button.connect("clicked", lambda _b: self._preview())
        sound_buttons.pack_start(self._preview_button, False, False, 0)
        grid.attach(sound_buttons, 2, row, 1, 1)
        row += 1

        # -- Repetición --
        grid.attach(self._build_repeat_label(), 0, row, 1, 1)
        grid.attach(self._build_repeat_controls(rule), 1, row, 2, 1)
        row += 1

        # -- @all / @here (solo tipo "mencion") --
        self._mention_all_check = Gtk.CheckButton(label="Avisar también con @all y @here")
        self._mention_all_check.set_active(bool(rule and rule.get("mencion_todos")))
        grid.attach(self._mention_all_check, 0, row, 3, 1)
        row += 1

        self.show_all()
        self._repeat_resync()
        self._apply_type_visibility()
        self.resize(480, 1)  # se dimensionó con todo visible antes de ocultar lo que no toca
        save_button.grab_default()

    # -- Tipo --------------------------------------------------------------------------

    def _apply_type_visibility(self) -> None:
        is_room = self._tipo == "sala"
        for widget in self._room_widgets:
            widget.set_visible(is_room)
        self._mention_all_check.set_visible(not is_room)

    # -- Repetición --------------------------------------------------------------------

    def _build_repeat_label(self) -> Gtk.Box:
        """Etiqueta 'Repetir sonido:' + icono de información con tooltip -el nombre
        por sí solo no deja claro que la repetición depende de si el mensaje sigue
        sin leer, así que se explica al pasar el ratón en vez de alargar la
        etiqueta misma."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_valign(Gtk.Align.START)
        box.pack_start(Gtk.Label(label="Repetir sonido:", xalign=0), False, False, 0)
        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.BUTTON)
        info_icon.set_tooltip_text(
            "El sonido se repite mientras el mensaje siga sin leer en Rocket.Chat "
            "(en cualquier dispositivo), con la frecuencia elegida aquí. En cuanto "
            "lo leas, deja de repetirse."
        )
        box.pack_start(info_icon, False, False, 0)
        return box

    def _build_repeat_controls(self, rule: dict | None) -> Gtk.Box:
        """Modo / número de veces / cada X revisiones. Tras cualquier show_all() hay que
        volver a llamar a self._repeat_resync: show_all() vuelve a mostrar los detalles
        que esta función oculta según el modo."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_valign(Gtk.Align.START)

        self._repeat_combo = Gtk.ComboBoxText()
        self._repeat_combo.append("una_vez", "Solo una vez")
        self._repeat_combo.append("n_veces", "N veces")
        self._repeat_combo.append("infinito", "Hasta que lo leas")
        self._repeat_combo.set_active_id((rule or {}).get("repeticion_modo", "una_vez"))
        box.pack_start(self._repeat_combo, True, True, 0)

        self._repeat_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._repeat_n_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._repeat_n_box.pack_start(Gtk.Label(label="Número de veces:"), False, False, 0)
        self._repeat_n = Gtk.SpinButton.new_with_range(1, 99, 1)
        self._repeat_n.set_value((rule or {}).get("repeticion_n") or 3)
        self._repeat_n_box.pack_start(self._repeat_n, False, False, 0)
        self._repeat_details.pack_start(self._repeat_n_box, False, False, 0)

        every_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        every_box.pack_start(Gtk.Label(label="Cada X revisiones:"), False, False, 0)
        self._repeat_every = Gtk.SpinButton.new_with_range(1, 20, 1)
        self._repeat_every.set_value((rule or {}).get("repeticion_cada_polls") or 1)
        every_box.pack_start(self._repeat_every, False, False, 0)
        self._repeat_details.pack_start(every_box, False, False, 0)
        box.pack_start(self._repeat_details, False, False, 0)

        self._repeat_combo.connect("changed", lambda _c: self._repeat_resync())
        return box

    def _repeat_resync(self) -> None:
        modo = self._repeat_combo.get_active_id()
        self._repeat_details.set_visible(modo != "una_vez")
        self._repeat_n_box.set_visible(modo == "n_veces")

    # -- Sonido ------------------------------------------------------------------------

    def _preview_sonido_id(self, sonido_id: str) -> None:
        try:
            sound_manager.play_sound(sonido_id)
        except sound_manager.SoundPlaybackError as exc:
            show_error_dialog(self, "No se pudo reproducir el sonido", str(exc))

    def _preview(self) -> None:
        if self._sonido_id is None:
            show_error_dialog(self, "Ningún sonido elegido", "Usa 'Elegir sonido...' primero.")
            return
        self._preview_sonido_id(self._sonido_id)

    def _choose_sound(self) -> None:
        chosen = open_sound_picker(
            self, self._sonido_id, self._preview_sonido_id,
            lambda summary, body: show_error_dialog(self, summary, body),
        )
        if chosen is not None:
            self._sonido_id = chosen
            self._sound_label.set_text(sonido_display_name(chosen))
            self._preview_button.set_sensitive(True)

    # -- Buscador de sala --------------------------------------------------------------

    def _build_room_popover(self) -> None:
        # Popover propio en vez de Gtk.EntryCompletion: su popup interno es una ventana
        # override-redirect que calcula la posición a mano en coordenadas X11 globales, y
        # se desalinea en monitores con orígenes distintos bajo XWayland. Un Gtk.Popover
        # deja el posicionamiento en manos del compositor.
        #
        # No modal: un Gtk.Popover modal hace un grab de eventos que bloquea el teclado
        # hacia el propio Gtk.Entry al que está anclado. En su lugar se cierra a mano
        # cuando el campo pierde el foco (ver _on_room_search_focus_out); los clics dentro
        # de la lista no se lo quitan porque sus filas no son enfocables.
        self._room_popover = Gtk.Popover()
        self._room_popover.set_relative_to(self._room_search_entry)
        self._room_popover.set_modal(False)
        self._room_popover.set_position(Gtk.PositionType.BOTTOM)
        self._room_popover_listbox = Gtk.ListBox()
        self._room_popover_listbox.set_can_focus(False)
        self._room_popover_listbox.connect("row-activated", self._on_room_popover_row_activated)
        popover_scroller = Gtk.ScrolledWindow()
        popover_scroller.set_min_content_height(200)
        popover_scroller.set_min_content_width(280)
        popover_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        popover_scroller.add(self._room_popover_listbox)
        self._room_popover.add(popover_scroller)
        popover_scroller.show_all()

    def _set_room_search_text(self, text: str) -> None:
        """Pone texto en el buscador sin que se reabra el popover de sugerencias -el
        texto ya está decidido y no hace falta sugerir nada."""
        self._suppress_room_popover = True
        self._room_search_entry.set_text(text)
        self._room_search_entry.set_position(-1)
        self._suppress_room_popover = False

    def _on_room_search_focus_out(self, _entry, _event) -> bool:
        # Pequeño retraso: al hacer clic en una fila del popover, el foco puede pasar
        # brevemente antes de que termine de procesarse la selección -sin el retraso,
        # cerraríamos el popover antes de que 'row-activated' llegue a ejecutarse.
        GLib.timeout_add(150, lambda: self._room_popover.popdown() or False)
        return False

    def _on_room_search_changed(self, entry) -> None:
        if self._suppress_room_popover:
            return

        text = entry.get_text()
        if self._selected_room is not None and text != self._selected_room[1]:
            self._selected_room = None

        query = text.strip().lower()
        for child in self._room_popover_listbox.get_children():
            self._room_popover_listbox.remove(child)

        if not query:
            self._room_popover.popdown()
            return

        matches = [
            room
            for room in self._known_rooms
            if query in room.get("descripcion", room["nombre"]).lower()
        ][:30]

        if not matches:
            self._room_popover.popdown()
            return

        for room in matches:
            row = Gtk.ListBoxRow()
            row.set_can_focus(False)
            row.room = room
            label = Gtk.Label(label=room.get("descripcion", room["nombre"]), xalign=0)
            label.set_margin_start(6)
            label.set_margin_end(6)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            row.add(label)
            self._room_popover_listbox.add(row)
        self._room_popover_listbox.show_all()
        self._room_popover.popup()

    def _on_room_popover_row_activated(self, _listbox, row) -> None:
        room = getattr(row, "room", None)
        if room is None:
            return
        descripcion = room.get("descripcion", room["nombre"])
        self._selected_room = (room["room_id"], descripcion)
        self._set_room_search_text(descripcion)
        self._room_popover.popdown()

    def _open_room_picker(self) -> None:
        """Árbol plegable de todas las salas conocidas, agrupadas por tipo, con un
        buscador que filtra en vivo. No hace ninguna petición nueva."""
        dialog = Gtk.Dialog(title="Elegir sala o persona", transient_for=self, modal=True)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Seleccionar", Gtk.ResponseType.OK
        )
        dialog.set_default_size(420, 480)

        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text("Buscar sala o persona...")
        dialog.get_content_area().pack_start(search_entry, False, False, 6)

        # Columnas: texto a mostrar (markup), room_id (None en las filas de categoría),
        # texto en minúsculas contra el que se compara el buscador.
        store = Gtk.TreeStore(str, str, str)

        grouped = {}
        for room in self._known_rooms:
            grouped.setdefault(room.get("tipo"), []).append(room)

        for tipo in ROOM_GROUP_ORDER:
            rooms = grouped.get(tipo, [])
            if not rooms:
                continue
            label = ROOM_GROUP_LABELS[tipo]
            category_iter = store.append(None, [f"<b>{label}</b>", None, label.lower()])
            for room in sorted(rooms, key=lambda r: r["nombre"].lower()):
                texto = (
                    f'{GLib.markup_escape_text(room["nombre"])}  '
                    f'<small><span foreground="#888888">({room["room_id"]})</span></small>'
                )
                busqueda = f'{room["nombre"]} {room["room_id"]}'.lower()
                store.append(category_iter, [texto, room["room_id"], busqueda])

        def visible_func(model, tree_iter, _data):
            query = search_entry.get_text().strip().lower()
            if not query:
                return True
            if query in model[tree_iter][2]:
                return True
            child = model.iter_children(tree_iter)
            while child is not None:
                if visible_func(model, child, _data):
                    return True
                child = model.iter_next(child)
            return False

        filtered = store.filter_new()
        filtered.set_visible_func(visible_func)

        treeview = Gtk.TreeView(model=filtered)
        treeview.set_headers_visible(False)
        treeview.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=0))

        def on_search_changed(_entry):
            filtered.refilter()
            if search_entry.get_text().strip():
                treeview.expand_all()
            else:
                treeview.collapse_all()

        search_entry.connect("search-changed", on_search_changed)

        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(360)
        scroller.add(treeview)
        dialog.get_content_area().pack_start(scroller, True, True, 0)

        def get_selected_room_id():
            model, tree_iter = treeview.get_selection().get_selected()
            if tree_iter is None:
                return None
            return model[tree_iter][1]

        treeview.connect(
            "row-activated",
            lambda _tv, _path, _col: dialog.response(Gtk.ResponseType.OK)
            if get_selected_room_id()
            else None,
        )

        dialog.show_all()
        response = dialog.run()
        selected_room_id = get_selected_room_id() if response == Gtk.ResponseType.OK else None
        dialog.destroy()

        if selected_room_id is not None:
            room = next((r for r in self._known_rooms if r["room_id"] == selected_room_id), None)
            if room is not None:
                descripcion = room.get("descripcion", room["nombre"])
                self._selected_room = (room["room_id"], descripcion)
                self._set_room_search_text(descripcion)

    # -- Resultado ---------------------------------------------------------------------

    def _collect(self):
        """(datos, None) si todo es válido, o (None, (titulo, mensaje))."""
        tipo = self._tipo
        room = self._selected_room
        duplicate = (
            self._rule is None
            and tipo == "sala"
            and room is not None
            and find_room_rule(self._config, self._servidor_id, room[0]) is not None
        )
        error = validate_alert(tipo, room if self._rule is None else True, self._sonido_id, duplicate)
        if error is not None:
            return None, error

        modo, n, cada = repeat_values(
            self._repeat_combo.get_active_id(),
            int(self._repeat_n.get_value()),
            int(self._repeat_every.get_value()),
        )
        data = {
            "tipo": tipo,
            "sonido_id": self._sonido_id,
            "mencion_todos": self._mention_all_check.get_active() if tipo == "mencion" else False,
            "repeticion_modo": modo,
            "repeticion_n": n,
            "repeticion_cada_polls": cada,
        }
        if tipo == "sala" and self._rule is None:
            data["room_id"] = room[0]
        return data, None

    def run_and_collect(self):
        """Muestra el diálogo y devuelve los datos de la alerta, o None si se cancela."""
        result = None
        while True:
            response = self.run()
            if response != Gtk.ResponseType.OK:
                break
            data, error = self._collect()
            if error is not None:
                show_error_dialog(self, *error)
                continue
            result = data
            break
        self.destroy()
        return result
