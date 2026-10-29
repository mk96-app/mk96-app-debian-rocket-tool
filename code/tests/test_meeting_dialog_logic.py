from datetime import date, datetime

from mk96_app_debian_rocket_tool.meeting_dialog import validate_meeting_form
from mk96_app_debian_rocket_tool.meetings import hora_por_defecto_en_dia
from mk96_app_debian_rocket_tool.meetings_calendar import pastillas_visibles, tooltip_reunion


def test_form_requires_title_date_and_time():
    error, _ = validate_meeting_form("", "13/10/2026", "10:00", "", "ninguna", [])
    assert error[0] == "Faltan datos"
    error, _ = validate_meeting_form("x", "", "10:00", "", "ninguna", [])
    assert error[0] == "Faltan datos"


def test_form_rejects_invalid_date_or_time():
    error, _ = validate_meeting_form("x", "31/02/2026", "10:00", "", "ninguna", [])
    assert error[0] == "Fecha u hora inválida"
    error, _ = validate_meeting_form("x", "13/10/2026", "25:00", "", "ninguna", [])
    assert error[0] == "Fecha u hora inválida"


def test_form_rejects_invalid_end_date():
    error, _ = validate_meeting_form("x", "13/10/2026", "10:00", "99/99/2026", "diaria", [])
    assert error[0] == "Fecha de fin inválida"


def test_form_weekly_needs_days():
    error, _ = validate_meeting_form("x", "13/10/2026", "10:00", "", "semanal", [])
    assert error[0] == "Faltan días"
    assert validate_meeting_form("x", "13/10/2026", "10:00", "", "semanal", ["lun"])[0] is None


def test_form_returns_parsed_values():
    error, valores = validate_meeting_form("x", "13/10/2026", "10:00", "20/10/2026", "diaria", [])
    assert error is None
    assert valores == ("2026-10-13", "10:00", "2026-10-20")


def test_pastillas_visibles():
    assert pastillas_visibles(2) == (2, 0)
    assert pastillas_visibles(3) == (3, 0)
    assert pastillas_visibles(7) == (3, 4)


def test_hora_por_defecto_today_is_next_half_hour_other_days_9am():
    ahora = datetime(2026, 10, 13, 15, 10)
    assert hora_por_defecto_en_dia(date(2026, 10, 13), ahora) == datetime(2026, 10, 13, 15, 30)
    assert hora_por_defecto_en_dia(date(2026, 10, 20), ahora) == datetime(2026, 10, 20, 9, 0)


def test_tooltip_has_title_range_and_inactive_mark():
    meeting = {"titulo": "Daily", "duracion_min": 30, "activa": False, "notas": "sala 2"}
    texto = tooltip_reunion(meeting, datetime(2026, 10, 13, 9, 30))
    assert "Daily" in texto and "09:30 - 10:00" in texto and "inactiva" in texto and "sala 2" in texto


from mk96_app_debian_rocket_tool.meetings import format_duracion, franja_seleccion, posicion_ahora


def test_franja_seleccion_is_order_independent_and_inclusive():
    inicio, duracion = franja_seleccion(date(2026, 10, 13), 5, 2)
    assert inicio == datetime(2026, 10, 13, 8, 0)  # fila 2 = 07:00 + 2 franjas de 30 min
    assert duracion == 120


def test_franja_seleccion_single_row_is_30_minutes():
    inicio, duracion = franja_seleccion(date(2026, 10, 13), 0, 0)
    assert (inicio, duracion) == (datetime(2026, 10, 13, 7, 0), 30)


def test_posicion_ahora_is_exact_to_the_minute():
    assert posicion_ahora(datetime(2026, 10, 13, 7, 0)) == (0, 0.0)
    fila, fraccion = posicion_ahora(datetime(2026, 10, 13, 15, 45))
    assert fila == 17 and fraccion == 0.5
    assert posicion_ahora(datetime(2026, 10, 13, 6, 59)) is None
    assert posicion_ahora(datetime(2026, 10, 13, 21, 0)) is None


def test_format_duracion():
    assert format_duracion(30) == "30 min"
    assert format_duracion(60) == "1 h"
    assert format_duracion(90) == "1 h 30 min"
