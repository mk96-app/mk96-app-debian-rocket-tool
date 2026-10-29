"""Guarda la URL del servidor, el user id y el Personal Access Token de cada servidor
Rocket.Chat configurado en el Secret Service del sistema (GNOME Keyring) vía libsecret.

Cada servidor se identifica por su `servidor_id` (el mismo id no sensible que vive en
config.yaml, en la lista `servidores`). Nunca se guardan credenciales en config.yaml ni en
texto plano: si el Secret Service no está disponible, se falla explícitamente en vez de
hacer fallback inseguro.
"""

import gi

gi.require_version("Secret", "1")
from gi.repository import Secret

SCHEMA = Secret.Schema.new(
    "com.github.markes96.mk96-app-debian-rocket-tool",
    Secret.SchemaFlags.NONE,
    {
        "servidor_id": Secret.SchemaAttributeType.STRING,
        "campo": Secret.SchemaAttributeType.STRING,
    },
)

FIELDS = ("server_url", "user_id", "token")


class SecretStoreUnavailable(Exception):
    """El Secret Service (GNOME Keyring u otro backend libsecret) no responde."""


def save_server_credentials(servidor_id: str, server_url: str, user_id: str, token: str) -> None:
    values = {"server_url": server_url, "user_id": user_id, "token": token}
    try:
        for campo, valor in values.items():
            Secret.password_store_sync(
                SCHEMA,
                {"servidor_id": servidor_id, "campo": campo},
                Secret.COLLECTION_DEFAULT,
                f"Rocket.Chat {server_url} (mk96-app-debian-rocket-tool)",
                valor,
                None,
            )
    except Exception as exc:  # noqa: BLE001 - errores de D-Bus llegan como GLib.Error
        raise SecretStoreUnavailable(str(exc)) from exc


def load_server_credentials(servidor_id: str) -> dict | None:
    try:
        values = {
            campo: Secret.password_lookup_sync(
                SCHEMA, {"servidor_id": servidor_id, "campo": campo}, None
            )
            for campo in FIELDS
        }
    except Exception as exc:  # noqa: BLE001
        raise SecretStoreUnavailable(str(exc)) from exc

    if any(value is None for value in values.values()):
        return None
    return values


def clear_server_credentials(servidor_id: str) -> None:
    try:
        for campo in FIELDS:
            Secret.password_clear_sync(SCHEMA, {"servidor_id": servidor_id, "campo": campo}, None)
    except Exception as exc:  # noqa: BLE001
        raise SecretStoreUnavailable(str(exc)) from exc
