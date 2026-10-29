from mk96_app_debian_rocket_tool.alert_dialog import repeat_values, validate_alert


def test_room_alert_requires_a_room():
    title, _ = validate_alert("sala", None, "s1", False)
    assert "sala" in title.lower()


def test_room_alert_rejects_duplicate_room():
    title, _ = validate_alert("sala", ("r1", "General"), "s1", True)
    assert "Ya existe" in title


def test_alert_requires_a_sound():
    title, _ = validate_alert("sala", ("r1", "General"), None, False)
    assert "sonido" in title.lower()
    assert validate_alert("mencion", None, None, False)[0] == title


def test_valid_alerts_have_no_error():
    assert validate_alert("sala", ("r1", "General"), "s1", False) is None
    assert validate_alert("mencion", None, "s1", False) is None


def test_repeat_values():
    assert repeat_values("una_vez", 5, 7) == ("una_vez", None, 1)
    assert repeat_values("n_veces", 5, 7) == ("n_veces", 5, 7)
    assert repeat_values("infinito", 5, 7) == ("infinito", None, 7)
