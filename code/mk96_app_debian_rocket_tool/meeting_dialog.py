"""Diálogo para crear o editar una reunión. Lo abre meetings_window.py; aquí solo se
recogen y validan los datos -guardarlos o borrarlos lo hace la ventana que lo abre."""

from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from mk96_app_debian_rocket_tool import sound_manager
from mk96_app_debian_rocket_tool.gtk_helpers import open_sound_picker, open_url, show_error_dialog
from mk96_app_debian_rocket_tool.meetings import (
    DIAS_SEMANA,
    es_serie,
    format_partial_date_digits,
    format_partial_time_digits,
    normalize_meeting,
    parse_ddmmyyyy,
    parse_hhmm,
    round_up_to_next_half_hour,
)
from mk96_app_debian_rocket_tool.sound_manager import sonido_display_name

DIA_LABELS = {"lun": "L", "mar": "M", "mie": "X", "jue": "J", "vie": "V", "sab": "S", "dom": "D"}

# Teclas de dígito (fila superior y numérico) reconocidas por los campos de
# fecha/hora auto-formateados -ver build_auto_format_entry.
_DIGIT_KEYVALS = {getattr(Gdk, f"KEY_{d}"): str(d) for d in range(10)}
_DIGIT_KEYVALS.update({getattr(Gdk, f"KEY_KP_{d}"): str(d) for d in range(10)})
_NAV_KEYVALS = {
    Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Home, Gdk.KEY_End, Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab,
}

RESPONSE_DELETE = 100


def validate_meeting_form(titulo, fecha_texto, hora_texto, fin_texto, modo, dias):
    """((titulo, mensaje) | None, (fecha, hora, repeticion_fin)) -con error, los valores
    parseados no son fiables."""
    if not titulo or not fecha_texto or not hora_texto:
        return ("Faltan datos", "Título, fecha y hora son obligatorios."), None
    fecha = parse_ddmmyyyy(fecha_texto)
    hora = parse_hhmm(hora_texto)
    if fecha is None or hora is None:
        return (
            "Fecha u hora inválida",
            "Usa el formato DD/MM/AAAA para la fecha y HH:MM (24h) para la hora.",
        ), None
    repeticion_fin = None
    if fin_texto:
        repeticion_fin = parse_ddmmyyyy(fin_texto)
        if repeticion_fin is None:
            return ("Fecha de fin inválida", "Usa el formato DD/MM/AAAA."), None
    if modo == "semanal" and not dias:
        return (
            "Faltan días", "Elige al menos un día de la semana para la repetición semanal."
        ), None
    return None, (fecha, hora, repeticion_fin)


def build_auto_format_entry(
    placeholder, formatter, parser, max_digits, allow_empty, error_tooltip
) -> Gtk.Entry:
    """Entry que se auto-formatea mientras se teclea (inserta el separador en cuanto
    se completa cada grupo de dígitos, vía `formatter`) y se valida al perder el foco
    con `parser` -si el texto no está vacío y no parsea, se marca con el estilo
    nativo 'error' de GTK y un tooltip explicando el problema.

    Los dígitos se guardan aparte (`entry._raw_digits`) y el texto visible se
    reconstruye entero en cada pulsación -reformatear reaccionando a la señal
    "changed" (después de que GTK ya insertó el carácter) descuadra la posición
    interna del cursor de GTK con cada reformateo y los dígitos siguientes
    terminan en el sitio equivocado. Interceptando la tecla ANTES de que GTK
    toque el buffer se evita esa doble mutación. Como contrapartida, el campo es
    "solo se edita por el final": no se puede insertar/borrar en medio del texto,
    hay que borrar hasta el error y volver a teclear (o seleccionar todo y
    reescribir)."""
    entry = Gtk.Entry()
    entry.set_placeholder_text(placeholder)
    entry._raw_digits = ""

    def refresh_text():
        formateado = formatter(entry._raw_digits)
        entry.set_text(formateado)
        entry.set_position(len(formateado))

    def set_formatted_value(texto):
        entry._raw_digits = "".join(c for c in texto if c.isdigit())[:max_digits]
        refresh_text()

    def clear_validation():
        entry.get_style_context().remove_class("error")
        entry.set_tooltip_text("")

    def on_key_press(_entry, event):
        keyval = event.keyval
        if keyval in _NAV_KEYVALS:
            return False
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and keyval in (Gdk.KEY_a, Gdk.KEY_c):
            return False  # seleccionar todo / copiar siguen funcionando
        hay_seleccion = entry.get_selection_bounds() != ()
        if keyval in _DIGIT_KEYVALS:
            if hay_seleccion:
                entry._raw_digits = ""
            if len(entry._raw_digits) < max_digits:
                entry._raw_digits += _DIGIT_KEYVALS[keyval]
            refresh_text()
            return True
        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete):
            entry._raw_digits = "" if hay_seleccion else entry._raw_digits[:-1]
            refresh_text()
            return True
        return True  # bloquea cualquier otra tecla (letras, pegar, etc.)

    def on_focus_out(_entry, _event):
        texto = entry.get_text().strip()
        if texto == "" and allow_empty:
            clear_validation()
        elif parser(texto) is None:
            entry.get_style_context().add_class("error")
            entry.set_tooltip_text(error_tooltip)
        else:
            clear_validation()
        return False

    entry.connect("key-press-event", on_key_press)
    entry.connect("focus-out-event", on_focus_out)
    entry.clear_validation = clear_validation
    entry.set_formatted_value = set_formatted_value
    return entry


def build_calendar_button(target_entry: Gtk.Entry) -> Gtk.Button:
    """Botón '📅' que abre un Gtk.Popover con un Gtk.Calendar anclado a él;
    elegir un día escribe la fecha en target_entry (DD/MM/AAAA) y cierra el
    popover. `opening` evita que el reposicionamiento inicial del calendario
    (select_month/select_day, que también disparan "day-selected") cierre el
    popover antes de que el usuario haya podido elegir nada. `navegando` evita lo
    mismo cuando quien dispara "day-selected" son los botones de cambiar de mes/año
    (GtkCalendar reemite "day-selected" al cambiar de página si ya había un día
    seleccionado) -sin este guard, hojear meses cerraba el popover de golpe. Se
    activa en los cuatro signals de navegación y se desactiva en el siguiente ciclo
    del bucle principal (GLib.idle_add), una vez GTK ya ha terminado de procesar el
    clic y cualquier "day-selected" que haya disparado de rebote."""
    button = Gtk.Button(label="📅")
    popover = Gtk.Popover()
    popover.set_relative_to(button)
    calendar = Gtk.Calendar()
    popover.add(calendar)
    estado = {"opening": False, "navegando": False}

    def dejar_de_navegar():
        estado["navegando"] = False
        return GLib.SOURCE_REMOVE

    def on_navegacion(_calendar):
        estado["navegando"] = True
        GLib.idle_add(dejar_de_navegar)

    def on_day_selected(_calendar):
        if estado["opening"] or estado["navegando"]:
            return
        year, month, day = calendar.get_date()
        target_entry.set_formatted_value(f"{day:02d}/{month + 1:02d}/{year:04d}")
        target_entry.clear_validation()
        popover.popdown()

    def on_button_clicked(_button):
        texto = target_entry.get_text().strip()
        try:
            fecha = datetime.strptime(texto, "%d/%m/%Y").date()
        except ValueError:
            fecha = datetime.now().date()
        estado["opening"] = True
        calendar.select_month(fecha.month - 1, fecha.year)
        calendar.select_day(fecha.day)
        estado["opening"] = False
        popover.show_all()
        popover.popup()

    for senal in ("month-changed", "next-month", "prev-month", "next-year", "prev-year"):
        calendar.connect(senal, on_navegacion)
    calendar.connect("day-selected", on_day_selected)
    button.connect("clicked", on_button_clicked)
    return button


class MeetingDialog(Gtk.Dialog):
    def __init__(self, parent, meeting: dict | None = None, inicio: datetime | None = None,
                 duracion: int | None = None):
        """meeting=None crea una reunión nueva (con fecha/hora `inicio` y `duracion`, o la
        próxima media hora y 30 min si son None); con una reunión existente la edita y ofrece Borrar."""
        super().__init__(
            title="Editar reunión" if meeting else "Nueva reunión", transient_for=parent, modal=True
        )
        self.set_default_size(580, 1)
        self._meeting = meeting
        self._sonido_id = meeting.get("sonido_id") if meeting else None

        if meeting:
            delete_button = self.add_button("Borrar", RESPONSE_DELETE)
            delete_button.get_style_context().add_class("destructive-action")
            self.get_action_area().set_child_secondary(delete_button, True)
        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        save_button = self.add_button("Guardar", Gtk.ResponseType.OK)
        save_button.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_border_width(14)
        self.get_content_area().pack_start(body, True, True, 0)

        if meeting and es_serie(meeting):
            nota = Gtk.Label(
                label="Esta reunión se repite: los cambios afectan a toda la serie.", xalign=0
            )
            nota.get_style_context().add_class("dim-label")
            body.pack_start(nota, False, False, 0)

        # -- Detalles principales --
        self._titulo_entry = Gtk.Entry()
        self._titulo_entry.set_hexpand(True)
        grid = self._add_section(body, "Reunión")
        grid.attach(Gtk.Label(label="Título:", xalign=0), 0, 0, 1, 1)
        grid.attach(self._titulo_entry, 1, 0, 3, 1)
        self._activa_check = Gtk.CheckButton(label="Activa")
        grid.attach(self._activa_check, 1, 1, 3, 1)

        # -- Cuándo --
        grid = self._add_section(body, "Cuándo")
        grid.attach(Gtk.Label(label="Fecha (DD/MM/AAAA):", xalign=0), 0, 0, 1, 1)
        self._fecha_entry = build_auto_format_entry(
            placeholder="20/08/2026",
            formatter=format_partial_date_digits,
            parser=parse_ddmmyyyy,
            max_digits=8,
            allow_empty=False,
            error_tooltip="Usa el formato DD/MM/AAAA con una fecha real.",
        )
        fecha_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        fecha_box.pack_start(self._fecha_entry, True, True, 0)
        fecha_box.pack_start(build_calendar_button(self._fecha_entry), False, False, 0)
        grid.attach(fecha_box, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Hora (HH:MM):", xalign=0), 2, 0, 1, 1)
        self._hora_entry = build_auto_format_entry(
            placeholder="10:00",
            formatter=format_partial_time_digits,
            parser=parse_hhmm,
            max_digits=4,
            allow_empty=False,
            error_tooltip="Usa el formato HH:MM en 24h.",
        )
        grid.attach(self._hora_entry, 3, 0, 1, 1)
        grid.attach(Gtk.Label(label="Duración (min):", xalign=0), 0, 1, 1, 1)
        self._duracion_spin = Gtk.SpinButton.new_with_range(5, 480, 5)
        grid.attach(self._duracion_spin, 1, 1, 1, 1)

        # -- Repetición --
        grid = self._add_section(body, "Repetición")
        grid.attach(Gtk.Label(label="Repetir:", xalign=0), 0, 0, 1, 1)
        self._repeticion_combo = Gtk.ComboBoxText()
        self._repeticion_combo.append("ninguna", "Ninguna")
        self._repeticion_combo.append("diaria", "Diaria")
        self._repeticion_combo.append("semanal", "Semanal")
        self._repeticion_combo.append("mensual", "Mensual (mismo día del mes)")
        self._repeticion_combo.set_hexpand(True)
        self._repeticion_combo.connect("changed", lambda _c: self._update_repeticion_visibility())
        grid.attach(self._repeticion_combo, 1, 0, 3, 1)
        self._dias_label = Gtk.Label(label="Días:", xalign=0)
        grid.attach(self._dias_label, 0, 1, 1, 1)
        self._dias_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._dia_checks = {}
        for dia in DIAS_SEMANA:
            check = Gtk.CheckButton(label=DIA_LABELS[dia])
            self._dias_box.pack_start(check, False, False, 0)
            self._dia_checks[dia] = check
        grid.attach(self._dias_box, 1, 1, 3, 1)
        self._fin_label = Gtk.Label(label="Fin de la serie:", xalign=0)
        grid.attach(self._fin_label, 0, 2, 1, 1)
        self._fin_entry = build_auto_format_entry(
            placeholder="DD/MM/AAAA (opcional)",
            formatter=format_partial_date_digits,
            parser=parse_ddmmyyyy,
            max_digits=8,
            allow_empty=True,
            error_tooltip="Usa el formato DD/MM/AAAA con una fecha real, o déjalo vacío.",
        )
        self._fin_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._fin_box.pack_start(self._fin_entry, True, True, 0)
        self._fin_box.pack_start(build_calendar_button(self._fin_entry), False, False, 0)
        grid.attach(self._fin_box, 1, 2, 3, 1)

        # -- Aviso y sonido --
        grid = self._add_section(body, "Aviso y sonido")
        grid.attach(Gtk.Label(label="Avisar antes (min):", xalign=0), 0, 0, 1, 1)
        self._aviso_spin = Gtk.SpinButton.new_with_range(0, 180, 5)
        grid.attach(self._aviso_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Sonido:", xalign=0), 0, 1, 1, 1)
        self._sonido_label = Gtk.Label(xalign=0)
        self._sonido_label.set_hexpand(True)
        grid.attach(self._sonido_label, 1, 1, 1, 1)
        sound_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        choose_button = Gtk.Button(label="Elegir sonido...")
        choose_button.connect("clicked", lambda _b: self._choose_sound())
        sound_buttons.pack_start(choose_button, False, False, 0)
        preview_button = Gtk.Button(label="▶ Probar")
        preview_button.connect("clicked", lambda _b: self._preview_selected_sound())
        sound_buttons.pack_start(preview_button, False, False, 0)
        grid.attach(sound_buttons, 2, 1, 2, 1)

        # -- Detalles --
        grid = self._add_section(body, "Detalles")
        grid.attach(Gtk.Label(label="Enlace:", xalign=0), 0, 0, 1, 1)
        self._enlace_entry = Gtk.Entry()
        self._enlace_entry.set_placeholder_text("https://... (opcional)")
        self._enlace_entry.set_hexpand(True)
        grid.attach(self._enlace_entry, 1, 0, 2, 1)
        open_link_button = Gtk.Button(label="Abrir")
        open_link_button.connect("clicked", lambda _b: self._open_link())
        grid.attach(open_link_button, 3, 0, 1, 1)
        grid.attach(Gtk.Label(label="Notas:", xalign=0), 0, 1, 1, 1)
        self._notas_entry = Gtk.Entry()
        grid.attach(self._notas_entry, 1, 1, 3, 1)

        self._load(meeting, inicio, duracion)
        self.show_all()
        self._update_repeticion_visibility()
        self.resize(580, 1)
        save_button.grab_default()
        self._titulo_entry.grab_focus()

    @staticmethod
    def _add_section(body: Gtk.Box, title: str) -> Gtk.Grid:
        frame = Gtk.Frame(label=title)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        grid.set_border_width(10)
        frame.add(grid)
        body.pack_start(frame, False, False, 0)
        return grid

    def _load(self, meeting: dict | None, inicio: datetime | None, duracion: int | None) -> None:
        if meeting is None:
            propuesta = inicio or round_up_to_next_half_hour(datetime.now())
            self._fecha_entry.set_formatted_value(propuesta.strftime("%d/%m/%Y"))
            self._hora_entry.set_formatted_value(propuesta.strftime("%H:%M"))
            self._duracion_spin.set_value(duracion or 30)
            self._repeticion_combo.set_active_id("ninguna")
            self._activa_check.set_active(True)
            self._sonido_label.set_text("(por defecto)")
            return
        self._titulo_entry.set_text(meeting["titulo"])
        fecha, hora = meeting["fecha_hora"].split("T")
        self._fecha_entry.set_formatted_value(datetime.strptime(fecha, "%Y-%m-%d").strftime("%d/%m/%Y"))
        self._hora_entry.set_formatted_value(hora)
        self._duracion_spin.set_value(meeting["duracion_min"])
        self._repeticion_combo.set_active_id(meeting["repeticion_modo"])
        for dia, check in self._dia_checks.items():
            check.set_active(dia in meeting["repeticion_dias"])
        repeticion_fin = meeting.get("repeticion_fin")
        self._fin_entry.set_formatted_value(
            datetime.strptime(repeticion_fin, "%Y-%m-%d").strftime("%d/%m/%Y") if repeticion_fin else ""
        )
        for entry in (self._fecha_entry, self._hora_entry, self._fin_entry):
            entry.clear_validation()
        self._aviso_spin.set_value(meeting["aviso_antes_min"])
        self._enlace_entry.set_text(meeting.get("enlace") or "")
        self._notas_entry.set_text(meeting.get("notas") or "")
        self._sonido_label.set_text(
            sonido_display_name(self._sonido_id) if self._sonido_id else "(por defecto)"
        )
        self._activa_check.set_active(meeting["activa"])

    def _update_repeticion_visibility(self) -> None:
        modo = self._repeticion_combo.get_active_id()
        for widget in (self._dias_label, self._dias_box):
            widget.set_visible(modo == "semanal")
        for widget in (self._fin_label, self._fin_box):
            widget.set_visible(modo != "ninguna")

    def _open_link(self) -> None:
        enlace = self._enlace_entry.get_text().strip()
        if enlace:
            open_url(enlace)

    # -- Sonido ----------------------------------------------------------------------

    def _preview_sonido_id(self, sonido_id: str) -> None:
        try:
            sound_manager.play_sound(sonido_id)
        except sound_manager.SoundPlaybackError as exc:
            show_error_dialog(self, "No se pudo reproducir el sonido", str(exc))

    def _preview_selected_sound(self) -> None:
        if self._sonido_id is None:
            show_error_dialog(
                self, "Sonido por defecto", "Esta reunión usa el sonido por defecto de reuniones."
            )
            return
        self._preview_sonido_id(self._sonido_id)

    def _choose_sound(self) -> None:
        chosen = open_sound_picker(
            self, self._sonido_id, self._preview_sonido_id,
            lambda summary, body: show_error_dialog(self, summary, body),
        )
        if chosen is not None:
            self._sonido_id = chosen
            self._sonido_label.set_text(sonido_display_name(chosen))

    # -- Resultado -------------------------------------------------------------------

    def _collect(self):
        """(reunión, None) si todo es válido, o (None, (titulo, mensaje))."""
        modo = self._repeticion_combo.get_active_id()
        dias = [dia for dia, check in self._dia_checks.items() if check.get_active()]
        error, valores = validate_meeting_form(
            self._titulo_entry.get_text().strip(),
            self._fecha_entry.get_text().strip(),
            self._hora_entry.get_text().strip(),
            self._fin_entry.get_text().strip() if modo != "ninguna" else "",
            modo,
            dias,
        )
        if error is not None:
            return None, error
        fecha, hora, repeticion_fin = valores
        meeting = normalize_meeting(
            {
                "id": self._meeting["id"] if self._meeting else None,
                "titulo": self._titulo_entry.get_text().strip(),
                "fecha_hora": f"{fecha}T{hora}",
                "duracion_min": int(self._duracion_spin.get_value()),
                "repeticion_modo": modo,
                "repeticion_dias": dias if modo == "semanal" else [],
                "repeticion_fin": repeticion_fin,
                "aviso_antes_min": int(self._aviso_spin.get_value()),
                "enlace": self._enlace_entry.get_text().strip() or None,
                "notas": self._notas_entry.get_text().strip(),
                "sonido_id": self._sonido_id,
                "activa": self._activa_check.get_active(),
            }
        )
        return meeting, None

    def _confirm_delete(self) -> bool:
        confirm = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            text=f"¿Borrar la reunión «{self._meeting['titulo']}»?",
        )
        confirm.format_secondary_text("Esta acción no se puede deshacer.")
        confirm.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        delete = confirm.add_button("Borrar", Gtk.ResponseType.OK)
        delete.get_style_context().add_class("destructive-action")
        response = confirm.run()
        confirm.destroy()
        return response == Gtk.ResponseType.OK

    def run_and_collect(self):
        """Muestra el diálogo. Devuelve {"accion": "guardar", "reunion": dict},
        {"accion": "borrar"} o None si se cancela."""
        result = None
        self.present()  # que el diálogo reciba el foco: si no, el primer clic solo lo activa
        while True:
            response = self.run()
            if response == RESPONSE_DELETE:
                if self._confirm_delete():
                    result = {"accion": "borrar"}
                    break
                continue
            if response != Gtk.ResponseType.OK:
                break
            meeting, error = self._collect()
            if error is not None:
                show_error_dialog(self, *error)
                continue
            result = {"accion": "guardar", "reunion": meeting}
            break
        self.destroy()
        return result
