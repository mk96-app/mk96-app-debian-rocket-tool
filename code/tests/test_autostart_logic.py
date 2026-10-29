from mk96_app_debian_rocket_tool import autostart


def _paths(tmp_path, with_system):
    user = tmp_path / "user" / "app.desktop"
    system = tmp_path / "system.desktop"
    if with_system:
        system.write_text("[Desktop Entry]\n")
    return str(user), str(system)


def test_disabled_by_default_without_any_file(tmp_path):
    user, system = _paths(tmp_path, with_system=False)
    assert autostart.is_enabled(user, system) is False


def test_enabled_when_only_system_file_exists(tmp_path):
    user, system = _paths(tmp_path, with_system=True)
    assert autostart.is_enabled(user, system) is True


def test_enable_writes_user_file(tmp_path):
    user, system = _paths(tmp_path, with_system=False)
    autostart.set_enabled(True, user, system)
    assert autostart.is_enabled(user, system) is True
    assert "Exec=mk96-app-debian-rocket-tool" in open(user).read()


def test_disable_without_system_file_removes_user_file(tmp_path):
    user, system = _paths(tmp_path, with_system=False)
    autostart.set_enabled(True, user, system)
    autostart.set_enabled(False, user, system)
    assert autostart.is_enabled(user, system) is False
    assert not (tmp_path / "user" / "app.desktop").exists()


def test_disable_with_system_file_writes_hidden_override(tmp_path):
    user, system = _paths(tmp_path, with_system=True)
    autostart.set_enabled(False, user, system)
    assert "Hidden=true" in open(user).read()
    assert autostart.is_enabled(user, system) is False


def test_reenable_overrides_hidden(tmp_path):
    user, system = _paths(tmp_path, with_system=True)
    autostart.set_enabled(False, user, system)
    autostart.set_enabled(True, user, system)
    assert autostart.is_enabled(user, system) is True
