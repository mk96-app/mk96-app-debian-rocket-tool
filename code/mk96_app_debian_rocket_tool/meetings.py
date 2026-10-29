"""Calendario local de reuniones: modelo de datos y lógica pura de recurrencia/avisos.

Funciones puras (sin GLib/GTK/I-O), testeables directamente -mismo patrón que
rules.py/poller.py. La orquestación con efectos (temporizador, sonido, notificación)
vive en meeting_scheduler.py.
"""

import math
import uuid
from datetime import date, datetime, timedelta

DIAS_SEMANA = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
NOMBRES_MES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
NOMBRES_DIA_SEMANA = {
    "lun": "lunes", "mar": "martes", "mie": "miércoles", "jue": "jueves",
    "vie": "viernes", "sab": "sábado", "dom": "domingo",
}
NOMBRES_DIA_CORTO = {
    "lun": "lun", "mar": "mar", "mie": "mié", "jue": "jue",
    "vie": "vie", "sab": "sáb", "dom": "dom",
}
FECHA_HORA_FORMAT = "%Y-%m-%dT%H:%M"
FECHA_FORMAT = "%Y-%m-%d"

# Sonido de la paleta empaquetada (ver sounds/default/LICENSES.md) usado cuando una
# reunión no tiene sonido_id propio.
DEFAULT_MEETING_SONIDO_ID = "interface-sounds/confirmation_001"

# Modos de repetición reconocidos. Un valor fuera de este conjunto (config.yaml es
# editable a mano) se degrada a "ninguna" en normalize_meeting.
REPETICION_MODOS = {"ninguna", "diaria", "semanal", "mensual"}

# Tope del bucle mensual: solo acota el salto de meses que no tienen ese día (p.ej.
# día 31 en feb/abr/jun/sep/nov). La búsqueda arranca ya en max(base, ahora), así que
# nunca hace falta recorrer años enteros.
MAX_MESES_BUSQUEDA = 12

TIMELINE_INICIO_HORA = 7
TIMELINE_FIN_HORA = 21
TIMELINE_FRANJA_MIN = 30
TIMELINE_FILAS = (TIMELINE_FIN_HORA - TIMELINE_INICIO_HORA) * 60 // TIMELINE_FRANJA_MIN

# Columnas de grid reservadas por día en las vistas Día/Semana para repartir reuniones
# solapadas -ver posicion_columna.
CARRILES_POR_DIA = 4


def _fecha_str(value) -> str | None:
    """PyYAML auto-convierte escalares con pinta de fecha ('2026-12-31') a
    datetime.date al cargar el YAML -esto normaliza cualquiera de las dos formas
    a un str 'YYYY-MM-DD', para que el resto del código nunca tenga que
    distinguir entre las dos representaciones."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime(FECHA_FORMAT)
    return value


def _repeticion_modo(value) -> str:
    """config.yaml se edita a mano: un modo con una errata no debe tumbar el
    planificador, así que se degrada silenciosamente a "ninguna"."""
    return value if value in REPETICION_MODOS else "ninguna"


# Estados de una ocurrencia suelta de una serie (ver meeting["excepciones"]): "borrada"
# desaparece del calendario y no avisa; "inactiva" se sigue viendo (atenuada) pero no avisa.
ESTADOS_EXCEPCION = {"borrada", "inactiva"}


def _excepciones(value) -> dict:
    """{"YYYY-MM-DDTHH:MM": "borrada"|"inactiva"}. config.yaml es editable a mano: se
    descarta lo que no encaje en vez de fallar al cargar."""
    if not isinstance(value, dict):
        return {}
    resultado = {}
    for clave, estado in value.items():
        try:
            datetime.strptime(str(clave), FECHA_HORA_FORMAT)
        except ValueError:
            continue
        if estado in ESTADOS_EXCEPCION:
            resultado[str(clave)] = estado
    return resultado


def normalize_meeting(raw: dict) -> dict:
    """Rellena los campos opcionales de una reunión con sus valores por defecto,
    igual que normalize_rule en config.py."""
    return {
        "id": raw.get("id") or str(uuid.uuid4()),
        "titulo": raw["titulo"],
        "fecha_hora": raw["fecha_hora"],
        "repeticion_modo": _repeticion_modo(raw.get("repeticion_modo", "ninguna")),
        "repeticion_dias": raw.get("repeticion_dias") or [],
        "repeticion_fin": _fecha_str(raw.get("repeticion_fin")),
        "aviso_antes_min": raw.get("aviso_antes_min", 0),
        "enlace": raw.get("enlace"),
        "notas": raw.get("notas", ""),
        "sonido_id": raw.get("sonido_id"),
        "activa": raw.get("activa", True),
        "duracion_min": raw.get("duracion_min", 30),
        "excepciones": _excepciones(raw.get("excepciones")),
    }


def _format_partial_grouped_digits(digits: str, group_sizes: list, separator: str) -> str:
    """Reagrupa `digits` (solo dígitos, ya truncados a la suma de group_sizes) insertando
    `separator` en cuanto se completa cada grupo -así el campo de la UI muestra el
    separador nada más terminar de teclear cada bloque, sin esperar al siguiente dígito."""
    partes = []
    resto = digits
    for tamano in group_sizes:
        partes.append(resto[:tamano])
        resto = resto[tamano:]

    resultado = ""
    for i, parte in enumerate(partes):
        if parte == "":
            break
        resultado += parte
        es_ultimo_grupo = i == len(group_sizes) - 1
        if not es_ultimo_grupo and len(parte) == group_sizes[i]:
            resultado += separator
    return resultado


def format_partial_date_digits(digits: str) -> str:
    """Formatea, mientras se teclea, hasta 8 dígitos como fecha parcial 'DD/MM/AAAA'."""
    return _format_partial_grouped_digits(digits[:8], [2, 2, 4], "/")


def format_partial_time_digits(digits: str) -> str:
    """Formatea, mientras se teclea, hasta 4 dígitos como hora parcial 'HH:MM'."""
    return _format_partial_grouped_digits(digits[:4], [2, 2], ":")


def parse_ddmmyyyy(text: str) -> str | None:
    """Convierte una fecha completa 'DD/MM/AAAA' a la representación interna
    'AAAA-MM-DD', o `None` si `text` no es una fecha real en ese formato."""
    try:
        return datetime.strptime(text, "%d/%m/%Y").strftime(FECHA_FORMAT)
    except ValueError:
        return None


def parse_hhmm(text: str) -> str | None:
    """Normaliza una hora completa 'HH:MM' (24h), o `None` si no es válida."""
    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def round_up_to_next_half_hour(momento: datetime) -> datetime:
    """Siguiente marca de :00/:30 tras `momento` -avanza siempre, aunque `momento` ya
    caiga justo en una de esas marcas (10:30:00 en punto pasa a 11:00)."""
    base = momento.replace(minute=0, second=0, microsecond=0)
    bloques = momento.minute // 30 + 1
    return base + timedelta(minutes=bloques * 30)


def occurrences_in_range(meeting: dict, start: datetime, end: datetime) -> list:
    """Todas las ocurrencias de `meeting` en [start, end), respetando
    repeticion_modo/repeticion_dias/repeticion_fin/activa -reutiliza next_occurrence
    avanzando un cursor, sin duplicar la lógica de recurrencia."""
    resultado = []
    cursor = start
    while True:
        ocurrencia = next_occurrence(meeting, cursor)
        if ocurrencia is None or ocurrencia >= end:
            break
        resultado.append(ocurrencia)
        cursor = ocurrencia + timedelta(minutes=1)
    return resultado


def assign_lanes(intervalos: list) -> list:
    """Por cada (inicio, fin, item) de `intervalos`, decide en qué carril dibujarlo
    para que los que se solapan en el tiempo queden uno al lado del otro en vez de
    superpuestos. Devuelve [(item, carril, total_carriles), ...] en el MISMO orden que
    `intervalos` -total_carriles es el máximo de carriles simultáneos dentro del grupo
    de solapes mutuamente conectados al que pertenece ese item (grupos sin relación
    entre sí, ej. una reunión sola por la mañana y dos solapadas por la tarde, no se
    contagian el ancho el uno al otro).

    Algoritmo: ordenar por inicio; recorrer en ese orden agrupando en un mismo
    "cluster" los intervalos conectados transitivamente por solape (usando el fin
    máximo visto hasta ahora en el cluster, técnica clásica de fusión de intervalos);
    dentro de cada cluster, asignar carriles con barrido voraz (cada intervalo va al
    primer carril ya libre para su hora de inicio, o abre uno nuevo)."""
    if not intervalos:
        return []

    orden = sorted(range(len(intervalos)), key=lambda i: intervalos[i][0])
    resultado = [None] * len(intervalos)

    def resolver_cluster(indices: list) -> None:
        carriles_fin = []
        asignacion = {}
        for i in indices:
            inicio, fin, _item = intervalos[i]
            carril = next(
                (c for c, fin_ocupado in enumerate(carriles_fin) if fin_ocupado <= inicio),
                None,
            )
            if carril is None:
                carril = len(carriles_fin)
                carriles_fin.append(fin)
            else:
                carriles_fin[carril] = fin
            asignacion[i] = carril
        total = len(carriles_fin)
        for i in indices:
            _inicio, _fin, item = intervalos[i]
            resultado[i] = (item, asignacion[i], total)

    cluster_indices = []
    cluster_fin_maximo = None
    for i in orden:
        inicio, fin, _item = intervalos[i]
        if cluster_fin_maximo is not None and inicio < cluster_fin_maximo:
            cluster_indices.append(i)
            cluster_fin_maximo = max(cluster_fin_maximo, fin)
        else:
            if cluster_indices:
                resolver_cluster(cluster_indices)
            cluster_indices = [i]
            cluster_fin_maximo = fin
    if cluster_indices:
        resolver_cluster(cluster_indices)

    return resultado


def week_bounds(dia: date) -> tuple:
    """(lunes, lunes + 7 días) de la semana que contiene `dia`."""
    lunes = dia - timedelta(days=dia.weekday())
    return lunes, lunes + timedelta(days=7)


def format_day_label(dia: date) -> str:
    nombre_dia = NOMBRES_DIA_SEMANA[DIAS_SEMANA[dia.weekday()]]
    return f"{nombre_dia}, {dia.day} de {NOMBRES_MES[dia.month - 1]} de {dia.year}"


def format_week_label(lunes: date) -> str:
    domingo = lunes + timedelta(days=6)
    if lunes.month == domingo.month:
        return f"{lunes.day} - {domingo.day} de {NOMBRES_MES[lunes.month - 1]} de {lunes.year}"
    mes_lunes = NOMBRES_MES[lunes.month - 1][:3]
    mes_domingo = NOMBRES_MES[domingo.month - 1][:3]
    if lunes.year == domingo.year:
        return f"{lunes.day} {mes_lunes} - {domingo.day} {mes_domingo} {lunes.year}"
    return f"{lunes.day} {mes_lunes} {lunes.year} - {domingo.day} {mes_domingo} {domingo.year}"


def format_month_label(year: int, month: int) -> str:
    return f"{NOMBRES_MES[month - 1]} de {year}"


def _parse_fecha_hora(fecha_hora: str) -> datetime:
    return datetime.strptime(fecha_hora, FECHA_HORA_FORMAT)


def _parse_fecha_fin(repeticion_fin: str | None):
    if repeticion_fin is None:
        return None
    return datetime.strptime(repeticion_fin, FECHA_FORMAT).date()


def _pasada_fecha_fin(candidate_date, repeticion_fin_date) -> bool:
    return repeticion_fin_date is not None and candidate_date > repeticion_fin_date


def next_occurrence(meeting: dict, ahora: datetime) -> datetime | None:
    """Próxima fecha/hora de la reunión en el instante `ahora` o posterior (>=),
    respetando repeticion_modo/repeticion_dias/repeticion_fin y saltando las
    ocurrencias sueltas de meeting["excepciones"]. `None` si la reunión está inactiva
    o la serie ya ha terminado.

    Es el único punto por el que pasan los avisos, la bandeja y el calendario
    (occurrences_in_range, due_meetings, startup_due_meetings), así que las excepciones
    solo se aplican aquí. El bucle termina siempre: cada vuelta salta una clave distinta
    y las excepciones son un conjunto finito."""
    excepciones = meeting.get("excepciones") or {}
    cursor = ahora
    while True:
        ocurrencia = _siguiente_sin_excepciones(meeting, cursor)
        if ocurrencia is None or ocurrencia.strftime(FECHA_HORA_FORMAT) not in excepciones:
            return ocurrencia
        cursor = ocurrencia + timedelta(minutes=1)


def _siguiente_sin_excepciones(meeting: dict, ahora: datetime) -> datetime | None:
    if not meeting.get("activa", True):
        return None

    base = _parse_fecha_hora(meeting["fecha_hora"])
    repeticion_fin_date = _parse_fecha_fin(meeting.get("repeticion_fin"))
    modo = meeting.get("repeticion_modo", "ninguna")

    if modo == "ninguna":
        return base if base >= ahora else None

    if modo == "diaria":
        start_date = max(base.date(), ahora.date())
        candidate = datetime.combine(start_date, base.time())
        if candidate < ahora:
            candidate += timedelta(days=1)
        if _pasada_fecha_fin(candidate.date(), repeticion_fin_date):
            return None
        return candidate

    if modo == "semanal":
        dias = meeting.get("repeticion_dias") or []
        start_date = max(base.date(), ahora.date())
        for offset in range(8):
            candidate_date = start_date + timedelta(days=offset)
            if DIAS_SEMANA[candidate_date.weekday()] not in dias:
                continue
            candidate = datetime.combine(candidate_date, base.time())
            if candidate < ahora:
                continue
            if _pasada_fecha_fin(candidate_date, repeticion_fin_date):
                return None
            return candidate
        return None

    if modo == "mensual":
        # Se arranca directamente en el mes de max(base, ahora): una reunión mensual
        # creada hace años sigue teniendo ocurrencias en el presente, y escanear mes a
        # mes desde base haría falta recorrer decenas de años para llegar hasta hoy.
        inicio = max(base, ahora)
        year, month = inicio.year, inicio.month
        for _ in range(MAX_MESES_BUSQUEDA):
            try:
                candidate_date = date(year, month, base.day)
            except ValueError:
                candidate_date = None  # ese mes no tiene ese día -se omite

            if candidate_date is not None:
                candidate = datetime.combine(candidate_date, base.time())
                if candidate >= base and candidate >= ahora:
                    if _pasada_fecha_fin(candidate_date, repeticion_fin_date):
                        return None
                    return candidate

            month += 1
            if month > 12:
                month = 1
                year += 1
        return None

    raise ValueError(f"repeticion_modo desconocido: {modo!r}")


def due_meetings(meetings: list, ahora: datetime, ultimo_chequeo: datetime) -> list:
    """Reuniones cuyo aviso previo y/o cuyo momento exacto caen en la ventana
    semiabierta (ultimo_chequeo, ahora] -evita duplicar el aviso entre ticks
    consecutivos del planificador. Cuando aviso_antes_min > 0 cada ocurrencia avisa
    DOS veces: una con antelación ("aviso") y otra en el momento exacto ("hora"); con
    aviso_antes_min == 0 ambos instantes coinciden y solo se dispara "hora". Devuelve
    [(meeting, ocurrencia, momento), ...]."""
    resultado = []
    for meeting in meetings:
        ocurrencia = next_occurrence(meeting, ultimo_chequeo)
        if ocurrencia is None:
            continue
        aviso_antes_min = meeting.get("aviso_antes_min", 0)
        momentos = []
        if aviso_antes_min > 0:
            momentos.append(("aviso", ocurrencia - timedelta(minutes=aviso_antes_min)))
        momentos.append(("hora", ocurrencia))
        for momento, instante in momentos:
            if ultimo_chequeo < instante <= ahora:
                resultado.append((meeting, ocurrencia, momento))
    return resultado


def startup_due_meetings(meetings: list, ahora: datetime) -> list:
    """Reuniones cuya ventana de aviso ya se había abierto antes de arrancar la app pero
    que todavía no han ocurrido: abrir el portátil a las 09:55 para una reunión de las
    10:00 con aviso_antes_min=10 debe avisar igualmente. En este punto la reunión
    todavía no ha ocurrido, así que el único instante que puede haberse perdido es el
    aviso previo (o el propio momento exacto, si aviso_antes_min es 0). Sin control de
    "ya disparado": está pensada para llamarse exactamente una vez, al arrancar el
    planificador. Devuelve [(meeting, ocurrencia, momento), ...]."""
    resultado = []
    for meeting in meetings:
        ocurrencia = next_occurrence(meeting, ahora)
        if ocurrencia is None or ocurrencia < ahora:
            continue
        aviso_antes_min = meeting.get("aviso_antes_min", 0)
        aviso_en = ocurrencia - timedelta(minutes=aviso_antes_min)
        if aviso_en <= ahora:
            momento = "aviso" if aviso_antes_min > 0 else "hora"
            resultado.append((meeting, ocurrencia, momento))
    return resultado


def fila_timeline(momento: datetime) -> tuple:
    """(fila, recortada) de `momento` dentro de la rejilla 07:00-21:00 en franjas de
    TIMELINE_FRANJA_MIN minutos. `fila` está siempre en [0, TIMELINE_FILAS];
    `recortada=True` si `momento` cae estrictamente fuera de esa ventana (se ancló al
    borde más cercano)."""
    inicio_dia = momento.replace(
        hour=TIMELINE_INICIO_HORA, minute=0, second=0, microsecond=0
    )
    fin_dia = momento.replace(hour=TIMELINE_FIN_HORA, minute=0, second=0, microsecond=0)
    if momento <= inicio_dia:
        return 0, momento < inicio_dia
    if momento >= fin_dia:
        return TIMELINE_FILAS, momento > fin_dia
    minutos = (momento - inicio_dia).total_seconds() / 60
    return int(minutos // TIMELINE_FRANJA_MIN), False


def filas_para_bloque(inicio: datetime, duracion_min: int) -> tuple:
    """Fila de inicio y número de filas que ocupa un bloque de reunión en el timeline:
    num_filas = ceil(duracion_min / TIMELINE_FRANJA_MIN) con mínimo 1, recortando el
    bloque a los bordes de la rejilla si empieza o acaba fuera de 07:00-21:00. Devuelve
    (fila_inicio, num_filas, recortada_arriba, recortada_abajo)."""
    fila_inicio, recortada_arriba = fila_timeline(inicio)
    if fila_inicio >= TIMELINE_FILAS:
        fila_inicio = TIMELINE_FILAS - 1
    filas_deseadas = max(1, math.ceil(duracion_min / TIMELINE_FRANJA_MIN))
    filas_disponibles = max(1, TIMELINE_FILAS - fila_inicio)
    num_filas = min(filas_deseadas, filas_disponibles)
    recortada_abajo = filas_deseadas > filas_disponibles
    return fila_inicio, num_filas, recortada_arriba, recortada_abajo


def posicion_columna(carril: int, total_carriles: int) -> tuple:
    """(columna_relativa, ancho_columnas) dentro de las CARRILES_POR_DIA columnas de
    grid reservadas para un día, a partir del (carril, total_carriles) que devuelve
    assign_lanes. Con más de CARRILES_POR_DIA reuniones solapadas a la vez (caso raro)
    se reparten en las mismas columnas y las últimas se solapan visualmente entre
    sí -degradación aceptada: no hay más carriles físicos que repartir."""
    total_para_ancho = min(total_carriles, CARRILES_POR_DIA)
    ancho = max(1, CARRILES_POR_DIA // total_para_ancho)
    columna = min(carril, CARRILES_POR_DIA - 1) * ancho
    return columna, ancho


def hora_por_defecto_en_dia(dia: date, ahora: datetime) -> datetime:
    """Fecha y hora con las que se propone una reunión nueva al hacer clic en un día
    sin hora concreta (vista Mes): la próxima media hora si es hoy, las 09:00 si no."""
    if dia == ahora.date():
        return round_up_to_next_half_hour(ahora)
    return datetime.combine(dia, datetime.min.time()).replace(hour=9)


# -- Ocurrencias sueltas dentro de una serie ------------------------------------------


def es_serie(meeting: dict) -> bool:
    return meeting.get("repeticion_modo", "ninguna") != "ninguna"


def estado_ocurrencia(meeting: dict, ocurrencia: datetime) -> str:
    """"activa" o "inactiva" para una ocurrencia concreta de `meeting`."""
    if not meeting.get("activa", True):
        return "inactiva"
    clave = ocurrencia.strftime(FECHA_HORA_FORMAT)
    return "inactiva" if (meeting.get("excepciones") or {}).get(clave) == "inactiva" else "activa"


def ocurrencias_visibles(meeting: dict, inicio: datetime, fin: datetime) -> list:
    """Ocurrencias a DIBUJAR en [inicio, fin): incluye las inactivas (atenuadas, para que
    se puedan reactivar) y excluye las borradas. occurrences_in_range, que usan los
    avisos, excluye ambas, así que aquí se le pasa una copia sin la parte "inactiva"."""
    excepciones = {k: v for k, v in (meeting.get("excepciones") or {}).items() if v == "borrada"}
    return occurrences_in_range({**meeting, "activa": True, "excepciones": excepciones}, inicio, fin)


def con_excepcion(meeting: dict, ocurrencia: datetime, estado: str | None) -> dict:
    """Copia de `meeting` con la ocurrencia marcada "borrada"/"inactiva", o sin marca si
    `estado` es None."""
    excepciones = dict(meeting.get("excepciones") or {})
    clave = ocurrencia.strftime(FECHA_HORA_FORMAT)
    if estado is None:
        excepciones.pop(clave, None)
    else:
        excepciones[clave] = estado
    return {**meeting, "excepciones": excepciones}


def reunion_editada(original: dict | None, nueva: dict) -> dict:
    """`nueva` (recién salida del formulario) con las excepciones de `original`, salvo que
    haya cambiado cuándo ocurre la serie -entonces las claves guardadas ya no
    corresponden a ocurrencias reales y se descartan."""
    if original is None:
        return nueva
    cambia_serie = any(
        original.get(campo) != nueva.get(campo)
        for campo in ("fecha_hora", "repeticion_modo", "repeticion_dias")
    )
    return {**nueva, "excepciones": {} if cambia_serie else dict(original.get("excepciones") or {})}


# -- Rejilla del calendario (Día/Semana) ------------------------------------------------


def franja_seleccion(dia: date, fila_a: int, fila_b: int) -> tuple:
    """(inicio, duracion_min) de las filas de la rejilla entre `fila_a` y `fila_b`, ambas
    incluidas y en cualquier orden."""
    primera, ultima = sorted((fila_a, fila_b))
    inicio = datetime.combine(dia, datetime.min.time()) + timedelta(
        hours=TIMELINE_INICIO_HORA, minutes=primera * TIMELINE_FRANJA_MIN
    )
    return inicio, (ultima - primera + 1) * TIMELINE_FRANJA_MIN


def posicion_ahora(ahora: datetime) -> tuple | None:
    """(fila, fraccion) de `ahora` en la rejilla: la fila que lo contiene y cuánto de esa
    fila ha transcurrido (0.0-1.0), para dibujar la marca al minuto. None si cae fuera
    de la ventana horaria."""
    minutos = (ahora.hour - TIMELINE_INICIO_HORA) * 60 + ahora.minute + ahora.second / 60
    if minutos < 0 or minutos >= TIMELINE_FILAS * TIMELINE_FRANJA_MIN:
        return None
    return int(minutos // TIMELINE_FRANJA_MIN), (minutos % TIMELINE_FRANJA_MIN) / TIMELINE_FRANJA_MIN


def format_duracion(minutos: int) -> str:
    """30 -> "30 min", 60 -> "1 h", 90 -> "1 h 30 min"."""
    horas, resto = divmod(minutos, 60)
    if horas == 0:
        return f"{resto} min"
    return f"{horas} h" if resto == 0 else f"{horas} h {resto} min"
