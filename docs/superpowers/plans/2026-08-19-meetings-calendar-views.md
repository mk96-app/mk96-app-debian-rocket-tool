# Vistas de calendario (Día/Semana/Mes) para reuniones — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir la lista "Reuniones guardadas" de `MeetingsWindow` por tres vistas de
calendario navegables (Día/Semana/Mes) con timeline por horas, añadiendo una duración a
cada reunión.

**Architecture:** Toda la lógica de fechas/solapes/formato de etiquetas vive como
funciones puras nuevas en `meetings.py` (testeadas con pytest, sin GTK). Un módulo GTK
nuevo, `meetings_calendar.py`, traduce esas funciones puras a `Gtk.Grid`/`Gtk.Box` para
las tres vistas. `meetings_window.py` orquesta: guarda qué vista y qué periodo se está
mirando, dibuja el selector y la barra de navegación, y delega la construcción del
contenido en `meetings_calendar.py`.

**Tech Stack:** Python 3.10+, GTK3 (PyGObject), pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-19-meetings-calendar-views-design.md`

## Global Constraints

- Python 3.10+ (usa `str | None` en anotaciones, como el resto del código).
- Comentarios y textos de UI en español, mismo tono que el resto del proyecto.
- Lógica pura (fechas, solapes, formato) siempre en `meetings.py`, sin `gi`/GTK — mismo
  patrón que `next_occurrence`/`due_meetings`. El cableado GTK no lleva tests
  automáticos (ya es así para el resto de `meetings_window.py`); se verifica a mano con
  Xvfb + eventos simulados, como se hizo con el autoformateo y el calendario emergente.
- Rango de timeline fijo 07:00-21:00, franjas de 30 min (`TIMELINE_FRANJA_MIN`).
- `duracion_min` por defecto 30 (reuniones ya guardadas sin ese campo lo reciben al
  normalizar).
- Sin nombres de mes/día dependientes del locale del sistema — tablas propias en
  `meetings.py` (`NOMBRES_MES`, `NOMBRES_DIA_SEMANA`, `NOMBRES_DIA_CORTO`).
- Para las tres vistas nuevas (Día/Semana/Mes) no usar `Gtk.Calendar`, `Gtk.Stack` ni
  dibujo Cairo a mano — todo sobre `Gtk.Grid`/`Gtk.Box` con widgets normales (botones,
  etiquetas), como ya se decidió en el spec. Esto no afecta al `Gtk.Calendar` que ya
  usa el selector de fecha emergente del formulario (`_build_calendar_button`), que no
  se toca en este plan.

---

## Task 1: Campo `duracion_min` en el modelo de reunión

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings.py:47-62` (`normalize_meeting`)
- Test: `code/tests/test_meetings_logic.py`

**Interfaces:**
- Produces: `normalize_meeting(raw: dict) -> dict` ahora incluye la clave
  `"duracion_min": int` (por defecto `30` si `raw` no la trae).

- [ ] **Step 1: Write the failing tests**

Añadir en `code/tests/test_meetings_logic.py`, junto a
`test_normalize_meeting_defaults`/`test_normalize_meeting_keeps_explicit_values`:

```python
def test_normalize_meeting_defaults_duracion_to_30_minutes():
    meeting = normalize_meeting({"titulo": "Sync", "fecha_hora": "2026-08-20T10:00"})
    assert meeting["duracion_min"] == 30


def test_normalize_meeting_keeps_explicit_duracion():
    meeting = normalize_meeting(
        {"titulo": "Sync", "fecha_hora": "2026-08-20T10:00", "duracion_min": 90}
    )
    assert meeting["duracion_min"] == 90
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k duracion -v`
Expected: `FAIL` — `KeyError: 'duracion_min'`.

- [ ] **Step 3: Implement**

En `code/mk96_app_debian_rocket_tool/meetings.py`, dentro de `normalize_meeting`, añadir la
clave al dict devuelto (junto a `"activa"`):

```python
        "activa": raw.get("activa", True),
        "duracion_min": raw.get("duracion_min", 30),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k duracion -v`
Expected: `PASS` (2 tests).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd code && python3 -m pytest tests/ -q`
Expected: todos los tests pasan (ninguno debería romperse por este cambio).

```bash
git add code/mk96_app_debian_rocket_tool/meetings.py code/tests/test_meetings_logic.py
git commit -m "feat: add duracion_min field to meetings, default 30 minutes"
```

---

## Task 2: `occurrences_in_range`

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings.py` (añadir tras `round_up_to_next_half_hour`, antes de `_parse_fecha_hora`)
- Test: `code/tests/test_meetings_logic.py`

**Interfaces:**
- Consumes: `next_occurrence(meeting: dict, ahora: datetime) -> datetime | None` (ya existe).
- Produces: `occurrences_in_range(meeting: dict, start: datetime, end: datetime) -> list[datetime]`
  — todas las ocurrencias de `meeting` en `[start, end)`, ordenadas ascendente.

- [ ] **Step 1: Write the failing tests**

Añadir en `code/tests/test_meetings_logic.py` (import `occurrences_in_range` junto a
los demás nombres de `mk96_app_debian_rocket_tool.meetings` en el bloque `from ... import`):

```python
def test_occurrences_in_range_single_meeting_inside_range():
    meeting = _meeting(fecha_hora="2026-08-20T10:00")
    ocurrencias = occurrences_in_range(
        meeting, datetime(2026, 8, 20, 0, 0), datetime(2026, 8, 21, 0, 0)
    )
    assert ocurrencias == [datetime(2026, 8, 20, 10, 0)]


def test_occurrences_in_range_excludes_occurrence_before_start():
    meeting = _meeting(fecha_hora="2026-08-19T10:00")
    ocurrencias = occurrences_in_range(
        meeting, datetime(2026, 8, 20, 0, 0), datetime(2026, 8, 21, 0, 0)
    )
    assert ocurrencias == []


def test_occurrences_in_range_excludes_occurrence_at_or_after_end():
    meeting = _meeting(fecha_hora="2026-08-21T10:00")
    ocurrencias = occurrences_in_range(
        meeting, datetime(2026, 8, 20, 0, 0), datetime(2026, 8, 21, 0, 0)
    )
    assert ocurrencias == []


def test_occurrences_in_range_weekly_returns_every_matching_day():
    meeting = _meeting(
        fecha_hora="2026-08-17T09:00",  # lunes
        repeticion_modo="semanal",
        repeticion_dias=["lun", "jue"],
    )
    ocurrencias = occurrences_in_range(
        meeting, datetime(2026, 8, 17, 0, 0), datetime(2026, 8, 24, 0, 0)
    )
    assert ocurrencias == [datetime(2026, 8, 17, 9, 0), datetime(2026, 8, 20, 9, 0)]


def test_occurrences_in_range_monthly_skips_month_without_that_day():
    meeting = _meeting(fecha_hora="2026-01-31T09:00", repeticion_modo="mensual")
    ocurrencias = occurrences_in_range(
        meeting, datetime(2026, 1, 1, 0, 0), datetime(2026, 4, 1, 0, 0)
    )
    # Enero (31) y marzo (31) tienen día 31; febrero no -se omite, no se recorta.
    assert ocurrencias == [datetime(2026, 1, 31, 9, 0), datetime(2026, 3, 31, 9, 0)]


def test_occurrences_in_range_inactive_meeting_returns_empty():
    meeting = _meeting(fecha_hora="2026-08-20T10:00", activa=False)
    ocurrencias = occurrences_in_range(
        meeting, datetime(2026, 8, 20, 0, 0), datetime(2026, 8, 21, 0, 0)
    )
    assert ocurrencias == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k occurrences_in_range -v`
Expected: `FAIL` — `ImportError: cannot import name 'occurrences_in_range'`.

- [ ] **Step 3: Implement**

En `code/mk96_app_debian_rocket_tool/meetings.py`, justo después de
`round_up_to_next_half_hour`:

```python
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
```

`next_occurrence` está definida más abajo en el mismo archivo; en Python esto no es un
problema porque `occurrences_in_range` solo la resuelve cuando se *llama*, no cuando se
*define* -pero si se prefiere mantener el orden de lectura "de arriba abajo", esta
función puede colocarse igualmente después de `next_occurrence` (línea ~198) en vez de
antes. Cualquiera de las dos posiciones es correcta.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k occurrences_in_range -v`
Expected: `PASS` (6 tests).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd code && python3 -m pytest tests/ -q`

```bash
git add code/mk96_app_debian_rocket_tool/meetings.py code/tests/test_meetings_logic.py
git commit -m "feat: add occurrences_in_range for calendar views"
```

---

## Task 3: `assign_lanes`

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings.py`
- Test: `code/tests/test_meetings_logic.py`

**Interfaces:**
- Produces: `assign_lanes(intervalos: list[tuple[datetime, datetime, object]]) -> list[tuple[object, int, int]]`
  — por cada `(inicio, fin, item)` de entrada, devuelve `(item, carril, total_carriles)`
  en el **mismo orden** que la lista de entrada. `total_carriles` es el máximo de
  carriles simultáneos dentro del grupo de intervalos mutuamente solapados al que
  pertenece ese `item` (no un total global de todo el día).

- [ ] **Step 1: Write the failing tests**

Añadir en `code/tests/test_meetings_logic.py` (import `assign_lanes` en el bloque de
imports):

```python
def test_assign_lanes_no_overlap_all_get_lane_zero_of_one():
    intervalos = [
        (datetime(2026, 8, 20, 9, 0), datetime(2026, 8, 20, 9, 30), "a"),
        (datetime(2026, 8, 20, 10, 0), datetime(2026, 8, 20, 10, 30), "b"),
    ]
    assert assign_lanes(intervalos) == [("a", 0, 1), ("b", 0, 1)]


def test_assign_lanes_two_overlapping_get_separate_lanes():
    intervalos = [
        (datetime(2026, 8, 20, 9, 0), datetime(2026, 8, 20, 10, 0), "a"),
        (datetime(2026, 8, 20, 9, 30), datetime(2026, 8, 20, 10, 30), "b"),
    ]
    assert assign_lanes(intervalos) == [("a", 0, 2), ("b", 1, 2)]


def test_assign_lanes_three_mutually_overlapping_need_three_lanes():
    intervalos = [
        (datetime(2026, 8, 20, 10, 0), datetime(2026, 8, 20, 11, 0), "a"),
        (datetime(2026, 8, 20, 10, 15), datetime(2026, 8, 20, 10, 45), "b"),
        (datetime(2026, 8, 20, 10, 20), datetime(2026, 8, 20, 10, 40), "c"),
    ]
    resultado = assign_lanes(intervalos)
    assert [r[2] for r in resultado] == [3, 3, 3]
    assert {r[1] for r in resultado} == {0, 1, 2}  # tres carriles distintos


def test_assign_lanes_chain_overlap_reuses_lane_when_max_concurrency_is_two():
    # a y b se solapan, b y c se solapan, pero a y c NO se solapan entre sí -en
    # ningún instante coinciden las tres a la vez, así que solo hacen falta 2 carriles
    # (no 3), aunque las tres estén "conectadas" en cadena.
    intervalos = [
        (datetime(2026, 8, 20, 10, 0), datetime(2026, 8, 20, 11, 0), "a"),
        (datetime(2026, 8, 20, 10, 30), datetime(2026, 8, 20, 11, 30), "b"),
        (datetime(2026, 8, 20, 11, 15), datetime(2026, 8, 20, 12, 0), "c"),
    ]
    resultado = assign_lanes(intervalos)
    assert [r[2] for r in resultado] == [2, 2, 2]


def test_assign_lanes_separate_groups_have_independent_lane_counts():
    intervalos = [
        (datetime(2026, 8, 20, 9, 0), datetime(2026, 8, 20, 9, 30), "solo"),
        (datetime(2026, 8, 20, 10, 0), datetime(2026, 8, 20, 11, 0), "a"),
        (datetime(2026, 8, 20, 10, 15), datetime(2026, 8, 20, 10, 45), "b"),
    ]
    resultado = assign_lanes(intervalos)
    por_item = {item: (carril, total) for item, carril, total in resultado}
    assert por_item["solo"] == (0, 1)
    assert por_item["a"][1] == 2
    assert por_item["b"][1] == 2


def test_assign_lanes_empty_list():
    assert assign_lanes([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k assign_lanes -v`
Expected: `FAIL` — `ImportError: cannot import name 'assign_lanes'`.

- [ ] **Step 3: Implement**

En `code/mk96_app_debian_rocket_tool/meetings.py`, después de `occurrences_in_range`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k assign_lanes -v`
Expected: `PASS` (6 tests).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd code && python3 -m pytest tests/ -q`

```bash
git add code/mk96_app_debian_rocket_tool/meetings.py code/tests/test_meetings_logic.py
git commit -m "feat: add assign_lanes for overlapping meeting layout"
```

---

## Task 4: Etiquetas de periodo (`week_bounds`, `format_day_label`, `format_week_label`, `format_month_label`)

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings.py`
- Test: `code/tests/test_meetings_logic.py`

**Interfaces:**
- Produces:
  - `NOMBRES_MES: list[str]` (12 nombres, minúscula, índice = mes-1)
  - `NOMBRES_DIA_SEMANA: dict[str, str]` (código de `DIAS_SEMANA` -> nombre completo)
  - `NOMBRES_DIA_CORTO: dict[str, str]` (código de `DIAS_SEMANA` -> abreviatura de 3 letras)
  - `week_bounds(dia: date) -> tuple[date, date]` — `(lunes, lunes + 7 días)` de la
    semana que contiene `dia`.
  - `format_day_label(dia: date) -> str`
  - `format_week_label(lunes: date) -> str`
  - `format_month_label(year: int, month: int) -> str`

- [ ] **Step 1: Write the failing tests**

Añadir en `code/tests/test_meetings_logic.py` (import los 4 nombres de función nuevos):

```python
def test_week_bounds_returns_monday_and_next_monday():
    lunes, siguiente_lunes = week_bounds(date(2024, 1, 3))  # miércoles
    assert lunes == date(2024, 1, 1)
    assert siguiente_lunes == date(2024, 1, 8)


def test_format_day_label():
    assert format_day_label(date(2024, 1, 1)) == "lunes, 1 de enero de 2024"


def test_format_week_label_same_month():
    assert format_week_label(date(2024, 1, 1)) == "1 - 7 de enero de 2024"


def test_format_week_label_crossing_month():
    assert format_week_label(date(2024, 1, 29)) == "29 ene - 4 feb 2024"


def test_format_week_label_crossing_year():
    assert format_week_label(date(2024, 12, 30)) == "30 dic 2024 - 5 ene 2025"


def test_format_month_label():
    assert format_month_label(2026, 8) == "agosto de 2026"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k "week_bounds or format_day_label or format_week_label or format_month_label" -v`
Expected: `FAIL` — `ImportError`.

- [ ] **Step 3: Implement**

En `code/mk96_app_debian_rocket_tool/meetings.py`, añadir las tablas junto a `DIAS_SEMANA`
(cerca del principio del archivo):

```python
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
```

Y las funciones, después de `assign_lanes`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k "week_bounds or format_day_label or format_week_label or format_month_label" -v`
Expected: `PASS` (6 tests).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd code && python3 -m pytest tests/ -q`

```bash
git add code/mk96_app_debian_rocket_tool/meetings.py code/tests/test_meetings_logic.py
git commit -m "feat: add day/week/month label formatters, no locale dependency"
```

---

## Task 5: Aritmética de la rejilla del timeline

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings.py`
- Test: `code/tests/test_meetings_logic.py`

**Interfaces:**
- Produces:
  - `TIMELINE_INICIO_HORA = 7`, `TIMELINE_FIN_HORA = 21`, `TIMELINE_FRANJA_MIN = 30`,
    `TIMELINE_FILAS = 28` (constantes de módulo)
  - `CARRILES_POR_DIA = 4` (constante de módulo)
  - `fila_timeline(momento: datetime) -> tuple[int, bool]` — `(fila, recortada)`;
    `fila` en `[0, TIMELINE_FILAS]`, `recortada=True` si `momento` cae fuera de
    `07:00-21:00`.
  - `filas_para_bloque(inicio: datetime, duracion_min: int) -> tuple[int, int, bool, bool]`
    — `(fila_inicio, num_filas, recortada_arriba, recortada_abajo)`.
  - `posicion_columna(carril: int, total_carriles: int) -> tuple[int, int]` —
    `(columna_relativa, ancho_columnas)` dentro de las `CARRILES_POR_DIA` columnas de
    grid reservadas para un día.

- [ ] **Step 1: Write the failing tests**

Añadir en `code/tests/test_meetings_logic.py` (import los 3 nombres de función + las
constantes usadas por los tests):

```python
def test_fila_timeline_at_window_start():
    assert fila_timeline(datetime(2026, 8, 20, 7, 0)) == (0, False)


def test_fila_timeline_before_window_is_clipped_to_zero():
    assert fila_timeline(datetime(2026, 8, 20, 6, 0)) == (0, True)


def test_fila_timeline_after_window_is_clipped_to_last_row():
    assert fila_timeline(datetime(2026, 8, 20, 22, 0)) == (TIMELINE_FILAS, True)


def test_fila_timeline_at_window_end_is_not_clipped():
    assert fila_timeline(datetime(2026, 8, 20, 21, 0)) == (TIMELINE_FILAS, False)


def test_fila_timeline_mid_slot_floors_to_slot_start():
    assert fila_timeline(datetime(2026, 8, 20, 10, 17)) == (6, False)


def test_filas_para_bloque_within_window():
    assert filas_para_bloque(datetime(2026, 8, 20, 10, 0), 45) == (6, 2, False, False)


def test_filas_para_bloque_clipped_at_bottom_of_window():
    assert filas_para_bloque(datetime(2026, 8, 20, 20, 30), 60) == (27, 1, False, True)


def test_filas_para_bloque_starting_after_window_anchors_to_last_row():
    assert filas_para_bloque(datetime(2026, 8, 20, 22, 0), 30) == (27, 1, True, False)


def test_posicion_columna_single_meeting_spans_full_width():
    assert posicion_columna(0, 1) == (0, 4)


def test_posicion_columna_two_overlapping_split_in_half():
    assert posicion_columna(0, 2) == (0, 2)
    assert posicion_columna(1, 2) == (2, 2)


def test_posicion_columna_three_overlapping():
    assert posicion_columna(0, 3) == (0, 1)
    assert posicion_columna(2, 3) == (2, 1)


def test_posicion_columna_beyond_carriles_por_dia_degrades_by_reusing_columns():
    assert posicion_columna(0, 5) == (0, 1)
    assert posicion_columna(4, 5) == (3, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k "fila_timeline or filas_para_bloque or posicion_columna" -v`
Expected: `FAIL` — `ImportError`.

- [ ] **Step 3: Implement**

En `code/mk96_app_debian_rocket_tool/meetings.py`, añadir las constantes junto a
`MAX_MESES_BUSQUEDA`:

```python
TIMELINE_INICIO_HORA = 7
TIMELINE_FIN_HORA = 21
TIMELINE_FRANJA_MIN = 30
TIMELINE_FILAS = (TIMELINE_FIN_HORA - TIMELINE_INICIO_HORA) * 60 // TIMELINE_FRANJA_MIN

# Columnas de grid reservadas por día en las vistas Día/Semana para repartir reuniones
# solapadas -ver posicion_columna.
CARRILES_POR_DIA = 4
```

Y añadir `import math` al principio del archivo (junto a `import uuid`). Después,
añadir las tres funciones al final del archivo:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd code && python3 -m pytest tests/test_meetings_logic.py -k "fila_timeline or filas_para_bloque or posicion_columna" -v`
Expected: `PASS` (12 tests).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd code && python3 -m pytest tests/ -q`

```bash
git add code/mk96_app_debian_rocket_tool/meetings.py code/tests/test_meetings_logic.py
git commit -m "feat: add timeline grid arithmetic for day/week calendar views"
```

---

## Task 6: Formulario — Duración, Borrar y Abrir enlace

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings_window.py:75-192` (`_build_form`),
  `:389-432` (`_load_meeting_into_form`, `_clear_form`), `:461-515` (`_save_meeting`)

**Interfaces:**
- Consumes: `open_url(url: str) -> None` (ya importado de `gtk_helpers`).
- Produces: `self._duracion_spin: Gtk.SpinButton`, `self._borrar_button: Gtk.Button`
  (para que Task 10 no necesite tocar `_build_form` de nuevo).

Este task no tiene tests automáticos (widgets GTK) — se verifica a mano con Xvfb.

- [ ] **Step 1: Añadir el SpinButton de Duración**

En `_build_form`, justo después del bloque de Fecha/Hora (después de la línea
`grid.attach(self._hora_entry, 3, row, 1, 1)` y antes de `row += 1` /
`"Repetición:"`), insertar:

```python
        row += 1
        grid.attach(Gtk.Label(label="Duración (min):", xalign=0), 0, row, 1, 1)
        self._duracion_spin = Gtk.SpinButton.new_with_range(5, 480, 5)
        self._duracion_spin.set_value(30)
        grid.attach(self._duracion_spin, 1, row, 1, 1)
```

- [ ] **Step 2: Añadir el botón "Abrir" junto al campo Enlace**

En `_build_form`, sustituir el bloque actual del Enlace:

```python
        row += 1
        grid.attach(Gtk.Label(label="Enlace (opcional):", xalign=0), 0, row, 1, 1)
        self._enlace_entry = Gtk.Entry()
        self._enlace_entry.set_placeholder_text("https://...")
        self._enlace_entry.set_hexpand(True)
        grid.attach(self._enlace_entry, 1, row, 3, 1)
```

por:

```python
        row += 1
        grid.attach(Gtk.Label(label="Enlace (opcional):", xalign=0), 0, row, 1, 1)
        self._enlace_entry = Gtk.Entry()
        self._enlace_entry.set_placeholder_text("https://...")
        self._enlace_entry.set_hexpand(True)
        grid.attach(self._enlace_entry, 1, row, 2, 1)
        abrir_enlace_button = Gtk.Button(label="Abrir")
        abrir_enlace_button.connect("clicked", lambda _b: self._abrir_enlace_actual())
        grid.attach(abrir_enlace_button, 3, row, 1, 1)
```

- [ ] **Step 3: Añadir el botón "Borrar"**

En `_build_form`, en el `buttons_box` (junto a `save_button`/`clear_button`), añadir:

```python
        self._borrar_button = Gtk.Button(label="Borrar")
        self._borrar_button.set_sensitive(False)
        self._borrar_button.connect("clicked", lambda _b: self._delete_current_meeting())
        buttons_box.pack_start(self._borrar_button, False, False, 0)
```

(justo después de `buttons_box.pack_start(clear_button, False, False, 0)`, antes de
`grid.attach(buttons_box, 2, row, 2, 1)`).

- [ ] **Step 4: Nuevos métodos `_abrir_enlace_actual`, `_delete_current_meeting`, `_actualizar_estado_borrar`**

Añadir estos tres métodos a la clase, cerca de `_remove_meeting`:

```python
    def _abrir_enlace_actual(self) -> None:
        enlace = self._enlace_entry.get_text().strip()
        if enlace:
            open_url(enlace)

    def _delete_current_meeting(self) -> None:
        if self._editing_id is None:
            return
        self._remove_meeting(self._editing_id)
        self._clear_form()

    def _actualizar_estado_borrar(self) -> None:
        self._borrar_button.set_sensitive(self._editing_id is not None)
```

- [ ] **Step 5: Cablear Duración y el estado de Borrar en carga/limpieza del formulario**

En `_load_meeting_into_form`, añadir tras `self._hora_entry.set_formatted_value(hora)`:

```python
        self._duracion_spin.set_value(meeting["duracion_min"])
```

Y al final del método (después de `self._update_repeticion_visibility()`):

```python
        self._actualizar_estado_borrar()
```

En `_clear_form`, añadir tras la línea de `self._hora_entry.set_formatted_value(...)`:

```python
        self._duracion_spin.set_value(30)
```

Y al final del método (después de `self._update_repeticion_visibility()`):

```python
        self._actualizar_estado_borrar()
```

- [ ] **Step 6: Guardar `duracion_min` en `_save_meeting`**

En `_save_meeting`, en el dict que se pasa a `normalize_meeting`, añadir junto a
`"activa": self._activa_check.get_active(),`:

```python
                "duracion_min": int(self._duracion_spin.get_value()),
```

- [ ] **Step 7: Verificar a mano con Xvfb**

Run (asume que ya hay un `Xvfb :99` corriendo; si no, arrancarlo con
`Xvfb :99 -screen 0 1280x800x24 & disown`):

```bash
cd code
DISPLAY=:99 GDK_BACKEND=x11 python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.init(None)

from mk96_app_debian_rocket_tool.meetings_window import MeetingsWindow

win = MeetingsWindow({'reuniones': []}, lambda cfg: None)
while Gtk.events_pending():
    Gtk.main_iteration()

print('duracion inicial:', win._duracion_spin.get_value())
assert win._duracion_spin.get_value() == 30

print('borrar sensible sin edicion:', win._borrar_button.get_sensitive())
assert win._borrar_button.get_sensitive() is False

win._titulo_entry.set_text('Prueba')
win._save_meeting()
assert len(win._config['reuniones']) == 1
meeting = win._config['reuniones'][0]
assert meeting['duracion_min'] == 30

win._load_meeting_into_form(meeting)
print('borrar sensible tras cargar:', win._borrar_button.get_sensitive())
assert win._borrar_button.get_sensitive() is True

win._delete_current_meeting()
assert win._config['reuniones'] == []
assert win._borrar_button.get_sensitive() is False
print('OK')
"
```

Expected: imprime `OK` sin excepciones ni asserts fallidos.

- [ ] **Step 8: Run the full suite and commit**

Run: `cd code && python3 -m pytest tests/ -q`

```bash
git add code/mk96_app_debian_rocket_tool/meetings_window.py
git commit -m "feat: add duration field, delete and open-link buttons to meeting form"
```

---

## Task 7: `meetings_calendar.py` — vista Día

**Files:**
- Create: `code/mk96_app_debian_rocket_tool/meetings_calendar.py`

**Interfaces:**
- Consumes (de `meetings.py`): `TIMELINE_FILAS`, `TIMELINE_FRANJA_MIN`,
  `TIMELINE_INICIO_HORA`, `occurrences_in_range`, `assign_lanes`, `filas_para_bloque`,
  `posicion_columna`.
- Produces: `build_day_view(meetings: list, dia: date, ahora: datetime, on_meeting_clicked: callable) -> Gtk.Widget`
  — `on_meeting_clicked(meeting: dict)` se llama al pinchar un bloque.

Sin tests automáticos (GTK) — verificación manual con Xvfb.

- [ ] **Step 1: Crear el archivo con `build_day_view`**

```python
"""Vistas de calendario (Día/Semana/Mes) de MeetingsWindow: traducen las reuniones ya
calculadas por meetings.py (occurrences_in_range, assign_lanes, filas_para_bloque,
posicion_columna) a Gtk.Grid/Gtk.Box -este módulo no repite lógica de recurrencia ni de
solapes, solo la dibuja."""

from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from mk96_app_debian_rocket_tool.meetings import (
    TIMELINE_FILAS,
    TIMELINE_FRANJA_MIN,
    TIMELINE_INICIO_HORA,
    assign_lanes,
    filas_para_bloque,
    occurrences_in_range,
    posicion_columna,
)


def _etiqueta_bloque(ocurrencia: datetime, meeting: dict, recortada_arriba: bool, recortada_abajo: bool) -> str:
    texto = f"{ocurrencia.strftime('%H:%M')} {meeting['titulo']}"
    if recortada_arriba:
        texto = "▲ " + texto
    if recortada_abajo:
        texto = texto + " ▼"
    return texto


def _intervalos_del_dia(meetings: list, dia) -> list:
    inicio_dia = datetime.combine(dia, datetime.min.time())
    fin_dia = inicio_dia + timedelta(days=1)
    intervalos = []
    for meeting in meetings:
        for ocurrencia in occurrences_in_range(meeting, inicio_dia, fin_dia):
            fin_ocurrencia = ocurrencia + timedelta(minutes=meeting["duracion_min"])
            intervalos.append((ocurrencia, fin_ocurrencia, (meeting, ocurrencia)))
    return intervalos


def _etiquetas_horas(grid: Gtk.Grid, columna: int, fila_extra: int) -> None:
    """Coloca una etiqueta 'HH:00' cada dos filas (cada hora en punto) en `columna`,
    desplazada `fila_extra` filas (usado por la vista Semana para dejar hueco a la
    cabecera de días)."""
    for fila in range(TIMELINE_FILAS):
        minuto_total = fila * TIMELINE_FRANJA_MIN
        if minuto_total % 60 != 0:
            continue
        hora_fila = TIMELINE_INICIO_HORA + minuto_total // 60
        etiqueta = Gtk.Label(label=f"{hora_fila:02d}:00", xalign=1)
        etiqueta.get_style_context().add_class("dim-label")
        grid.attach(etiqueta, columna, fila + fila_extra, 1, 2)


def _adjuntar_bloques(grid, intervalos, columna_base, fila_extra, on_meeting_clicked) -> None:
    for (meeting, ocurrencia), carril, total_carriles in assign_lanes(intervalos):
        fila_inicio, num_filas, recortada_arriba, recortada_abajo = filas_para_bloque(
            ocurrencia, meeting["duracion_min"]
        )
        columna_relativa, ancho = posicion_columna(carril, total_carriles)
        boton = Gtk.Button(label=_etiqueta_bloque(ocurrencia, meeting, recortada_arriba, recortada_abajo))
        boton.get_child().set_line_wrap(True)
        boton.connect("clicked", lambda _b, m=meeting: on_meeting_clicked(m))
        grid.attach(
            boton, columna_base + columna_relativa, fila_inicio + fila_extra, ancho, num_filas
        )


def build_day_view(meetings: list, dia, ahora: datetime, on_meeting_clicked) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=2, row_spacing=1)
    grid.set_row_homogeneous(True)

    _etiquetas_horas(grid, columna=0, fila_extra=0)
    _adjuntar_bloques(grid, _intervalos_del_dia(meetings, dia), columna_base=1, fila_extra=0,
                       on_meeting_clicked=on_meeting_clicked)

    grid.show_all()
    return grid
```

- [ ] **Step 2: Verificar a mano con Xvfb**

```bash
cd code
DISPLAY=:99 GDK_BACKEND=x11 python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.init(None)

from datetime import date, datetime
from mk96_app_debian_rocket_tool.meetings import normalize_meeting
from mk96_app_debian_rocket_tool.meetings_calendar import build_day_view

meetings = [
    normalize_meeting({'titulo': 'Sync', 'fecha_hora': '2026-08-20T10:00', 'duracion_min': 45}),
    normalize_meeting({'titulo': 'Otra', 'fecha_hora': '2026-08-20T10:15', 'duracion_min': 30}),
]

clicks = []
vista = build_day_view(meetings, date(2026, 8, 20), datetime(2026, 8, 20, 9, 0), clicks.append)
assert isinstance(vista, Gtk.Grid)

win = Gtk.Window()
win.add(vista)
win.show_all()
while Gtk.events_pending():
    Gtk.main_iteration()

botones = [w for w in vista.get_children() if isinstance(w, Gtk.Button)]
print('bloques dibujados:', len(botones))
assert len(botones) == 2
botones[0].clicked()
print('clicks:', clicks)
assert len(clicks) == 1
print('OK')
"
```

Expected: `bloques dibujados: 2`, `clicks: [...]` con una reunión, y `OK` final.

- [ ] **Step 3: Commit**

```bash
git add code/mk96_app_debian_rocket_tool/meetings_calendar.py
git commit -m "feat: add day view timeline for meetings calendar"
```

---

## Task 8: `meetings_calendar.py` — vista Semana

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings_calendar.py`

**Interfaces:**
- Consumes (de `meetings.py`): `DIAS_SEMANA`, `NOMBRES_DIA_CORTO`, `CARRILES_POR_DIA`.
- Produces: `build_week_view(meetings: list, lunes: date, ahora: datetime, on_meeting_clicked: callable) -> Gtk.Widget`.

- [ ] **Step 1: Añadir el import y `build_week_view`**

Añadir `DIAS_SEMANA`, `NOMBRES_DIA_CORTO`, `CARRILES_POR_DIA` al `from
mk96_app_debian_rocket_tool.meetings import (...)` existente en
`code/mk96_app_debian_rocket_tool/meetings_calendar.py`. Después, añadir al final del
archivo:

```python
def build_week_view(meetings: list, lunes, ahora: datetime, on_meeting_clicked) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=2, row_spacing=1)
    grid.set_row_homogeneous(True)

    _etiquetas_horas(grid, columna=0, fila_extra=1)  # fila 0 se reserva para cabeceras

    for indice_dia in range(7):
        dia = lunes + timedelta(days=indice_dia)
        columna_dia = 1 + indice_dia * CARRILES_POR_DIA

        cabecera = Gtk.Label(label=f"{NOMBRES_DIA_CORTO[DIAS_SEMANA[indice_dia]]} {dia.day:02d}")
        cabecera.get_style_context().add_class("dim-label")
        grid.attach(cabecera, columna_dia, 0, CARRILES_POR_DIA, 1)

        _adjuntar_bloques(
            grid, _intervalos_del_dia(meetings, dia), columna_base=columna_dia,
            fila_extra=1, on_meeting_clicked=on_meeting_clicked,
        )

    grid.show_all()
    return grid
```

- [ ] **Step 2: Verificar a mano con Xvfb**

```bash
cd code
DISPLAY=:99 GDK_BACKEND=x11 python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.init(None)

from datetime import date, datetime
from mk96_app_debian_rocket_tool.meetings import normalize_meeting
from mk96_app_debian_rocket_tool.meetings_calendar import build_week_view

meetings = [
    normalize_meeting({'titulo': 'Lunes', 'fecha_hora': '2026-08-17T10:00', 'duracion_min': 30}),
    normalize_meeting({'titulo': 'Jueves', 'fecha_hora': '2026-08-20T15:00', 'duracion_min': 60}),
]

clicks = []
vista = build_week_view(meetings, date(2026, 8, 17), datetime(2026, 8, 17, 9, 0), clicks.append)

win = Gtk.Window()
win.add(vista)
win.show_all()
while Gtk.events_pending():
    Gtk.main_iteration()

botones = [w for w in vista.get_children() if isinstance(w, Gtk.Button)]
print('bloques dibujados:', len(botones))
assert len(botones) == 2
botones[0].clicked()
assert len(clicks) == 1
print('OK')
"
```

Expected: `bloques dibujados: 2` y `OK`.

- [ ] **Step 3: Commit**

```bash
git add code/mk96_app_debian_rocket_tool/meetings_calendar.py
git commit -m "feat: add week view timeline for meetings calendar"
```

---

## Task 9: `meetings_calendar.py` — vista Mes

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings_calendar.py`

**Interfaces:**
- Produces: `build_month_view(meetings: list, year: int, month: int, ahora: datetime, on_meeting_clicked: callable) -> Gtk.Widget`.

- [ ] **Step 1: Añadir `from datetime import date` y `build_month_view`**

Cambiar la primera línea de import del archivo de `from datetime import datetime,
timedelta` a `from datetime import date, datetime, timedelta`. Después, añadir al
final del archivo:

```python
def build_month_view(meetings: list, year: int, month: int, ahora: datetime, on_meeting_clicked) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=4, row_spacing=4)
    grid.set_column_homogeneous(True)

    primer_dia_mes = date(year, month, 1)
    primer_lunes = primer_dia_mes - timedelta(days=primer_dia_mes.weekday())

    for indice_dia_semana, codigo in enumerate(DIAS_SEMANA):
        cabecera = Gtk.Label(label=NOMBRES_DIA_CORTO[codigo])
        cabecera.get_style_context().add_class("dim-label")
        grid.attach(cabecera, indice_dia_semana, 0, 1, 1)

    for semana in range(6):
        for indice_dia_semana in range(7):
            dia = primer_lunes + timedelta(days=semana * 7 + indice_dia_semana)
            celda = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            celda.set_border_width(2)

            numero = Gtk.Label(label=str(dia.day), xalign=0)
            if dia.month != month:
                numero.get_style_context().add_class("dim-label")
            celda.pack_start(numero, False, False, 0)

            inicio_dia = datetime.combine(dia, datetime.min.time())
            fin_dia = inicio_dia + timedelta(days=1)
            ocurrencias = []
            for meeting in meetings:
                for ocurrencia in occurrences_in_range(meeting, inicio_dia, fin_dia):
                    ocurrencias.append((ocurrencia, meeting))
            ocurrencias.sort(key=lambda par: par[0])

            for ocurrencia, meeting in ocurrencias:
                boton = Gtk.Button(label=f"{ocurrencia.strftime('%H:%M')} {meeting['titulo']}")
                boton.set_relief(Gtk.ReliefStyle.NONE)
                boton.get_child().set_xalign(0)
                boton.connect("clicked", lambda _b, m=meeting: on_meeting_clicked(m))
                celda.pack_start(boton, False, False, 0)

            grid.attach(celda, indice_dia_semana, semana + 1, 1, 1)

    grid.show_all()
    return grid
```

- [ ] **Step 2: Verificar a mano con Xvfb**

```bash
cd code
DISPLAY=:99 GDK_BACKEND=x11 python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.init(None)

from datetime import datetime
from mk96_app_debian_rocket_tool.meetings import normalize_meeting
from mk96_app_debian_rocket_tool.meetings_calendar import build_month_view

meetings = [
    normalize_meeting({'titulo': 'Reunion A', 'fecha_hora': '2026-08-05T10:00'}),
    normalize_meeting({'titulo': 'Reunion B', 'fecha_hora': '2026-08-31T10:00'}),
    normalize_meeting({'titulo': 'Fuera de mes', 'fecha_hora': '2026-09-02T10:00'}),
]

clicks = []
vista = build_month_view(meetings, 2026, 8, datetime(2026, 8, 1, 0, 0), clicks.append)

win = Gtk.Window()
win.add(vista)
win.show_all()
while Gtk.events_pending():
    Gtk.main_iteration()

def contar_botones(widget):
    total = 0
    if isinstance(widget, Gtk.Button):
        total += 1
    if hasattr(widget, 'get_children'):
        for hijo in widget.get_children():
            total += contar_botones(hijo)
    return total

print('botones de reunion en el mes:', contar_botones(vista))
assert contar_botones(vista) == 3  # A, B, y la de septiembre SI cae en la rejilla de 6 semanas
print('OK')
"
```

Expected: imprime el número de botones (incluye la de septiembre si cae dentro de la
rejilla de 6 semanas que empieza el lunes anterior al 1 de agosto) y `OK`. Si el
`assert` falla porque la reunión de septiembre queda fuera de las 6 filas, ajustar el
`assert` a `>= 2` (A y B siempre caen dentro del mes) y anotarlo en el commit -no es un
bug, depende de en qué día de la semana cae el 1 de agosto de 2026.

- [ ] **Step 3: Commit**

```bash
git add code/mk96_app_debian_rocket_tool/meetings_calendar.py
git commit -m "feat: add month view grid for meetings calendar"
```

---

## Task 10: Cablear las vistas en `MeetingsWindow`

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/meetings_window.py`

**Interfaces:**
- Consumes: `build_day_view`, `build_week_view`, `build_month_view` (de
  `meetings_calendar.py`); `week_bounds`, `format_day_label`, `format_week_label`,
  `format_month_label` (de `meetings.py`).

- [ ] **Step 1: Actualizar imports**

En `code/mk96_app_debian_rocket_tool/meetings_window.py`, cambiar:

```python
from datetime import datetime
```

por:

```python
import calendar
from datetime import date, datetime, timedelta
```

Y en el bloque `from mk96_app_debian_rocket_tool.meetings import (...)`, quitar
`next_occurrence` (ya no se usa tras quitar `_describe_meeting` en el Step 3) y añadir
`format_day_label`, `format_month_label`, `format_week_label`, `week_bounds`. Añadir
también, como import nuevo:

```python
from mk96_app_debian_rocket_tool.meetings_calendar import build_day_view, build_month_view, build_week_view
```

- [ ] **Step 2: Reemplazar el bloque de la lista en `__init__` por el selector + navegación + contenedor**

Sustituir, en `__init__`, desde `self._editing_id = None` hasta justo antes de
`root.pack_start(Gtk.Separator(), False, False, 0)` (es decir, todo el bloque de
`self._selected_sonido_id`, la creación de `root`, la etiqueta "Reuniones guardadas" y
el `self._list`/`list_scroller`), por:

```python
        self._config = config
        self._on_config_changed = on_config_changed
        self._editing_id = None
        self._selected_sonido_id = None
        self._vista_actual = "dia"
        self._fecha_referencia = date.today()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(12)
        self.add(root)

        vista_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._vista_dia_radio = Gtk.RadioButton.new_with_label_from_widget(None, "Día")
        self._vista_semana_radio = Gtk.RadioButton.new_with_label_from_widget(
            self._vista_dia_radio, "Semana"
        )
        self._vista_mes_radio = Gtk.RadioButton.new_with_label_from_widget(
            self._vista_dia_radio, "Mes"
        )
        for radio, vista in (
            (self._vista_dia_radio, "dia"),
            (self._vista_semana_radio, "semana"),
            (self._vista_mes_radio, "mes"),
        ):
            radio.set_mode(False)
            radio.connect("toggled", self._on_vista_toggled, vista)
            vista_box.pack_start(radio, False, False, 0)
        root.pack_start(vista_box, False, False, 0)

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
        calendario_scroller = Gtk.ScrolledWindow()
        calendario_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        calendario_scroller.set_min_content_height(360)
        calendario_scroller.add(self._calendario_container)
        root.pack_start(calendario_scroller, True, True, 0)
```

Y sustituir, al final de `__init__`, estas tres líneas:

```python
        self._refresh_list()
        self.show_all()
        self._clear_form()
```

por:

```python
        self.show_all()
        self._clear_form()
        self._refresh_calendar()
```

(`set_default_size` puede subirse a `self.set_default_size(760, 640)` para dar más
sitio al timeline -opcional pero recomendado).

- [ ] **Step 2: Añadir los métodos de navegación y refresco del calendario**

Añadir estos métodos a la clase (por ejemplo, justo antes de `_update_repeticion_visibility`):

```python
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

    def _refresh_calendar(self) -> None:
        for child in self._calendario_container.get_children():
            self._calendario_container.remove(child)

        ahora = datetime.now()
        reuniones = self._config["reuniones"]

        if self._vista_actual == "dia":
            self._periodo_label.set_text(format_day_label(self._fecha_referencia))
            vista = build_day_view(reuniones, self._fecha_referencia, ahora, self._load_meeting_into_form)
        elif self._vista_actual == "semana":
            lunes, _fin_semana = week_bounds(self._fecha_referencia)
            self._periodo_label.set_text(format_week_label(lunes))
            vista = build_week_view(reuniones, lunes, ahora, self._load_meeting_into_form)
        else:
            self._periodo_label.set_text(
                format_month_label(self._fecha_referencia.year, self._fecha_referencia.month)
            )
            vista = build_month_view(
                reuniones, self._fecha_referencia.year, self._fecha_referencia.month, ahora,
                self._load_meeting_into_form,
            )

        self._calendario_container.pack_start(vista, True, True, 0)
        self._calendario_container.show_all()
```

- [ ] **Step 3: Quitar el código de la lista que ya no se usa**

Eliminar de la clase los métodos `_refresh_list` y `_describe_meeting` por completo
(el bloque bajo el comentario `# -- Lista ---...` hasta el final de
`_describe_meeting`). Eliminar también `_toggle_meeting_active` (ya no hay checkbox de
"activa" fuera del formulario -la casilla "Activa" del formulario sigue existiendo y
sigue funcionando igual).

En `_remove_meeting`, cambiar `self._refresh_list()` por `self._refresh_calendar()`.

En `_save_meeting`, cambiar la línea final `self._refresh_list()` por
`self._refresh_calendar()`.

- [ ] **Step 4: Verificar a mano con Xvfb — navegación y construcción de vistas**

```bash
cd code
DISPLAY=:99 GDK_BACKEND=x11 python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.init(None)

from mk96_app_debian_rocket_tool.meetings_window import MeetingsWindow

win = MeetingsWindow({'reuniones': []}, lambda cfg: None)
while Gtk.events_pending():
    Gtk.main_iteration()

print('vista inicial:', win._vista_actual)
assert win._vista_actual == 'dia'
print('periodo:', win._periodo_label.get_text())
assert win._periodo_label.get_text() != ''

win._vista_semana_radio.set_active(True)
while Gtk.events_pending():
    Gtk.main_iteration()
assert win._vista_actual == 'semana'
print('periodo semana:', win._periodo_label.get_text())

referencia_antes = win._fecha_referencia
win._navegar_periodo(1)
assert win._fecha_referencia != referencia_antes
print('avanzo periodo:', win._fecha_referencia)

win._ir_a_hoy()
from datetime import date
assert win._fecha_referencia == date.today()

win._vista_mes_radio.set_active(True)
while Gtk.events_pending():
    Gtk.main_iteration()
assert win._vista_actual == 'mes'
print('periodo mes:', win._periodo_label.get_text())
print('OK')
"
```

Expected: imprime los periodos y `OK`, sin excepciones.

- [ ] **Step 5: Verificar a mano con Xvfb — click en un bloque carga el formulario**

```bash
cd code
DISPLAY=:99 GDK_BACKEND=x11 python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.init(None)

from datetime import date
from mk96_app_debian_rocket_tool.meetings import normalize_meeting, round_up_to_next_half_hour
from mk96_app_debian_rocket_tool.meetings_window import MeetingsWindow

hoy_hora = round_up_to_next_half_hour(__import__('datetime').datetime.now())
meeting = normalize_meeting({
    'titulo': 'Reunion de prueba',
    'fecha_hora': hoy_hora.strftime('%Y-%m-%dT%H:%M'),
})
config = {'reuniones': [meeting]}
win = MeetingsWindow(config, lambda cfg: None)
while Gtk.events_pending():
    Gtk.main_iteration()

def buscar_boton(widget):
    if isinstance(widget, Gtk.Button) and 'Reunion de prueba' in (widget.get_label() or ''):
        return widget
    if hasattr(widget, 'get_children'):
        for hijo in widget.get_children():
            encontrado = buscar_boton(hijo)
            if encontrado is not None:
                return encontrado
    return None

boton = buscar_boton(win._calendario_container)
assert boton is not None, 'no se encontro el bloque de la reunion en la vista Dia'
boton.clicked()
while Gtk.events_pending():
    Gtk.main_iteration()

print('titulo cargado en el formulario:', win._titulo_entry.get_text())
assert win._titulo_entry.get_text() == 'Reunion de prueba'
assert win._editing_id == meeting['id']
print('OK')
"
```

Expected: `titulo cargado en el formulario: Reunion de prueba` y `OK`.

- [ ] **Step 6: Run the full test suite**

Run: `cd code && python3 -m pytest tests/ -q`
Expected: todos los tests pasan (ninguno testea `MeetingsWindow` directamente, así que
no deberían romperse por este task, pero confirma que `meetings.py` sigue sano).

- [ ] **Step 7: Commit**

```bash
git add code/mk96_app_debian_rocket_tool/meetings_window.py
git commit -m "feat: replace meetings list with day/week/month calendar views"
```

---

## Task 11: Verificación final integrada

**Files:** ninguno nuevo — solo verificación.

- [ ] **Step 1: Suite completa de pytest**

Run: `cd code && python3 -m pytest tests/ -v`
Expected: todos los tests en verde (deberían ser los ~140 anteriores + los ~24 nuevos
de los tasks 1-5).

- [ ] **Step 2: Arrancar la app real bajo Xvfb y comprobar visualmente**

```bash
pgrep -f "Xvfb :99" || (Xvfb :99 -screen 0 1280x800x24 & disown)
cd code
DISPLAY=:99 GDK_BACKEND=x11 python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
Gtk.init(None)

from mk96_app_debian_rocket_tool.meetings import normalize_meeting
from mk96_app_debian_rocket_tool.meetings_window import MeetingsWindow

config = {
    'reuniones': [
        normalize_meeting({'titulo': 'Diaria', 'fecha_hora': '2026-08-17T09:00', 'repeticion_modo': 'diaria', 'duracion_min': 30}),
        normalize_meeting({'titulo': 'Larga', 'fecha_hora': '2026-08-20T14:00', 'duracion_min': 120}),
    ]
}
win = MeetingsWindow(config, lambda cfg: None)
win.set_default_size(900, 700)
while Gtk.events_pending():
    Gtk.main_iteration()

pb = Gdk.pixbuf_get_from_window(win.get_window(), 0, 0, *win.get_size())
pb.savev('/tmp/meetings_calendar_dia.png', 'png', [], [])

win._vista_semana_radio.set_active(True)
while Gtk.events_pending():
    Gtk.main_iteration()
pb = Gdk.pixbuf_get_from_window(win.get_window(), 0, 0, *win.get_size())
pb.savev('/tmp/meetings_calendar_semana.png', 'png', [], [])

win._vista_mes_radio.set_active(True)
while Gtk.events_pending():
    Gtk.main_iteration()
pb = Gdk.pixbuf_get_from_window(win.get_window(), 0, 0, *win.get_size())
pb.savev('/tmp/meetings_calendar_mes.png', 'png', [], [])
print('capturas guardadas')
"
```

Expected: `capturas guardadas` sin excepciones. Abrir (`Read`) las tres imágenes en
`/tmp/meetings_calendar_dia.png`, `/tmp/meetings_calendar_semana.png`,
`/tmp/meetings_calendar_mes.png` y comprobar visualmente que: la vista Día muestra el
bloque de "Larga" con el tamaño correcto (2h = 4 filas), la vista Semana muestra
"Diaria" en varias columnas, y la vista Mes muestra ambas reuniones en sus celdas.

- [ ] **Step 3: Arrancar la app completa (no solo la ventana) para confirmar que no rompe el arranque**

```bash
pkill -f "mk96_app_debian_rocket_tool.app" 2>/dev/null
sleep 1
cd code
DISPLAY=:99 nohup env PYTHONPATH="$PWD" python3 -m mk96_app_debian_rocket_tool.app > /tmp/mk96-app-debian-rocket-tool.log 2>&1 &
sleep 2
ps aux | grep mk96_app_debian_rocket_tool.app | grep -v grep
cat /tmp/mk96-app-debian-rocket-tool.log
```

Expected: el proceso aparece corriendo y `/tmp/mk96-app-debian-rocket-tool.log` está vacío
(sin tracebacks).

- [ ] **Step 4: Commit final si algo quedó pendiente**

Si los pasos anteriores no requirieron cambios de código, no hay nada que commitear en
este task -es solo verificación. Si se detectó y corrigió algo, commitear con un
mensaje que describa el arreglo puntual (no un commit vacío).
