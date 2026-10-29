"""Helpers finos sobre Gio.DBusProxy para el bus de sesión (notificaciones de escritorio).

Copiado del mismo módulo en mk96-app-debian-switchboard (mismo autor): el patrón de
proxy síncrono + traducción de errores GLib no cambia entre proyectos.
"""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib


class ServiceUnavailable(Exception):
    """El servicio D-Bus solicitado no responde o no existe."""


def get_proxy(bus_type, bus_name, object_path, interface_name):
    """Crea un Gio.DBusProxy síncrono. Lanza ServiceUnavailable si falla."""
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            bus_type,
            Gio.DBusProxyFlags.NONE,
            None,
            bus_name,
            object_path,
            interface_name,
            None,
        )
    except GLib.Error as exc:
        raise ServiceUnavailable(f"{interface_name} en {object_path}: {exc}") from exc


def call_sync(proxy, method_name, parameters=None, timeout_msec=3000):
    """Llama a un método D-Bus síncronamente. Traduce errores GLib a ServiceUnavailable."""
    try:
        return proxy.call_sync(
            method_name, parameters, Gio.DBusCallFlags.NONE, timeout_msec, None
        )
    except GLib.Error as exc:
        raise ServiceUnavailable(f"{method_name}: {exc}") from exc
