"""Ventana de una sala: historial de solo lectura + respuesta simple de una línea.

Sin adjuntos, hilos ni indicador de escritura -para eso se abre Rocket.Chat directamente.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

from mk96_app_debian_rocket_tool.async_utils import run_in_thread
from mk96_app_debian_rocket_tool.gtk_helpers import notify_error
from mk96_app_debian_rocket_tool.rest_client import RestClient

# Menos mensajes que el límite general de la REST API (ver poller.py): aquí se prioriza
# que la ventana se lea de un vistazo, no tener todo el contexto histórico.
HISTORY_MESSAGE_COUNT = 10


def trailing_new_start(messages: list, own_username: str | None) -> int:
    """Índice a partir del cual los mensajes son "nuevos" y hay que destacarlos: la
    racha final de mensajes que no son tuyos, contando desde el final hacia atrás hasta
    el último mensaje que sí escribiste tú (o hasta el principio si no escribiste
    ninguno). Devuelve len(messages) si no hay nada que destacar -el último mensaje es
    tuyo, o no sabemos qué usuario eres."""
    if own_username is None:
        return len(messages)
    index = len(messages)
    while index > 0 and messages[index - 1].get("sender") != own_username:
        index -= 1
    return index


class ChatWindow(Gtk.Window):
    def __init__(self, rest_client: RestClient, room_id: str, room_type: str, titulo: str):
        super().__init__(title=titulo)
        self.set_default_size(420, 480)

        self._rest_client = rest_client
        self._room_id = room_id
        self._room_type = room_type
        # La respuesta de un hilo puede llegar cuando la ventana ya se cerró.
        self._closed = False
        self.connect("destroy", lambda _w: setattr(self, "_closed", True))

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.set_border_width(6)
        self.add(root)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self._history_buffer = Gtk.TextBuffer()
        self._sender_tag = self._history_buffer.create_tag(
            "sender", weight=Pango.Weight.BOLD
        )
        self._new_tag = self._history_buffer.create_tag(
            "new", weight=Pango.Weight.BOLD, background="#fff3b0", foreground="#3a3000"
        )
        history_view = Gtk.TextView(buffer=self._history_buffer)
        history_view.set_editable(False)
        history_view.set_cursor_visible(False)
        history_view.set_wrap_mode(Gtk.WrapMode.WORD)
        scroller.add(history_view)
        self._history_view = history_view
        root.pack_start(scroller, True, True, 0)

        reply_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._reply_entry = Gtk.Entry()
        self._reply_entry.set_placeholder_text("Escribe una respuesta...")
        self._reply_entry.connect("activate", lambda _e: self._send_reply())
        reply_row.pack_start(self._reply_entry, True, True, 0)

        send_button = Gtk.Button(label="Enviar")
        send_button.connect("clicked", lambda _b: self._send_reply())
        reply_row.pack_start(send_button, False, False, 0)
        root.pack_start(reply_row, False, False, 0)

        self._load_history()
        self.show_all()

    def _load_history(self) -> None:
        def work():
            messages = self._rest_client.room_history(
                self._room_id, self._room_type, count=HISTORY_MESSAGE_COUNT
            )
            return messages, self._rest_client.get_own_username()

        def done(result, error):
            if error is not None:
                notify_error("No se pudo cargar el historial", str(error))
                return
            if self._closed:
                return
            messages, own_username = result
            self._render_history(messages, own_username)

        run_in_thread(work, done)

    def _render_history(self, messages: list, own_username: str | None) -> None:
        buf = self._history_buffer
        buf.set_text("")
        new_start = trailing_new_start(messages, own_username)

        for index, msg in enumerate(messages):
            sender = msg.get("sender") or "?"
            sender_start = buf.get_char_count()
            buf.insert(buf.get_end_iter(), f"{sender}\n")
            buf.apply_tag(
                self._sender_tag,
                buf.get_iter_at_offset(sender_start),
                buf.get_iter_at_offset(sender_start + len(sender)),
            )

            buf.insert(buf.get_end_iter(), f"{msg.get('text', '')}\n\n")
            if index >= new_start:
                buf.apply_tag(
                    self._new_tag,
                    buf.get_iter_at_offset(sender_start),
                    buf.get_end_iter(),
                )

        GLib.idle_add(self._scroll_to_end)

    def _scroll_to_end(self) -> bool:
        mark = self._history_buffer.create_mark(None, self._history_buffer.get_end_iter(), False)
        self._history_view.scroll_to_mark(mark, 0.0, False, 0, 0)
        return GLib.SOURCE_REMOVE

    def _send_reply(self) -> None:
        text = self._reply_entry.get_text().strip()
        if not text:
            return
        self._reply_entry.set_sensitive(False)

        def done(_result, error):
            if self._closed:
                return
            self._reply_entry.set_sensitive(True)
            if error is not None:
                notify_error("No se pudo enviar el mensaje", str(error))
                return
            self._reply_entry.set_text("")
            self._load_history()

        run_in_thread(lambda: self._rest_client.send_message(self._room_id, text), done)
