"""Vistas de calendario (Día/Semana/Mes) de MeetingsWindow: traducen las reuniones ya
calculadas por meetings.py (occurrences_in_range, assign_lanes, filas_para_bloque,
posicion_columna) a Gtk.Grid/Gtk.Box -este módulo no repite lógica de recurrencia ni de
solapes, solo la dibuja.

Cada builder devuelve un CalendarView (widget ya con su scroll + scroll_to_ancla para
llevar la vista a la hora actual). Clic izquierdo (arrastrando) selecciona franjas en Día/Semana; los menús se abren con clic derecho. `callbacks` es un objeto con
on_meeting(reunión, ocurrencia, widget), on_empty(datetime, duracion_min | None, widget, rect) -clic
derecho en un hueco o franja; `rect` (Gdk.Rectangle o None) sitúa el punto pulsado dentro de `widget`- y
on_day(date) -"+N más" del mes."""

from datetime import date, datetime, timedelta

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango

from mk96_app_debian_rocket_tool.meetings import (
    CARRILES_POR_DIA,
    DIAS_SEMANA,
    NOMBRES_DIA_CORTO,
    TIMELINE_FILAS,
    TIMELINE_FRANJA_MIN,
    TIMELINE_INICIO_HORA,
    assign_lanes,
    fila_timeline,
    filas_para_bloque,
    franja_seleccion,
    estado_ocurrencia,
    hora_por_defecto_en_dia,
    ocurrencias_visibles,
    posicion_ahora,
    posicion_columna,
)

SLOT_HEIGHT = 22
BORDE_DIA = 3  # px de aire entre las reuniones y la línea que separa los días
HOUR_COL_WIDTH = 56
MAX_PILLS_POR_DIA = 3

# Tintes azules translúcidos: válidos en tema claro y oscuro.
_CSS = Gtk.CssProvider()
_CSS.load_from_data(
    b"""
.slot { border-top: 1px solid alpha(@theme_fg_color, 0.07); }
.slot-hour { border-top-color: alpha(@theme_fg_color, 0.2); }
.slot-first { border-left: 1px solid alpha(@theme_fg_color, 0.2); }
.slot-today { background-color: alpha(#3584e4, 0.07); }
.day-header { padding: 4px; border-radius: 6px; }
.day-header-today { background-color: alpha(#3584e4, 0.35); font-weight: bold; }
.meeting-block, .meeting-pill {
    background-image: none; background-color: alpha(#3584e4, 0.4);
    border: 1px solid alpha(#3584e4, 0.9); border-radius: 4px;
    padding: 1px 4px; min-height: 0; box-shadow: none; margin: 1px;
}
.meeting-pill { padding: 0 4px; margin: 1px 3px; }
.meeting-off { background-color: alpha(#9a9996, 0.25); border-color: alpha(#9a9996, 0.6); color: #9a9996; }
.month-cell { border: 1px solid alpha(@theme_fg_color, 0.15); border-radius: 6px; }
.month-cell-off { background-color: alpha(@theme_fg_color, 0.04); }
.month-cell-today { border: 2px solid #3584e4; }
.more-link { padding: 0 4px; min-height: 0; }
"""
)


class CalendarView:
    def __init__(self, widget: Gtk.Widget, scroll_to_ancla=None, tick=None):
        self.widget = widget
        self._scroll = scroll_to_ancla
        self._tick = tick

    def tick(self) -> None:
        """Mueve la marca de la hora actual (llamar cada pocos segundos)."""
        if self._tick is not None:
            self._tick()

    def scroll_to_ancla(self) -> bool:
        """Lleva la vista a la hora actual (Día/Semana). Devuelve False para poder
        usarse directamente como callback de GLib.timeout_add."""
        if self._scroll is not None:
            self._scroll()
        return False


def _pintar_slot(slot, cr, indice: int, fila: int, hoy: bool, estado: dict) -> bool:
    """Se dibuja sobre cada hueco de la rejilla, por encima de su fondo CSS: el resaltado
    de la franja seleccionada y, en la columna de hoy, la marca roja de la hora actual
    exacta al minuto (a la altura proporcional de los minutos transcurridos en la fila).
    Se pinta a mano porque cambiar clases CSS en caliente no repintaba estas cajas."""
    ancho, alto = slot.get_allocated_width(), slot.get_allocated_height()
    sel = estado["sel"]
    if sel is not None and sel[0] == indice and min(sel[1], sel[2]) <= fila <= max(sel[1], sel[2]):
        cr.set_source_rgba(0.208, 0.518, 0.894, 0.35)
        cr.rectangle(0, 0, ancho, alto)
        cr.fill()
    if hoy:
        posicion = posicion_ahora(estado["ahora"])
        if posicion is not None and posicion[0] == fila:
            y = posicion[1] * alto
            cr.set_source_rgb(0.878, 0.106, 0.141)
            cr.rectangle(0, y - 1, ancho, 2)
            cr.fill()
            cr.arc(4, y, 4, 0, 6.2832)
            cr.fill()
    return False


def _clic_derecho(accion):
    """Manejador de "button-press-event" que solo reacciona al botón derecho."""
    def manejador(widget, evento):
        if evento.button != 3:
            return False
        accion(widget)
        return True
    return manejador


def _estilo(widget: Gtk.Widget, *clases: str) -> None:
    context = widget.get_style_context()
    context.add_provider(_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    for clase in clases:
        context.add_class(clase)


def tooltip_reunion(meeting: dict, ocurrencia: datetime) -> str:
    """Título completo + franja horaria (y notas), para el tooltip de un bloque o pastilla."""
    fin = ocurrencia + timedelta(minutes=meeting["duracion_min"])
    texto = f"{meeting['titulo']}\n{ocurrencia.strftime('%H:%M')} - {fin.strftime('%H:%M')} ({meeting['duracion_min']} min)"
    if estado_ocurrencia(meeting, ocurrencia) == "inactiva":
        texto += "\n(inactiva)"
    if meeting.get("notas"):
        texto += f"\n{meeting['notas']}"
    return texto


def pastillas_visibles(total: int, maximo: int = MAX_PILLS_POR_DIA) -> tuple:
    """(visibles, ocultas) de las reuniones de un día en la vista Mes."""
    if total <= maximo:
        return total, 0
    return maximo, total - maximo


def _etiqueta_bloque(ocurrencia: datetime, meeting: dict, recortada_arriba: bool, recortada_abajo: bool) -> str:
    texto = f"{ocurrencia.strftime('%H:%M')} {meeting['titulo']}"
    if recortada_arriba:
        texto = "▲ " + texto
    if recortada_abajo:
        texto = texto + " ▼"
    return texto


def _intervalos_del_dia(meetings: list, dia) -> list:
    """Intervalos para assign_lanes, ya en FILAS DE REJILLA cuantizadas (no en
    horas de reloj reales): dos reuniones consecutivas cortas (10:00-10:15 y
    10:15-10:30) pueden caer en la MISMA fila de 30 minutos aunque no se solapen en
    reloj, así que el carril hay que asignarlo sobre la cuantización ya aplicada,
    o ambas terminan dibujadas en la misma celda. assign_lanes no exige datetimes,
    solo valores comparables con < y <=, así que enteros de fila funcionan igual."""
    inicio_dia = datetime.combine(dia, datetime.min.time())
    fin_dia = inicio_dia + timedelta(days=1)
    intervalos = []
    for meeting in meetings:
        for ocurrencia in ocurrencias_visibles(meeting, inicio_dia, fin_dia):
            fila_inicio, num_filas, recortada_arriba, recortada_abajo = filas_para_bloque(
                ocurrencia, meeting["duracion_min"]
            )
            intervalos.append(
                (
                    fila_inicio,
                    fila_inicio + num_filas,
                    (meeting, ocurrencia, fila_inicio, num_filas, recortada_arriba, recortada_abajo),
                )
            )
    return intervalos


def _bloque(ocurrencia, meeting, recortada_arriba, recortada_abajo, callbacks) -> Gtk.Button:
    boton = Gtk.Button(label=_etiqueta_bloque(ocurrencia, meeting, recortada_arriba, recortada_abajo))
    boton.set_hexpand(True)
    boton.set_halign(Gtk.Align.FILL)
    etiqueta = boton.get_child()
    etiqueta.set_xalign(0)
    etiqueta.set_ellipsize(Pango.EllipsizeMode.END)
    etiqueta.set_line_wrap(False)
    _estilo(boton, "meeting-block", *(("meeting-off",) if estado_ocurrencia(meeting, ocurrencia) == "inactiva" else ()))
    boton.set_tooltip_text(tooltip_reunion(meeting, ocurrencia))
    boton.connect("button-press-event", _clic_derecho(lambda b, m=meeting, o=ocurrencia: callbacks.on_meeting(m, o, b)))
    return boton


def _construir_timeline(dias: list, meetings: list, ahora: datetime, callbacks, con_cabecera: bool) -> CalendarView:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    num_dias = len(dias)

    if con_cabecera:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        spacer = Gtk.Box()
        spacer.set_size_request(HOUR_COL_WIDTH, -1)
        header.pack_start(spacer, False, False, 0)
        header_grid = Gtk.Grid(column_homogeneous=True, column_spacing=2)
        for indice, dia in enumerate(dias):
            cabecera = Gtk.Label(label=f"{NOMBRES_DIA_CORTO[DIAS_SEMANA[dia.weekday()]]} {dia.day:02d}")
            _estilo(cabecera, "day-header", *(("day-header-today",) if dia == ahora.date() else ()))
            header_grid.attach(cabecera, indice, 0, 1, 1)
        header.pack_start(header_grid, True, True, 0)
        outer.pack_start(header, False, False, 4)

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

    horas = Gtk.Grid(row_homogeneous=True)
    horas.set_size_request(HOUR_COL_WIDTH, -1)
    for fila in range(0, TIMELINE_FILAS, 2):
        hora = TIMELINE_INICIO_HORA + fila * TIMELINE_FRANJA_MIN // 60
        etiqueta = Gtk.Label(label=f"{hora:02d}:00", xalign=1)
        etiqueta.set_valign(Gtk.Align.START)
        etiqueta.set_margin_end(6)
        etiqueta.get_style_context().add_class("dim-label")
        horas.attach(etiqueta, 0, fila, 1, 2)
    body.pack_start(horas, False, False, 0)

    columnas = Gtk.Grid(column_homogeneous=True, row_homogeneous=True)
    fila_ahora, ahora_recortada = fila_timeline(ahora)
    hoy_visible = ahora.date() in dias and not ahora_recortada
    slots = {}
    slots_hoy = []
    estado = {"ahora": ahora, "sel": None, "drag": None}
    for indice, dia in enumerate(dias):
        for fila in range(TIMELINE_FILAS):
            # Cajas sin ventana propia: solo dibujan el fondo. Los clics en huecos vacíos
            # los recoge un único EventBox sobre toda la rejilla (ver más abajo), así no hay
            # ventanas de entrada apiladas bajo los bloques que les quiten los clics.
            slot = Gtk.Box()
            slot.set_size_request(-1, SLOT_HEIGHT)
            clases = ["slot"]
            if fila % 2 == 0:
                clases.append("slot-hour")
            es_hoy = dia == ahora.date()
            if es_hoy:
                clases.append("slot-today")
                slots_hoy.append(slot)
            slot.connect_after(
                "draw", lambda w, cr, i=indice, f=fila, h=es_hoy: _pintar_slot(w, cr, i, f, h, estado)
            )
            if indice > 0 or num_dias == 1:
                clases.append("slot-first")
            _estilo(slot, *clases)
            columnas.attach(slot, indice * CARRILES_POR_DIA, fila, CARRILES_POR_DIA, 1)
            slots[(indice, fila)] = slot

        for item, carril, total_carriles in assign_lanes(_intervalos_del_dia(meetings, dia)):
            meeting, ocurrencia, fila_inicio, num_filas, rec_arriba, rec_abajo = item
            columna_relativa, ancho = posicion_columna(carril, total_carriles)
            bloque = _bloque(ocurrencia, meeting, rec_arriba, rec_abajo, callbacks)
            # Aire entre días: solo en los bordes del día, para no restar ancho a los
            # carriles de reuniones solapadas, que ya van justos.
            if columna_relativa == 0:
                bloque.set_margin_start(BORDE_DIA + 1)  # +1: compensa la línea de 1 px del propio día
            if columna_relativa + ancho >= CARRILES_POR_DIA:
                bloque.set_margin_end(BORDE_DIA)
            columnas.attach(
                bloque, indice * CARRILES_POR_DIA + columna_relativa, fila_inicio, ancho, num_filas,
            )

    def celda(widget, evento):
        ancho, alto = widget.get_allocated_width(), widget.get_allocated_height()
        indice = min(num_dias - 1, max(0, int(evento.x * num_dias / ancho)))
        fila = min(TIMELINE_FILAS - 1, max(0, int(evento.y * TIMELINE_FILAS / alto)))
        return indice, fila

    def pintar_seleccion():
        for slot in slots.values():
            slot.queue_draw()

    def on_press(widget, evento):
        indice, fila = celda(widget, evento)
        if evento.button == 1:
            estado["drag"] = (indice, fila)
            estado["sel"] = (indice, fila, fila)
            pintar_seleccion()
            return True
        if evento.button != 3:
            return False
        sel = estado["sel"]
        if sel is None or sel[0] != indice or not min(sel[1], sel[2]) <= fila <= max(sel[1], sel[2]):
            # Clic derecho fuera de la selección: el menú se refiere a esa franja suelta.
            estado["sel"] = sel = (indice, fila, fila)
            pintar_seleccion()
        inicio, duracion = franja_seleccion(dias[sel[0]], sel[1], sel[2])
        punto = Gdk.Rectangle()
        punto.x, punto.y, punto.width, punto.height = int(evento.x), int(evento.y), 1, 1
        callbacks.on_empty(inicio, duracion, widget, punto)
        return True

    def on_motion(widget, evento):
        if estado["drag"] is None:
            return False
        indice0, fila0 = estado["drag"]  # el arrastre se queda en la columna (día) donde empezó
        _, fila = celda(widget, evento)
        estado["sel"] = (indice0, fila0, fila)
        pintar_seleccion()
        return True

    def on_release(_widget, evento):
        if evento.button != 1:
            return False
        estado["drag"] = None
        return True

    base = Gtk.EventBox()
    base.add(columnas)
    base.add_events(
        Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.BUTTON1_MOTION_MASK
    )
    base.connect("button-press-event", on_press)
    base.connect("motion-notify-event", on_motion)
    base.connect("button-release-event", on_release)
    body.pack_start(base, True, True, 0)
    scroller.add(body)
    outer.pack_start(scroller, True, True, 0)

    fila_ancla = max(0, fila_ahora - 2) if hoy_visible else 2  # 08:00 si hoy no está en la vista
    ancla = slots[(0, min(fila_ancla, TIMELINE_FILAS - 1))]

    def scroll_to_ancla():
        coordenadas = ancla.translate_coordinates(body, 0, 0)
        if coordenadas is None:
            return
        ajuste = scroller.get_vadjustment()
        ajuste.set_value(max(0, min(coordenadas[1], ajuste.get_upper() - ajuste.get_page_size())))

    outer.show_all()
    def tick():
        estado["ahora"] = datetime.now()
        for slot in slots_hoy:
            slot.queue_draw()

    return CalendarView(outer, scroll_to_ancla, tick)


def build_day_view(meetings: list, dia, ahora: datetime, callbacks) -> CalendarView:
    return _construir_timeline([dia], meetings, ahora, callbacks, con_cabecera=False)


def build_week_view(meetings: list, lunes, ahora: datetime, callbacks) -> CalendarView:
    return _construir_timeline(
        [lunes + timedelta(days=i) for i in range(7)], meetings, ahora, callbacks, con_cabecera=True
    )


def build_month_view(meetings: list, year: int, month: int, ahora: datetime, callbacks) -> CalendarView:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

    cabeceras = Gtk.Grid(column_homogeneous=True, column_spacing=4)
    for indice, codigo in enumerate(DIAS_SEMANA):
        etiqueta = Gtk.Label(label=NOMBRES_DIA_CORTO[codigo])
        etiqueta.get_style_context().add_class("dim-label")
        cabeceras.attach(etiqueta, indice, 0, 1, 1)
    outer.pack_start(cabeceras, False, False, 4)

    grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True, column_spacing=4, row_spacing=4)
    primer_dia_mes = date(year, month, 1)
    primer_lunes = primer_dia_mes - timedelta(days=primer_dia_mes.weekday())

    for semana in range(6):
        for indice_dia_semana in range(7):
            dia = primer_lunes + timedelta(days=semana * 7 + indice_dia_semana)
            clases = ["month-cell"]
            if dia.month != month:
                clases.append("month-cell-off")
            if dia == ahora.date():
                clases.append("month-cell-today")
            celda = Gtk.EventBox()
            _estilo(celda, *clases)
            celda.connect(
                "button-press-event",
                lambda w, e, d=dia: e.button == 3
                and (callbacks.on_empty(hora_por_defecto_en_dia(d, ahora), None, w, None) or True),
            )
            contenido = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            contenido.set_border_width(3)
            celda.add(contenido)

            numero = Gtk.Label(xalign=0)
            numero.set_margin_start(3)
            numero.set_markup(f"<b>{dia.day}</b>" if dia == ahora.date() else str(dia.day))
            if dia.month != month:
                numero.get_style_context().add_class("dim-label")
            contenido.pack_start(numero, False, False, 0)

            inicio_dia = datetime.combine(dia, datetime.min.time())
            fin_dia = inicio_dia + timedelta(days=1)
            ocurrencias = sorted(
                (
                    (ocurrencia, meeting)
                    for meeting in meetings
                    for ocurrencia in ocurrencias_visibles(meeting, inicio_dia, fin_dia)
                ),
                key=lambda par: par[0],
            )
            visibles, ocultas = pastillas_visibles(len(ocurrencias))
            for ocurrencia, meeting in ocurrencias[:visibles]:
                boton = Gtk.Button(label=f"{ocurrencia.strftime('%H:%M')} {meeting['titulo']}")
                boton.set_hexpand(True)
                boton.set_halign(Gtk.Align.FILL)
                etiqueta = boton.get_child()
                etiqueta.set_xalign(0)
                etiqueta.set_ellipsize(Pango.EllipsizeMode.END)
                etiqueta.set_line_wrap(False)
                _estilo(boton, "meeting-pill", *(("meeting-off",) if estado_ocurrencia(meeting, ocurrencia) == "inactiva" else ()))
                boton.set_tooltip_text(tooltip_reunion(meeting, ocurrencia))
                boton.connect("button-press-event", _clic_derecho(lambda b, m=meeting, o=ocurrencia: callbacks.on_meeting(m, o, b)))
                contenido.pack_start(boton, False, False, 0)
            if ocultas:
                mas = Gtk.Button(label=f"+{ocultas} más")
                mas.set_relief(Gtk.ReliefStyle.NONE)
                mas.get_child().set_xalign(0)
                _estilo(mas, "more-link")
                mas.set_tooltip_text("Ver el día completo")
                mas.connect("clicked", lambda _b, d=dia: callbacks.on_day(d))
                contenido.pack_start(mas, False, False, 0)

            grid.attach(celda, indice_dia_semana, semana, 1, 1)

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.add(grid)
    outer.pack_start(scroller, True, True, 0)
    outer.show_all()
    return CalendarView(outer)
