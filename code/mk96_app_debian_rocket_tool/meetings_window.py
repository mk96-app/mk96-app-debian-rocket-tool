"""Panel de reuniones: selector/navegación de vistas de calendario (Día/Semana/Mes,
delegadas en meetings_calendar.py). Crear o editar una reunión se hace en
meeting_dialog.py. Mismo estilo que alerts_window.py, pero sin selector de servidor
-las reuniones no están ligadas a ningún servidor Rocket.Chat."""

import calendar
from datetime import date, datetime, timedelta

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from mk96_app_debian_rocket_tool.meeting_dialog import MeetingDialog
from mk96_app_debian_rocket_tool.meetings import (
    con_excepcion,
    es_serie,
    estado_ocurrencia,
    format_day_label,
    format_duracion,
    format_month_label,
    format_week_label,
    reunion_editada,
    week_bounds,
)
from mk96_app_debian_rocket_tool.meetings_calendar import build_day_view, build_month_view, build_week_view


class _CalendarCallbacks:
    def __init__(self, window: "MeetingsWindow"):
        self.on_meeting = window._show_meeting_menu
        self.on_empty = window._show_empty_menu
        self.on_day = window._show_day


class MeetingsWindow(Gtk.Box):
    @staticmethod
    def default_size() -> tuple:
        """Lo bastante grande para ver entero un día, una semana o un mes sin desplazarse,
        sin pasar del área útil de la pantalla (si no cabe, el calendario se desplaza)."""
        ancho, alto = 1000, 900
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0) if display else None
        if monitor is not None:
            area = monitor.get_workarea()
            ancho, alto = min(ancho, area.width - 40), min(alto, area.height - 40)
        return ancho, alto

    def __init__(self, config: dict, on_config_changed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._config = config
        self._on_config_changed = on_config_changed
        self._vista_actual = "semana"
        self._popover = None
        self._vista = None
        self._fecha_referencia = date.today()
        self._callbacks = _CalendarCallbacks(self)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(12)
        self.pack_start(root, True, True, 0)

        top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._vista_dia_radio = Gtk.RadioButton.new_with_label_from_widget(None, "Día")
        self._vista_semana_radio = Gtk.RadioButton.new_with_label_from_widget(
            self._vista_dia_radio, "Semana"
        )
        self._vista_mes_radio = Gtk.RadioButton.new_with_label_from_widget(
            self._vista_dia_radio, "Mes"
        )
        self._vista_semana_radio.set_active(True)  # antes de conectar "toggled": aún no hay vista
        for radio, vista in (
            (self._vista_dia_radio, "dia"),
            (self._vista_semana_radio, "semana"),
            (self._vista_mes_radio, "mes"),
        ):
            radio.set_mode(False)
            radio.connect("toggled", self._on_vista_toggled, vista)
            top_box.pack_start(radio, False, False, 0)
        new_button = Gtk.Button(label="+ Nueva reunión")
        new_button.connect("clicked", lambda _b: self._new_meeting(None))
        top_box.pack_end(new_button, False, False, 0)
        root.pack_start(top_box, False, False, 0)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prev_button = Gtk.Button(label="◀")
        prev_button.connect("clicked", lambda _b: self._navegar_periodo(-1))
        nav_box.pack_start(prev_button, False, False, 0)
        self._periodo_label = Gtk.Label(xalign=0.5)
        self._periodo_label.set_hexpand(True)
        nav_box.pack_start(self._periodo_label, True, True, 0)
        next_button = Gtk.Button(label="▶")
        next_button.connect("clicked", lambda _b: self._navegar_periodo(1))
        nav_box.pack_start(next_button, False, False, 0)
        hoy_button = Gtk.Button(label="Hoy")
        hoy_button.connect("clicked", lambda _b: self._ir_a_hoy())
        nav_box.pack_start(hoy_button, False, False, 0)
        root.pack_start(nav_box, False, False, 0)

        self._calendario_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self._calendario_container, True, True, 0)

        self.show_all()
        self._refresh_calendar()
        # Mueve la marca roja de la hora actual sin reconstruir la vista.
        tick = GLib.timeout_add_seconds(20, self._tick)
        self.connect("destroy", lambda _w: GLib.source_remove(tick))

    def _tick(self) -> bool:
        if self._vista is not None:
            self._vista.tick()
        return True

    # -- Navegación --------------------------------------------------------------

    def _on_vista_toggled(self, radio, vista) -> None:
        if not radio.get_active():
            return
        self._vista_actual = vista
        self._refresh_calendar()

    def _navegar_periodo(self, direccion: int) -> None:
        if self._vista_actual == "dia":
            self._fecha_referencia += timedelta(days=direccion)
        elif self._vista_actual == "semana":
            self._fecha_referencia += timedelta(weeks=direccion)
        else:
            year, month = self._fecha_referencia.year, self._fecha_referencia.month + direccion
            if month < 1:
                month, year = 12, year - 1
            elif month > 12:
                month, year = 1, year + 1
            dia = min(self._fecha_referencia.day, calendar.monthrange(year, month)[1])
            self._fecha_referencia = date(year, month, dia)
        self._refresh_calendar()

    def _ir_a_hoy(self) -> None:
        self._fecha_referencia = date.today()
        self._refresh_calendar()

    def _show_day(self, dia: date) -> None:
        """'+N más' de la vista Mes: pasa a la vista Día de ese día."""
        self._fecha_referencia = dia
        if self._vista_dia_radio.get_active():
            self._refresh_calendar()
        else:
            self._vista_dia_radio.set_active(True)  # su "toggled" refresca

    def _refresh_calendar(self) -> None:
        for child in self._calendario_container.get_children():
            self._calendario_container.remove(child)

        ahora = datetime.now()
        reuniones = self._config["reuniones"]

        if self._vista_actual == "dia":
            self._periodo_label.set_text(format_day_label(self._fecha_referencia))
            vista = build_day_view(reuniones, self._fecha_referencia, ahora, self._callbacks)
        elif self._vista_actual == "semana":
            lunes, _fin_semana = week_bounds(self._fecha_referencia)
            self._periodo_label.set_text(format_week_label(lunes))
            vista = build_week_view(reuniones, lunes, ahora, self._callbacks)
        else:
            self._periodo_label.set_text(
                format_month_label(self._fecha_referencia.year, self._fecha_referencia.month)
            )
            vista = build_month_view(
                reuniones, self._fecha_referencia.year, self._fecha_referencia.month, ahora,
                self._callbacks,
            )

        self._vista = vista
        self._calendario_container.pack_start(vista.widget, True, True, 0)
        self._calendario_container.show_all()
        # Hasta que la vista tiene tamaño asignado no se puede calcular el desplazamiento.
        GLib.timeout_add(80, vista.scroll_to_ancla)

    # -- Menús emergentes ------------------------------------------------------------

    def _popup(self, widget, rect, titulo: str, acciones: list) -> None:
        """Popover modal (un clic fuera lo cierra) con un título y botones. Cada acción se
        ejecuta ya cerrado el popover y fuera del manejador del clic -abrir un diálogo
        desde dentro del evento le quita el foco al diálogo."""
        if self._popover is not None:
            self._popover.destroy()
        popover = Gtk.Popover()
        popover.set_relative_to(widget)
        if rect is not None:
            popover.set_pointing_to(rect)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_border_width(8)
        cabecera = Gtk.Label(xalign=0)
        cabecera.set_markup(f"<b>{GLib.markup_escape_text(titulo)}</b>")
        cabecera.set_margin_bottom(4)
        box.pack_start(cabecera, False, False, 0)
        for etiqueta, accion, destructiva in acciones:
            boton = Gtk.Button(label=etiqueta)
            boton.set_relief(Gtk.ReliefStyle.NONE)
            boton.get_child().set_xalign(0)
            if destructiva:
                boton.get_style_context().add_class("destructive-action")
            boton.connect("clicked", lambda _b, a=accion: self._run_action(popover, a))
            box.pack_start(boton, False, False, 0)
        popover.add(box)
        box.show_all()
        self._popover = popover
        popover.popup()

    @staticmethod
    def _run_action(popover, accion) -> None:
        popover.popdown()
        GLib.idle_add(lambda: accion() or False)

    def _show_empty_menu(self, momento: datetime, duracion, widget, rect) -> None:
        if duracion is None:
            titulo = "Hueco libre"
            etiqueta = f"+ Añadir reunión el {momento.strftime('%d/%m/%Y')} a las {momento.strftime('%H:%M')}"
        else:
            fin = momento + timedelta(minutes=duracion)
            titulo = momento.strftime("%d/%m/%Y")
            etiqueta = (
                f"+ Añadir reunión de {momento.strftime('%H:%M')} a {fin.strftime('%H:%M')} "
                f"({format_duracion(duracion)})"
            )
        self._popup(widget, rect, titulo, [(etiqueta, lambda: self._new_meeting(momento, duracion), False)])

    def _show_meeting_menu(self, meeting: dict, ocurrencia: datetime, widget) -> None:
        activa = estado_ocurrencia(meeting, ocurrencia) == "activa"
        if activa:
            etiqueta_estado = "Desactivar"
        else:
            etiqueta_estado = "Activar toda la serie" if es_serie(meeting) and not meeting["activa"] else "Activar"
        self._popup(
            widget, None, f"{ocurrencia.strftime('%H:%M')} {meeting['titulo']}",
            [
                ("Editar...", lambda: self._edit_meeting(meeting), False),
                (etiqueta_estado, lambda: self._toggle_meeting(meeting, ocurrencia), False),
                ("Eliminar", lambda: self._delete_meeting(meeting, ocurrencia), True),
            ],
        )

    # -- Crear / editar / activar / borrar ---------------------------------------------

    def _new_meeting(self, inicio: datetime | None, duracion: int | None = None) -> None:
        GLib.idle_add(lambda: self._open_dialog(None, inicio, duracion) or False)

    def _edit_meeting(self, meeting: dict) -> None:
        GLib.idle_add(lambda: self._open_dialog(meeting, None, None) or False)

    def _save(self, meeting: dict) -> None:
        """Sustituye (por id) o añade `meeting` y refresca."""
        self._config["reuniones"] = [
            m for m in self._config["reuniones"] if m["id"] != meeting["id"]
        ] + [meeting]
        self._on_config_changed(self._config)
        self._refresh_calendar()

    def _remove(self, meeting: dict) -> None:
        self._config["reuniones"] = [m for m in self._config["reuniones"] if m["id"] != meeting["id"]]
        self._on_config_changed(self._config)
        self._refresh_calendar()

    def _open_dialog(self, meeting: dict | None, inicio: datetime | None, duracion: int | None) -> None:
        resultado = MeetingDialog(self.get_toplevel(), meeting, inicio, duracion).run_and_collect()
        if resultado is None:
            return
        if resultado["accion"] == "borrar":
            self._remove(meeting)
            return
        nueva = reunion_editada(meeting, resultado["reunion"])
        self._fecha_referencia = datetime.strptime(nueva["fecha_hora"], "%Y-%m-%dT%H:%M").date()
        self._save(nueva)

    def _ask_scope(self, verbo: str, meeting: dict, ocurrencia: datetime):
        """Para una serie: "esta", "serie" o None si se cancela."""
        dialog = Gtk.MessageDialog(
            transient_for=self.get_toplevel(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            text=f"«{meeting['titulo']}» se repite",
        )
        dialog.format_secondary_text(
            f"¿Quieres {verbo} solo la del {ocurrencia.strftime('%d/%m/%Y')} a las "
            f"{ocurrencia.strftime('%H:%M')} o toda la serie?"
        )
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("Solo esta", 1)
        toda = dialog.add_button("Toda la serie", 2)
        if verbo == "eliminar":
            toda.get_style_context().add_class("destructive-action")
        respuesta = dialog.run()
        dialog.destroy()
        return {1: "esta", 2: "serie"}.get(respuesta)

    def _delete_meeting(self, meeting: dict, ocurrencia: datetime) -> None:
        if es_serie(meeting):
            alcance = self._ask_scope("eliminar", meeting, ocurrencia)
            if alcance == "esta":
                self._save(con_excepcion(meeting, ocurrencia, "borrada"))
            elif alcance == "serie":
                self._remove(meeting)
            return
        confirmar = Gtk.MessageDialog(
            transient_for=self.get_toplevel(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            text=f"¿Eliminar la reunión «{meeting['titulo']}»?",
        )
        confirmar.format_secondary_text("Esta acción no se puede deshacer.")
        confirmar.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        eliminar = confirmar.add_button("Eliminar", Gtk.ResponseType.OK)
        eliminar.get_style_context().add_class("destructive-action")
        respuesta = confirmar.run()
        confirmar.destroy()
        if respuesta == Gtk.ResponseType.OK:
            self._remove(meeting)

    def _toggle_meeting(self, meeting: dict, ocurrencia: datetime) -> None:
        if estado_ocurrencia(meeting, ocurrencia) == "activa":
            if es_serie(meeting):
                alcance = self._ask_scope("desactivar", meeting, ocurrencia)
                if alcance == "esta":
                    self._save(con_excepcion(meeting, ocurrencia, "inactiva"))
                elif alcance == "serie":
                    self._save({**meeting, "activa": False})
            else:
                self._save({**meeting, "activa": False})
        elif not meeting["activa"]:
            self._save({**meeting, "activa": True})  # reactivar es siempre de toda la reunión
        else:
            self._save(con_excepcion(meeting, ocurrencia, None))
