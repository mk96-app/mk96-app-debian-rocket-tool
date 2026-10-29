from datetime import date, datetime

from mk96_app_debian_rocket_tool.meetings import (
    CARRILES_POR_DIA,
    TIMELINE_FILAS,
    assign_lanes,
    due_meetings,
    filas_para_bloque,
    fila_timeline,
    format_day_label,
    format_month_label,
    format_partial_date_digits,
    format_partial_time_digits,
    format_week_label,
    next_occurrence,
    normalize_meeting,
    occurrences_in_range,
    parse_ddmmyyyy,
    parse_hhmm,
    posicion_columna,
    round_up_to_next_half_hour,
    startup_due_meetings,
    week_bounds,
)


def _meeting(**overrides):
    base = {"titulo": "Sync semanal", "fecha_hora": "2026-08-20T10:00"}
    base.update(overrides)
    return normalize_meeting(base)


# -- format_partial_date_digits / format_partial_time_digits -------------------------


def test_format_partial_date_digits_inserts_slash_after_day():
    assert format_partial_date_digits("04") == "04/"


def test_format_partial_date_digits_inserts_slash_after_month():
    assert format_partial_date_digits("0412") == "04/12/"


def test_format_partial_date_digits_full_date_has_no_trailing_slash():
    assert format_partial_date_digits("04122026") == "04/12/2026"


def test_format_partial_date_digits_mid_group_has_no_slash_yet():
    assert format_partial_date_digits("0") == "0"


def test_format_partial_date_digits_ignores_digits_past_eight():
    assert format_partial_date_digits("041220269999") == "04/12/2026"


def test_format_partial_time_digits_inserts_colon_after_hour():
    assert format_partial_time_digits("10") == "10:"


def test_format_partial_time_digits_full_time_has_no_trailing_colon():
    assert format_partial_time_digits("1030") == "10:30"


# -- parse_ddmmyyyy / parse_hhmm ------------------------------------------------------


def test_parse_ddmmyyyy_returns_iso_string():
    assert parse_ddmmyyyy("20/08/2026") == "2026-08-20"


def test_parse_ddmmyyyy_rejects_nonexistent_date():
    assert parse_ddmmyyyy("31/02/2026") is None


def test_parse_ddmmyyyy_rejects_incomplete_text():
    assert parse_ddmmyyyy("20/08") is None


def test_parse_ddmmyyyy_rejects_garbage():
    assert parse_ddmmyyyy("no es una fecha") is None


def test_parse_hhmm_returns_normalized_string():
    assert parse_hhmm("09:05") == "09:05"


def test_parse_hhmm_rejects_out_of_range_hour():
    assert parse_hhmm("24:00") is None


def test_parse_hhmm_rejects_incomplete_text():
    assert parse_hhmm("9:") is None


# -- round_up_to_next_half_hour -------------------------------------------------------


def test_round_up_to_next_half_hour_rounds_up_within_first_half():
    assert round_up_to_next_half_hour(datetime(2026, 8, 20, 10, 17)) == datetime(2026, 8, 20, 10, 30)


def test_round_up_to_next_half_hour_rounds_up_into_next_hour():
    assert round_up_to_next_half_hour(datetime(2026, 8, 20, 10, 35)) == datetime(2026, 8, 20, 11, 0)


def test_round_up_to_next_half_hour_advances_even_when_already_on_the_mark():
    assert round_up_to_next_half_hour(datetime(2026, 8, 20, 10, 30)) == datetime(2026, 8, 20, 11, 0)


def test_round_up_to_next_half_hour_rolls_over_to_next_day():
    assert round_up_to_next_half_hour(datetime(2026, 8, 20, 23, 45)) == datetime(2026, 8, 21, 0, 0)


def test_normalize_meeting_defaults():
    meeting = normalize_meeting({"titulo": "Sync", "fecha_hora": "2026-08-20T10:00"})
    assert meeting["repeticion_modo"] == "ninguna"
    assert meeting["repeticion_dias"] == []
    assert meeting["repeticion_fin"] is None
    assert meeting["aviso_antes_min"] == 0
    assert meeting["enlace"] is None
    assert meeting["notas"] == ""
    assert meeting["sonido_id"] is None
    assert meeting["activa"] is True
    assert meeting["id"]


def test_normalize_meeting_keeps_explicit_values():
    meeting = normalize_meeting(
        {
            "id": "m1",
            "titulo": "Sync",
            "fecha_hora": "2026-08-20T10:00",
            "repeticion_modo": "semanal",
            "repeticion_dias": ["lun", "jue"],
            "repeticion_fin": "2026-12-31",
            "aviso_antes_min": 10,
            "enlace": "https://meet.example/abc",
            "notas": "Traer el informe",
            "sonido_id": "interface-sounds/bong_001",
            "activa": False,
        }
    )
    assert meeting == {
        "id": "m1",
        "titulo": "Sync",
        "fecha_hora": "2026-08-20T10:00",
        "repeticion_modo": "semanal",
        "repeticion_dias": ["lun", "jue"],
        "repeticion_fin": "2026-12-31",
        "aviso_antes_min": 10,
        "enlace": "https://meet.example/abc",
        "notas": "Traer el informe",
        "sonido_id": "interface-sounds/bong_001",
        "activa": False,
        "duracion_min": 30,
        "excepciones": {},
    }


def test_normalize_meeting_defaults_duracion_to_30_minutes():
    meeting = normalize_meeting({"titulo": "Sync", "fecha_hora": "2026-08-20T10:00"})
    assert meeting["duracion_min"] == 30


def test_normalize_meeting_keeps_explicit_duracion():
    meeting = normalize_meeting(
        {"titulo": "Sync", "fecha_hora": "2026-08-20T10:00", "duracion_min": 90}
    )
    assert meeting["duracion_min"] == 90


def test_normalize_meeting_coerces_yaml_date_object_to_str():
    meeting = normalize_meeting(
        {"titulo": "Sync", "fecha_hora": "2026-08-20T10:00", "repeticion_fin": date(2026, 12, 31)}
    )
    assert meeting["repeticion_fin"] == "2026-12-31"


def test_next_occurrence_ninguna_future_returns_fecha_hora():
    meeting = _meeting(fecha_hora="2026-08-20T10:00")
    ahora = datetime(2026, 8, 18, 9, 0)
    assert next_occurrence(meeting, ahora) == datetime(2026, 8, 20, 10, 0)


def test_next_occurrence_ninguna_past_returns_none():
    meeting = _meeting(fecha_hora="2026-08-10T10:00")
    ahora = datetime(2026, 8, 18, 9, 0)
    assert next_occurrence(meeting, ahora) is None


def test_next_occurrence_inactive_returns_none():
    meeting = _meeting(fecha_hora="2026-08-20T10:00", activa=False)
    ahora = datetime(2026, 8, 18, 9, 0)
    assert next_occurrence(meeting, ahora) is None


def test_next_occurrence_diaria_same_day_before_time():
    meeting = _meeting(fecha_hora="2026-08-10T10:00", repeticion_modo="diaria")
    ahora = datetime(2026, 8, 18, 9, 0)
    assert next_occurrence(meeting, ahora) == datetime(2026, 8, 18, 10, 0)


def test_next_occurrence_diaria_same_day_after_time_rolls_to_tomorrow():
    meeting = _meeting(fecha_hora="2026-08-10T10:00", repeticion_modo="diaria")
    ahora = datetime(2026, 8, 18, 11, 0)
    assert next_occurrence(meeting, ahora) == datetime(2026, 8, 19, 10, 0)


def test_next_occurrence_diaria_respects_repeticion_fin():
    meeting = _meeting(
        fecha_hora="2026-08-10T10:00", repeticion_modo="diaria", repeticion_fin="2026-08-17"
    )
    ahora = datetime(2026, 8, 18, 9, 0)
    assert next_occurrence(meeting, ahora) is None


def test_next_occurrence_semanal_finds_next_matching_weekday():
    # 2026-08-03 es lunes, 2026-08-18 es martes; la reunión es lunes y jueves.
    meeting = _meeting(
        fecha_hora="2026-08-03T10:00", repeticion_modo="semanal", repeticion_dias=["lun", "jue"]
    )
    ahora = datetime(2026, 8, 18, 9, 0)
    assert next_occurrence(meeting, ahora) == datetime(2026, 8, 20, 10, 0)  # jueves


def test_next_occurrence_semanal_skips_today_if_time_already_passed():
    # 2026-08-20 es jueves; si ya pasó la hora, salta a la próxima semana (08-27).
    meeting = _meeting(fecha_hora="2026-08-03T10:00", repeticion_modo="semanal", repeticion_dias=["jue"])
    ahora = datetime(2026, 8, 20, 11, 0)
    assert next_occurrence(meeting, ahora) == datetime(2026, 8, 27, 10, 0)


def test_next_occurrence_mensual_same_day_next_month():
    meeting = _meeting(fecha_hora="2026-06-15T09:00", repeticion_modo="mensual")
    ahora = datetime(2026, 8, 18, 9, 0)
    assert next_occurrence(meeting, ahora) == datetime(2026, 9, 15, 9, 0)


def test_next_occurrence_mensual_skips_month_without_that_day():
    # Día 31: enero tiene 31, febrero no -se omite y cae en marzo.
    meeting = _meeting(fecha_hora="2026-01-31T09:00", repeticion_modo="mensual")
    ahora = datetime(2026, 1, 31, 10, 0)  # ya pasó la hora del 31 de enero
    assert next_occurrence(meeting, ahora) == datetime(2026, 3, 31, 9, 0)


def test_due_meetings_fires_aviso_when_lead_time_window_opens():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=10)
    ultimo_chequeo = datetime(2026, 8, 18, 9, 49)
    ahora = datetime(2026, 8, 18, 9, 50)  # aviso_en = 9:50, justo en la ventana
    assert due_meetings([meeting], ahora, ultimo_chequeo) == [
        (meeting, datetime(2026, 8, 18, 10, 0), "aviso")
    ]


def test_due_meetings_also_fires_hora_at_the_exact_moment_even_with_aviso_previo():
    # Con aviso_antes_min > 0 hay que avisar DOS veces por ocurrencia: una con
    # antelación (ya probado arriba) y otra en el momento exacto, en su propio tick.
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=10)
    ultimo_chequeo = datetime(2026, 8, 18, 9, 59, 30)
    ahora = datetime(2026, 8, 18, 10, 0, 0)
    assert due_meetings([meeting], ahora, ultimo_chequeo) == [
        (meeting, datetime(2026, 8, 18, 10, 0), "hora")
    ]


def test_due_meetings_fires_only_hora_once_when_no_aviso_previo():
    # aviso_antes_min == 0: el instante de aviso y el de la hora coinciden, así que
    # solo debe dispararse una vez (momento "hora"), nunca dos.
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=0)
    ultimo_chequeo = datetime(2026, 8, 18, 9, 59, 30)
    ahora = datetime(2026, 8, 18, 10, 0, 0)
    assert due_meetings([meeting], ahora, ultimo_chequeo) == [
        (meeting, datetime(2026, 8, 18, 10, 0), "hora")
    ]


def test_due_meetings_does_not_fire_before_aviso_window():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=10)
    ultimo_chequeo = datetime(2026, 8, 18, 9, 0)
    ahora = datetime(2026, 8, 18, 9, 30)
    assert due_meetings([meeting], ahora, ultimo_chequeo) == []


def test_due_meetings_does_not_duplicate_across_ticks():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=0)
    primer_tick = due_meetings(
        [meeting], datetime(2026, 8, 18, 10, 0), datetime(2026, 8, 18, 9, 59, 30)
    )
    assert primer_tick == [(meeting, datetime(2026, 8, 18, 10, 0), "hora")]

    segundo_tick = due_meetings(
        [meeting], datetime(2026, 8, 18, 10, 0, 30), datetime(2026, 8, 18, 10, 0)
    )
    assert segundo_tick == []


def test_due_meetings_ignores_inactive_meeting():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", activa=False)
    ultimo_chequeo = datetime(2026, 8, 18, 9, 59, 30)
    ahora = datetime(2026, 8, 18, 10, 0, 0)
    assert due_meetings([meeting], ahora, ultimo_chequeo) == []


def test_normalize_meeting_falls_back_to_ninguna_for_unknown_repeticion_modo():
    meeting = normalize_meeting(
        {"titulo": "Sync", "fecha_hora": "2026-08-20T10:00", "repeticion_modo": "semanl"}
    )
    assert meeting["repeticion_modo"] == "ninguna"
    # y por tanto sigue siendo utilizable, sin ValueError
    assert next_occurrence(meeting, datetime(2026, 8, 1, 9, 0)) == datetime(2026, 8, 20, 10, 0)


def test_normalize_meeting_keeps_known_repeticion_modos():
    for modo in ("ninguna", "diaria", "semanal", "mensual"):
        meeting = normalize_meeting(
            {"titulo": "Sync", "fecha_hora": "2026-08-20T10:00", "repeticion_modo": modo}
        )
        assert meeting["repeticion_modo"] == modo


def test_next_occurrence_mensual_for_meeting_created_many_years_ago():
    meeting = _meeting(fecha_hora="2018-03-15T10:00", repeticion_modo="mensual")
    assert next_occurrence(meeting, datetime(2026, 8, 1, 9, 0)) == datetime(2026, 8, 15, 10, 0)


def test_next_occurrence_mensual_old_meeting_rolls_to_next_month_when_day_passed():
    meeting = _meeting(fecha_hora="2018-03-15T10:00", repeticion_modo="mensual")
    assert next_occurrence(meeting, datetime(2026, 8, 20, 9, 0)) == datetime(2026, 9, 15, 10, 0)


def test_next_occurrence_mensual_old_meeting_skips_months_without_that_day():
    meeting = _meeting(fecha_hora="2018-01-31T10:00", repeticion_modo="mensual")
    assert next_occurrence(meeting, datetime(2026, 2, 1, 9, 0)) == datetime(2026, 3, 31, 10, 0)


def test_next_occurrence_mensual_old_meeting_respects_repeticion_fin():
    meeting = _meeting(
        fecha_hora="2018-03-15T10:00", repeticion_modo="mensual", repeticion_fin="2020-01-01"
    )
    assert next_occurrence(meeting, datetime(2026, 8, 1, 9, 0)) is None


def test_startup_due_meetings_fires_when_aviso_window_already_open():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=10)
    ahora = datetime(2026, 8, 18, 9, 55)
    assert startup_due_meetings([meeting], ahora) == [
        (meeting, datetime(2026, 8, 18, 10, 0), "aviso")
    ]


def test_startup_due_meetings_ignores_meeting_whose_aviso_window_has_not_opened():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=10)
    assert startup_due_meetings([meeting], datetime(2026, 8, 18, 9, 30)) == []


def test_startup_due_meetings_ignores_meeting_already_past():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=10)
    assert startup_due_meetings([meeting], datetime(2026, 8, 18, 10, 30)) == []


def test_startup_due_meetings_fires_for_meeting_happening_exactly_now():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=0)
    ahora = datetime(2026, 8, 18, 10, 0)
    assert startup_due_meetings([meeting], ahora) == [(meeting, ahora, "hora")]


def test_startup_due_meetings_ignores_inactive_meeting():
    meeting = _meeting(fecha_hora="2026-08-18T10:00", aviso_antes_min=10, activa=False)
    assert startup_due_meetings([meeting], datetime(2026, 8, 18, 9, 55)) == []


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


# -- assign_lanes ---------------------------------------------------------------


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


# -- week_bounds / format_day_label / format_week_label / format_month_label ------


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


# -- fila_timeline / filas_para_bloque / posicion_columna ----------------------------


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


# -- ocurrencias sueltas (excepciones) -------------------------------------------------

from datetime import datetime, timedelta

from mk96_app_debian_rocket_tool.meetings import (
    con_excepcion,
    due_meetings,
    es_serie,
    estado_ocurrencia,
    next_occurrence,
    normalize_meeting,
    occurrences_in_range,
    ocurrencias_visibles,
    reunion_editada,
    startup_due_meetings,
)


def _daily(**extra):
    return normalize_meeting(
        {"id": "d", "titulo": "Daily", "fecha_hora": "2026-10-12T09:30", "repeticion_modo": "diaria", **extra}
    )


def test_excepciones_invalid_entries_are_dropped():
    m = _daily(excepciones={"2026-10-13T09:30": "borrada", "basura": "borrada", "2026-10-14T09:30": "otra"})
    assert m["excepciones"] == {"2026-10-13T09:30": "borrada"}
    assert _daily(excepciones="x")["excepciones"] == {}


def test_next_occurrence_skips_deleted_and_inactive_occurrences():
    m = con_excepcion(con_excepcion(_daily(), datetime(2026, 10, 13, 9, 30), "borrada"),
                      datetime(2026, 10, 14, 9, 30), "inactiva")
    assert next_occurrence(m, datetime(2026, 10, 13, 0, 0)) == datetime(2026, 10, 15, 9, 30)


def test_next_occurrence_terminates_when_every_occurrence_is_excepted():
    m = normalize_meeting({
        "id": "u", "titulo": "x", "fecha_hora": "2026-10-13T09:30", "repeticion_modo": "diaria",
        "repeticion_fin": "2026-10-14", "excepciones": {"2026-10-13T09:30": "borrada", "2026-10-14T09:30": "borrada"},
    })
    assert next_occurrence(m, datetime(2026, 10, 1, 0, 0)) is None


def test_occurrences_and_alerts_skip_excepted_ones():
    m = con_excepcion(_daily(), datetime(2026, 10, 13, 9, 30), "inactiva")
    inicio, fin = datetime(2026, 10, 12), datetime(2026, 10, 15)
    assert occurrences_in_range(m, inicio, fin) == [datetime(2026, 10, 12, 9, 30), datetime(2026, 10, 14, 9, 30)]
    avisos = due_meetings([m], datetime(2026, 10, 13, 9, 31), datetime(2026, 10, 13, 9, 29))
    assert avisos == []
    assert startup_due_meetings([m], datetime(2026, 10, 13, 9, 0)) == []


def test_ocurrencias_visibles_shows_inactive_but_not_deleted():
    m = con_excepcion(con_excepcion(_daily(), datetime(2026, 10, 13, 9, 30), "inactiva"),
                      datetime(2026, 10, 14, 9, 30), "borrada")
    vistas = ocurrencias_visibles(m, datetime(2026, 10, 12), datetime(2026, 10, 15))
    assert vistas == [datetime(2026, 10, 12, 9, 30), datetime(2026, 10, 13, 9, 30)]
    assert estado_ocurrencia(m, datetime(2026, 10, 13, 9, 30)) == "inactiva"
    assert estado_ocurrencia(m, datetime(2026, 10, 12, 9, 30)) == "activa"


def test_inactive_series_shows_every_occurrence_as_inactive():
    m = _daily(activa=False)
    assert estado_ocurrencia(m, datetime(2026, 10, 13, 9, 30)) == "inactiva"
    assert len(ocurrencias_visibles(m, datetime(2026, 10, 12), datetime(2026, 10, 15))) == 3
    assert next_occurrence(m, datetime(2026, 10, 12)) is None


def test_con_excepcion_none_removes_the_mark_and_does_not_mutate_original():
    m = _daily()
    marcado = con_excepcion(m, datetime(2026, 10, 13, 9, 30), "borrada")
    assert m["excepciones"] == {}
    assert con_excepcion(marcado, datetime(2026, 10, 13, 9, 30), None)["excepciones"] == {}


def test_es_serie():
    assert es_serie(_daily())
    assert not es_serie(normalize_meeting({"titulo": "x", "fecha_hora": "2026-10-13T09:30"}))


def test_reunion_editada_keeps_exceptions_unless_the_series_changes():
    original = con_excepcion(_daily(), datetime(2026, 10, 13, 9, 30), "borrada")
    mismo = reunion_editada(original, {**_daily(), "titulo": "Otro nombre"})
    assert mismo["excepciones"] == {"2026-10-13T09:30": "borrada"}
    cambia_hora = reunion_editada(original, {**_daily(), "fecha_hora": "2026-10-12T10:00"})
    assert cambia_hora["excepciones"] == {}
    assert reunion_editada(None, _daily())["excepciones"] == {}
