"""Helpers de UI compartidos: items de menú de acción y notificaciones de escritorio.

Nota de arquitectura (heredada de mk96-app-debian-switchboard): AppIndicator no dibuja el menú en
este proceso, lo exporta por D-Bus (protocolo com.canonical.dbusmenu) y GNOME Shell lo
reconstruye y lo muestra. Los items de acción TIENEN que ser Gtk.MenuItem normales
conectados a 'activate' -cualquier otro widget/señal no llega nunca a dispararse.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from mk96_app_debian_rocket_tool import sound_manager
from mk96_app_debian_rocket_tool.dbus_utils import ServiceUnavailable, call_sync, get_proxy

NOTIFICATIONS_BUS_NAME = "org.freedesktop.Notifications"
NOTIFICATIONS_PATH = "/org/freedesktop/Notifications"
NOTIFICATIONS_IFACE = "org.freedesktop.Notifications"
APP_NAME = "MK96 Debian Rocket Tool"


def make_action_item(label: str, callback) -> Gtk.MenuItem:
    item = Gtk.MenuItem(label=label)
    item.connect("activate", lambda _widget: callback())
    return item


def make_checkbox_item(label: str, is_checked: bool, callback) -> Gtk.CheckMenuItem:
    item = Gtk.CheckMenuItem(label=label)
    item.set_active(is_checked)
    item.connect("toggled", lambda widget: callback(widget.get_active()))
    return item


def notify_message(summary: str, body: str, icon: str = "dialog-information") -> None:
    """Notificación de escritorio best-effort; si el servicio no responde, no hace nada."""
    try:
        proxy = get_proxy(
            Gio.BusType.SESSION,
            NOTIFICATIONS_BUS_NAME,
            NOTIFICATIONS_PATH,
            NOTIFICATIONS_IFACE,
        )
        call_sync(
            proxy,
            "Notify",
            GLib.Variant(
                "(susssasa{sv}i)",
                (APP_NAME, 0, icon, summary, body, [], {}, 5000),
            ),
        )
    except ServiceUnavailable:
        pass


def notify_error(summary: str, body: str) -> None:
    notify_message(summary, body, icon="dialog-error")


def show_error_dialog(parent: Gtk.Window, summary: str, body: str) -> None:
    dialog = Gtk.MessageDialog(
        parent=parent,
        flags=0,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text=summary,
    )
    dialog.format_secondary_text(body)
    dialog.run()
    dialog.destroy()


def open_url(url: str) -> None:
    """Abre un enlace con la aplicación por defecto del sistema, en background -mismo
    enfoque 'shell-out' que sound_manager.play_sound con paplay."""
    # xdg-open 1.1.x no admite "--", así que se descarta lo que parezca una opción.
    if url.startswith("-"):
        return
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def open_sound_picker(parent: Gtk.Window, current_sonido_id: str | None, on_preview, on_error) -> str | None:
    """Árbol plegable de los sonidos disponibles (propios primero, luego la paleta
    empaquetada por categoría), con buscador que filtra en vivo, más un botón para
    añadir uno nuevo desde el equipo, que se copia a sounds/user y queda elegible al
    momento. on_preview(sonido_id) reproduce un sonido para probarlo; on_error(summary,
    body) muestra un fallo -ambos los da quien llama, para no acoplar este helper
    compartido a una ventana concreta."""
    dialog = Gtk.Dialog(title="Elegir sonido", transient_for=parent, modal=True)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Seleccionar", Gtk.ResponseType.OK
    )
    dialog.set_default_size(420, 480)

    search_entry = Gtk.SearchEntry()
    search_entry.set_placeholder_text("Buscar sonido...")
    dialog.get_content_area().pack_start(search_entry, False, False, 6)

    # Columnas: texto a mostrar, sonido_id (None en las filas de categoría), texto en
    # minúsculas contra el que se compara el buscador.
    store = Gtk.TreeStore(str, str, str)

    def populate(select_sonido_id=None):
        store.clear()
        grouped = {}
        order = []
        for sound in sound_manager.list_available_sounds():
            if sound["categoria"] not in grouped:
                grouped[sound["categoria"]] = []
                order.append(sound["categoria"])
            grouped[sound["categoria"]].append(sound)

        select_path = None
        for categoria in order:
            category_iter = store.append(None, [f"<b>{categoria}</b>", None, categoria.lower()])
            for sound in grouped[categoria]:
                child_iter = store.append(
                    category_iter, [sound["nombre"], sound["sonido_id"], sound["nombre"].lower()]
                )
                if sound["sonido_id"] == select_sonido_id:
                    select_path = store.get_path(child_iter)

        return select_path

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
    renderer = Gtk.CellRendererText()
    name_column = Gtk.TreeViewColumn("", renderer, markup=0)
    name_column.set_expand(True)
    treeview.append_column(name_column)

    preview_renderer = Gtk.CellRendererText()
    preview_renderer.set_property("xalign", 0.5)
    hovered_path = [None]

    def preview_cell_data_func(_column, cell, model, tree_iter, _data):
        sonido_id = model[tree_iter][1]
        cell.set_property("text", "▶" if sonido_id else "")
        is_hovered = bool(sonido_id) and model.get_path(tree_iter) == hovered_path[0]
        if is_hovered:
            cell.set_property("background", "#3584e4")
            cell.set_property("foreground", "#ffffff")
        else:
            cell.set_property("background", None)
            cell.set_property("foreground", None)

    preview_column = Gtk.TreeViewColumn("", preview_renderer)
    preview_column.set_cell_data_func(preview_renderer, preview_cell_data_func)
    preview_column.set_fixed_width(36)
    preview_column.set_spacing(6)
    treeview.append_column(preview_column)
    treeview.set_margin_end(8)

    def on_treeview_button_press(_widget, event):
        hit = treeview.get_path_at_pos(int(event.x), int(event.y))
        if hit is None:
            return False
        path, column, _cell_x, _cell_y = hit
        if column is not preview_column:
            return False
        tree_iter = filtered.get_iter(path)
        sonido_id = filtered[tree_iter][1]
        if sonido_id:
            on_preview(sonido_id)
        return True

    def on_treeview_motion(_widget, event):
        new_path = None
        hit = treeview.get_path_at_pos(int(event.x), int(event.y))
        if hit is not None:
            path, column, _cell_x, _cell_y = hit
            if column is preview_column:
                tree_iter = filtered.get_iter(path)
                if filtered[tree_iter][1]:
                    new_path = path
        if new_path != hovered_path[0]:
            hovered_path[0] = new_path
            treeview.queue_draw()
        return False

    def on_treeview_leave(_widget, _event):
        if hovered_path[0] is not None:
            hovered_path[0] = None
            treeview.queue_draw()
        return False

    treeview.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
    treeview.connect("button-press-event", on_treeview_button_press)
    treeview.connect("motion-notify-event", on_treeview_motion)
    treeview.connect("leave-notify-event", on_treeview_leave)

    def on_search_changed(_entry):
        filtered.refilter()
        if search_entry.get_text().strip():
            treeview.expand_all()
        else:
            treeview.collapse_all()

    search_entry.connect("search-changed", on_search_changed)

    scroller = Gtk.ScrolledWindow()
    scroller.set_min_content_height(320)
    scroller.add(treeview)
    dialog.get_content_area().pack_start(scroller, True, True, 0)

    add_button = Gtk.Button(label="Añadir desde mi equipo...")
    dialog.get_content_area().pack_start(add_button, False, False, 6)

    def select_path_in_tree(store_path):
        if store_path is None:
            return
        filter_path = filtered.convert_child_path_to_path(store_path)
        if filter_path is None:
            return
        treeview.expand_to_path(filter_path)
        treeview.get_selection().select_path(filter_path)

    select_path_in_tree(populate(current_sonido_id))

    def get_selected_sonido_id():
        selection = treeview.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter is None:
            return None
        return model[tree_iter][1]

    def on_add_clicked(_button):
        file_dialog = Gtk.FileChooserDialog(
            title="Elegir sonido personalizado",
            parent=dialog,
            action=Gtk.FileChooserAction.OPEN,
        )
        file_dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        if file_dialog.run() == Gtk.ResponseType.OK:
            source_path = file_dialog.get_filename()
            sonido_id = os.path.splitext(os.path.basename(source_path))[0]
            try:
                sound_manager.add_custom_sound(source_path, sonido_id)
                select_path_in_tree(populate(select_sonido_id=sonido_id))
            except (ValueError, OSError) as exc:
                on_error("No se pudo añadir el sonido", str(exc))
        file_dialog.destroy()

    add_button.connect("clicked", on_add_clicked)
    treeview.connect(
        "row-activated",
        lambda _tv, _path, _col: dialog.response(Gtk.ResponseType.OK)
        if get_selected_sonido_id()
        else None,
    )

    dialog.show_all()
    response = dialog.run()
    chosen = None
    if response == Gtk.ResponseType.OK:
        chosen = get_selected_sonido_id()
    dialog.destroy()
    return chosen
