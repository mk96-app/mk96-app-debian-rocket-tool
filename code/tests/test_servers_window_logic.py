from mk96_app_debian_rocket_tool.servers_window import server_status_text, probe_ok_text


def test_connected_with_username_is_green():
    assert server_status_text("conectado", "jane.doe") == (
        "Conexión abierta:\n@jane.doe",
        True,
    )


def test_connected_without_username_yet_is_neutral():
    assert server_status_text("conectado", None) == ("Conectando...", None)


def test_error_shows_message_in_red():
    assert server_status_text("error", "Credenciales rechazadas") == ("Credenciales rechazadas", False)


def test_error_without_message_has_fallback():
    assert server_status_text("error", None) == ("Sin conexión.", False)


def test_disconnected_shows_grey_message():
    assert server_status_text("desconectado", None) == ("Conexión cerrada", "gris")


def test_unknown_status_shows_nothing():
    assert server_status_text(None, None) == ("", None)


def test_test_connection_message_has_no_word_usuario():
    assert probe_ok_text("jane.doe") == "Conexión correcta: @jane.doe"


from mk96_app_debian_rocket_tool.servers_window import delete_confirmation_text


def test_delete_confirmation_mentions_server_and_rule_count():
    titulo, cuerpo = delete_confirmation_text("Trabajo", 3)
    assert "Trabajo" in titulo
    assert "3 reglas" in cuerpo and "credenciales" in cuerpo


def test_delete_confirmation_singular_and_none():
    assert "su regla de alerta" in delete_confirmation_text("A", 1)[1]
    assert "reglas" not in delete_confirmation_text("A", 1)[1]
    assert "reglas" not in delete_confirmation_text("A", 0)[1]
