from mk96_app_debian_rocket_tool.config import (
    default_config,
    find_room_rule,
    get_active_servers,
    normalize_rule,
    normalize_server,
    parse_config,
    rules_for_server,
    serialize_config,
    set_server_active,
)
from mk96_app_debian_rocket_tool.meetings import normalize_meeting


def test_default_config_is_empty():
    config = default_config()
    assert config["servidores"] == []
    assert config["reglas"] == []
    assert config["salas_cache"] == {}
    assert config["reuniones"] == []


def test_parse_config_empty_text_returns_default():
    assert parse_config("") == default_config()


def test_parse_config_none_returns_default():
    assert parse_config(None) == default_config()


def test_parse_config_normalizes_servers():
    raw = """
servidores:
  - nombre: Trabajo
    activo: true
"""
    config = parse_config(raw)
    server = config["servidores"][0]
    assert server["nombre"] == "Trabajo"
    assert server["activo"] is True
    assert "id" in server and server["id"]


def test_parse_config_normalizes_rules_with_servidor_id():
    raw = """
reglas:
  - servidor_id: s1
    tipo: sala
    room_id: abc123
    sonido_id: cat
"""
    config = parse_config(raw)
    rule = config["reglas"][0]
    assert rule["servidor_id"] == "s1"
    assert rule["activa"] is True
    assert rule["etiqueta"] == ""
    assert "id" in rule and rule["id"]


def test_normalize_rule_keeps_explicit_values():
    rule = normalize_rule(
        {"servidor_id": "s1", "tipo": "mencion", "sonido_id": "bell", "activa": False, "id": "m1"}
    )
    assert rule == {
        "id": "m1",
        "servidor_id": "s1",
        "tipo": "mencion",
        "sonido_id": "bell",
        "etiqueta": "",
        "activa": False,
        "mencion_todos": False,
        "room_id": None,
        "room_type": None,
        "repeticion_modo": "una_vez",
        "repeticion_n": None,
        "repeticion_cada_polls": 1,
    }


def test_normalize_rule_defaults_repeticion_to_una_vez():
    rule = normalize_rule({"servidor_id": "s1", "tipo": "sala", "room_id": "r1", "sonido_id": "cat"})
    assert rule["repeticion_modo"] == "una_vez"
    assert rule["repeticion_n"] is None
    assert rule["repeticion_cada_polls"] == 1


def test_normalize_rule_keeps_explicit_repeticion_values():
    rule = normalize_rule(
        {
            "servidor_id": "s1",
            "tipo": "sala",
            "room_id": "r1",
            "sonido_id": "cat",
            "repeticion_modo": "n_veces",
            "repeticion_n": 3,
            "repeticion_cada_polls": 2,
        }
    )
    assert rule["repeticion_modo"] == "n_veces"
    assert rule["repeticion_n"] == 3
    assert rule["repeticion_cada_polls"] == 2


def test_normalize_server_keeps_explicit_values():
    server = normalize_server(
        {"id": "s1", "nombre": "Personal", "activo": True, "poll_interval_s": 60}
    )
    assert server == {"id": "s1", "nombre": "Personal", "activo": True, "poll_interval_s": 60}


def test_normalize_server_defaults_activo_to_false():
    server = normalize_server({"id": "s1", "nombre": "Personal"})
    assert server["activo"] is False


def test_normalize_server_defaults_poll_interval_to_30():
    server = normalize_server({"id": "s1", "nombre": "Personal"})
    assert server["poll_interval_s"] == 30


def test_normalize_server_keeps_explicit_poll_interval():
    server = normalize_server({"id": "s1", "nombre": "Personal", "poll_interval_s": 15})
    assert server["poll_interval_s"] == 15


def test_get_active_servers_empty_when_no_servers():
    assert get_active_servers(default_config()) == []


def test_get_active_servers_returns_all_flagged_ones():
    config = default_config()
    config["servidores"] = [
        normalize_server({"id": "s1", "nombre": "Trabajo", "activo": True}),
        normalize_server({"id": "s2", "nombre": "Personal", "activo": True}),
        normalize_server({"id": "s3", "nombre": "Otro", "activo": False}),
    ]
    assert [s["id"] for s in get_active_servers(config)] == ["s1", "s2"]


def test_set_server_active_only_touches_that_server():
    config = default_config()
    config["servidores"] = [
        normalize_server({"id": "s1", "nombre": "Trabajo", "activo": True}),
        normalize_server({"id": "s2", "nombre": "Personal", "activo": False}),
    ]
    set_server_active(config, "s2", True)
    assert [s["activo"] for s in config["servidores"]] == [True, True]
    set_server_active(config, "s1", False)
    assert [s["activo"] for s in config["servidores"]] == [False, True]


def test_parse_config_fills_quiet_hours_defaults():
    assert parse_config("")["no_molestar"]["horario_activo"] is False


def test_parse_config_reads_quiet_hours():
    config = parse_config("no_molestar:\n  horario_activo: true\n  desde: '23:00'\n")
    assert config["no_molestar"]["horario_activo"] is True
    assert config["no_molestar"]["desde"] == "23:00"
    assert config["no_molestar"]["hasta"] == "08:00"


def test_normalize_rule_mencion_todos_defaults_to_false():
    rule = normalize_rule({"servidor_id": "s1", "tipo": "mencion", "sonido_id": "x"})
    assert rule["mencion_todos"] is False


def test_rules_for_server_filters_by_servidor_id():
    config = default_config()
    config["reglas"] = [
        normalize_rule({"servidor_id": "s1", "tipo": "sala", "room_id": "r1", "sonido_id": "cat"}),
        normalize_rule({"servidor_id": "s2", "tipo": "sala", "room_id": "r2", "sonido_id": "dog"}),
    ]
    result = rules_for_server(config, "s1")
    assert len(result) == 1
    assert result[0]["room_id"] == "r1"


def test_find_room_rule_returns_matching_rule():
    config = default_config()
    config["reglas"] = [
        normalize_rule({"servidor_id": "s1", "tipo": "sala", "room_id": "r1", "sonido_id": "cat"}),
    ]
    found = find_room_rule(config, "s1", "r1")
    assert found is not None
    assert found["sonido_id"] == "cat"


def test_find_room_rule_returns_none_when_no_match():
    config = default_config()
    config["reglas"] = [
        normalize_rule({"servidor_id": "s1", "tipo": "sala", "room_id": "r1", "sonido_id": "cat"}),
    ]
    assert find_room_rule(config, "s1", "r2") is None


def test_find_room_rule_ignores_other_servers():
    config = default_config()
    config["reglas"] = [
        normalize_rule({"servidor_id": "s2", "tipo": "sala", "room_id": "r1", "sonido_id": "cat"}),
    ]
    assert find_room_rule(config, "s1", "r1") is None


def test_find_room_rule_ignores_mention_rules():
    config = default_config()
    config["reglas"] = [
        normalize_rule({"servidor_id": "s1", "tipo": "mencion", "sonido_id": "bell"}),
    ]
    assert find_room_rule(config, "s1", "r1") is None


def test_serialize_and_parse_roundtrip():
    config = default_config()
    config["servidores"].append(normalize_server({"nombre": "Trabajo", "activo": True}))
    servidor_id = config["servidores"][0]["id"]
    config["reglas"].append(
        normalize_rule({"servidor_id": servidor_id, "tipo": "sala", "room_id": "r1", "sonido_id": "dog"})
    )
    config["salas_cache"]["r1"] = "Sala de prueba"

    text = serialize_config(config)
    assert parse_config(text) == config


def test_default_config_includes_empty_reuniones():
    assert default_config()["reuniones"] == []


def test_parse_config_normalizes_meetings():
    raw = """
reuniones:
  - titulo: Sync semanal
    fecha_hora: "2026-08-20T10:00"
"""
    config = parse_config(raw)
    meeting = config["reuniones"][0]
    assert meeting["titulo"] == "Sync semanal"
    assert meeting["repeticion_modo"] == "ninguna"
    assert "id" in meeting and meeting["id"]


def test_serialize_and_parse_roundtrip_includes_meetings():
    config = default_config()
    config["reuniones"].append(
        normalize_meeting(
            {"titulo": "Sync", "fecha_hora": "2026-08-20T10:00", "repeticion_fin": "2026-12-31"}
        )
    )
    text = serialize_config(config)
    assert parse_config(text) == config
