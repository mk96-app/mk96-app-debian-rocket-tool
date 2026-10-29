from datetime import datetime, time

from mk96_app_debian_rocket_tool.quiet_hours import (
    default_quiet_config,
    has_manual_silence,
    in_schedule,
    is_quiet,
    normalize_quiet,
    parse_hhmm,
    quiet_status_text,
    silence_until,
)

NOW = datetime(2026, 10, 13, 12, 0)


def _config(**overrides):
    return {**default_quiet_config(), **overrides}


def test_parse_hhmm():
    assert parse_hhmm("08:30") == time(8, 30)
    assert parse_hhmm("25:00") is None
    assert parse_hhmm("abc") is None
    assert parse_hhmm(None) is None


def test_in_schedule_same_day_range():
    assert in_schedule(time(9), time(17), time(12)) is True
    assert in_schedule(time(9), time(17), time(17)) is False


def test_in_schedule_crossing_midnight():
    assert in_schedule(time(22), time(8), time(23)) is True
    assert in_schedule(time(22), time(8), time(3)) is True
    assert in_schedule(time(22), time(8), time(12)) is False


def test_in_schedule_equal_bounds_is_never_quiet():
    assert in_schedule(time(8), time(8), time(8)) is False


def test_default_config_is_not_quiet():
    assert is_quiet(default_quiet_config(), NOW) is False


def test_manual_silence_until_future_is_quiet_and_past_is_not():
    assert is_quiet(_config(silenciado_hasta="2026-10-13T13:00:00"), NOW) is True
    assert is_quiet(_config(silenciado_hasta="2026-10-13T11:00:00"), NOW) is False


def test_manual_indefinite_is_quiet():
    assert is_quiet(_config(silenciado_hasta="indefinido"), NOW) is True


def test_invalid_manual_value_is_ignored():
    assert is_quiet(_config(silenciado_hasta="basura"), NOW) is False


def test_schedule_only_applies_when_enabled():
    config = _config(desde="11:00", hasta="13:00")
    assert is_quiet(config, NOW) is False
    config["horario_activo"] = True
    assert is_quiet(config, NOW) is True


def test_silence_until_options():
    assert silence_until(NOW, "1h") == "2026-10-13T13:00:00"
    assert silence_until(NOW, "4h") == "2026-10-13T16:00:00"
    assert silence_until(NOW, "indefinido") == "indefinido"
    assert silence_until(NOW, "off") is None


def test_status_text():
    assert quiet_status_text(default_quiet_config(), NOW) is None
    assert "13:00" in quiet_status_text(_config(silenciado_hasta="2026-10-13T13:00:00"), NOW)
    assert "desactives" in quiet_status_text(_config(silenciado_hasta="indefinido"), NOW)
    scheduled = _config(horario_activo=True, desde="11:00", hasta="13:00")
    assert "13:00" in quiet_status_text(scheduled, NOW)


def test_has_manual_silence_ignores_schedule():
    scheduled = _config(horario_activo=True, desde="11:00", hasta="13:00")
    assert has_manual_silence(scheduled, NOW) is False
    assert has_manual_silence(_config(silenciado_hasta="indefinido"), NOW) is True


def test_normalize_quiet_fills_defaults_and_rejects_bad_times():
    assert normalize_quiet(None) == default_quiet_config()
    config = normalize_quiet({"horario_activo": True, "desde": "99:99", "hasta": "07:15"})
    assert config["horario_activo"] is True
    assert config["desde"] == "22:00"
    assert config["hasta"] == "07:15"
