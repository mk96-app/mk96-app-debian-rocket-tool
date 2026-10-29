"""Arranque automático con la sesión, por usuario.

El paquete .deb puede instalar /etc/xdg/autostart/<app>.desktop (pregunta de debconf).
Este módulo lo gestiona desde Ajustes sin necesitar root: escribe en
~/.config/autostart/, que tiene prioridad sobre el de sistema. Para desactivar un
arranque que viene del sistema se escribe un override con `Hidden=true`.
"""

import os

DESKTOP_NAME = "mk96-app-debian-rocket-tool.desktop"
USER_AUTOSTART_PATH = os.path.join(os.path.expanduser("~"), ".config", "autostart", DESKTOP_NAME)
SYSTEM_AUTOSTART_PATH = os.path.join("/etc/xdg/autostart", DESKTOP_NAME)

_ENABLED_ENTRY = """[Desktop Entry]
Type=Application
Name=MK96 Debian Rocket Tool
Comment=Sonidos distintivos para chats especiales de Rocket.Chat
Exec=mk96-app-debian-rocket-tool
Icon=mk96-app-debian-rocket-tool
Terminal=false
X-GNOME-Autostart-enabled=true
"""

_DISABLED_ENTRY = """[Desktop Entry]
Type=Application
Name=MK96 Debian Rocket Tool
Hidden=true
"""


def _read_keys(path: str) -> dict:
    keys = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                keys[key.strip()] = value.strip().lower()
    return keys


def is_enabled(user_path: str = USER_AUTOSTART_PATH, system_path: str = SYSTEM_AUTOSTART_PATH) -> bool:
    if os.path.exists(user_path):
        try:
            keys = _read_keys(user_path)
        except OSError:
            return False
        return keys.get("Hidden") != "true" and keys.get("X-GNOME-Autostart-enabled") != "false"
    return os.path.exists(system_path)


def set_enabled(
    enabled: bool,
    user_path: str = USER_AUTOSTART_PATH,
    system_path: str = SYSTEM_AUTOSTART_PATH,
) -> None:
    if enabled:
        content = _ENABLED_ENTRY
    elif os.path.exists(system_path):
        content = _DISABLED_ENTRY
    else:
        if os.path.exists(user_path):
            os.remove(user_path)
        return
    os.makedirs(os.path.dirname(user_path), exist_ok=True)
    with open(user_path, "w", encoding="utf-8") as handle:
        handle.write(content)
