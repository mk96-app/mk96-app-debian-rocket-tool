from mk96_app_debian_rocket_tool.tray import MAX_RECENT_ITEMS, add_to_recent, remove_from_recent
from mk96_app_debian_rocket_tool.tray import add_pending_meeting, remove_pending_meeting


def test_add_to_recent_inserts_at_front():
    result = add_to_recent([], "Ana", "room1")
    assert result == [{"etiqueta": "Ana", "rid": "room1"}]


def test_add_to_recent_new_room_goes_before_existing():
    existing = [{"etiqueta": "Ana", "rid": "room1"}]
    result = add_to_recent(existing, "Bea", "room2")
    assert result == [
        {"etiqueta": "Bea", "rid": "room2"},
        {"etiqueta": "Ana", "rid": "room1"},
    ]


def test_add_to_recent_same_room_updates_and_moves_to_front_instead_of_duplicating():
    existing = [
        {"etiqueta": "Bea", "rid": "room2"},
        {"etiqueta": "Ana", "rid": "room1"},
    ]
    result = add_to_recent(existing, "Ana (2)", "room1")
    assert result == [
        {"etiqueta": "Ana (2)", "rid": "room1"},
        {"etiqueta": "Bea", "rid": "room2"},
    ]


def test_add_to_recent_caps_at_max_items():
    existing = [{"etiqueta": f"u{i}", "rid": f"room{i}"} for i in range(3)]
    result = add_to_recent(existing, "nuevo", "room-nuevo", max_items=3)
    assert len(result) == 3
    assert result[0] == {"etiqueta": "nuevo", "rid": "room-nuevo"}


def test_remove_from_recent_drops_matching_rid():
    existing = [
        {"etiqueta": "Ana", "rid": "room1"},
        {"etiqueta": "Bea", "rid": "room2"},
    ]
    result = remove_from_recent(existing, "room1")
    assert result == [{"etiqueta": "Bea", "rid": "room2"}]


def test_remove_from_recent_no_match_is_a_no_op():
    existing = [{"etiqueta": "Ana", "rid": "room1"}]
    result = remove_from_recent(existing, "room-inexistente")
    assert result == existing


def test_add_pending_meeting_inserts_at_front():
    result = add_pending_meeting([], {"id": "m1", "titulo": "Sync", "enlace": None})
    assert result == [{"id": "m1", "titulo": "Sync", "enlace": None}]


def test_add_pending_meeting_same_id_updates_and_moves_to_front_instead_of_duplicating():
    existing = [{"id": "m1", "titulo": "Sync", "enlace": None}]
    result = add_pending_meeting(existing, {"id": "m1", "titulo": "Sync (movida)", "enlace": "https://x"})
    assert result == [{"id": "m1", "titulo": "Sync (movida)", "enlace": "https://x"}]


def test_add_pending_meeting_same_id_moves_to_front_over_other_entries():
    existing = [
        {"id": "m2", "titulo": "Standup", "enlace": None},
        {"id": "m1", "titulo": "Sync", "enlace": None},
    ]
    result = add_pending_meeting(existing, {"id": "m1", "titulo": "Sync (movida)", "enlace": "https://x"})
    assert result == [
        {"id": "m1", "titulo": "Sync (movida)", "enlace": "https://x"},
        {"id": "m2", "titulo": "Standup", "enlace": None},
    ]


def test_add_pending_meeting_different_id_stacks_on_front():
    existing = [{"id": "m1", "titulo": "Sync", "enlace": None}]
    result = add_pending_meeting(existing, {"id": "m2", "titulo": "Standup", "enlace": "https://x"})
    assert result == [
        {"id": "m2", "titulo": "Standup", "enlace": "https://x"},
        {"id": "m1", "titulo": "Sync", "enlace": None},
    ]


def test_add_pending_meeting_caps_the_list_at_max_items():
    existing = [{"id": f"m{i}", "titulo": f"R{i}", "enlace": None} for i in range(MAX_RECENT_ITEMS)]
    result = add_pending_meeting(existing, {"id": "nuevo", "titulo": "Nueva", "enlace": None})
    assert len(result) == MAX_RECENT_ITEMS
    assert result[0]["id"] == "nuevo"
    assert all(entry["id"] != f"m{MAX_RECENT_ITEMS - 1}" for entry in result)


def test_remove_pending_meeting_drops_matching_id():
    existing = [
        {"id": "m1", "titulo": "Sync", "enlace": None},
        {"id": "m2", "titulo": "Standup", "enlace": None},
    ]
    result = remove_pending_meeting(existing, "m1")
    assert result == [{"id": "m2", "titulo": "Standup", "enlace": None}]


def test_remove_pending_meeting_no_match_is_a_no_op():
    existing = [{"id": "m1", "titulo": "Sync", "enlace": None}]
    assert remove_pending_meeting(existing, "m-inexistente") == existing


# -- línea(s) de estado de conexión ---------------------------------------------------

from mk96_app_debian_rocket_tool.tray import build_status_lines


def _conn(nombre="Trabajo", connected=True, username=None, error=None):
    return {"nombre": nombre, "connected": connected, "username": username, "error": error}


def test_status_lines_without_servers_says_disconnected():
    assert build_status_lines([]) == ["Desconectado"]


def test_status_lines_single_server_shows_only_the_user():
    assert build_status_lines([_conn(username="jane.doe")]) == ["Conectado: @jane.doe"]


def test_status_lines_several_servers_add_server_name():
    lines = build_status_lines([_conn("A", username="ana"), _conn("B", username="bea")])
    assert lines == ["Conectado: @ana · A", "Conectado: @bea · B"]


def test_status_lines_connecting_until_username_is_known():
    assert build_status_lines([_conn()]) == ["Conectando a Trabajo..."]


def test_status_lines_error_shows_server_and_message():
    lines = build_status_lines([_conn(connected=False, error="Credenciales rechazadas")])
    assert lines == ["Trabajo: Credenciales rechazadas"]


def test_status_lines_error_without_message_has_fallback():
    assert build_status_lines([_conn(connected=False)]) == ["Trabajo: sin conexión"]
