"""Config no sensible: ~/.config/mk96-app-debian-rocket-tool/config.yaml.

Guarda la lista de servidores configurados (id, nombre visible, cuáles están activos
-conectados, puede haber varios a la vez-), el modo No molestar, las
reglas de sonido (cada una asociada a un servidor_id) y una caché de nombres de sala para
la UI. Las credenciales (URL del servidor, user id, Personal Access Token) viven en
secret_store.py, indexadas por el mismo servidor_id -nunca aquí.
"""

import os
import uuid

import yaml

from mk96_app_debian_rocket_tool.meetings import normalize_meeting
from mk96_app_debian_rocket_tool.quiet_hours import default_quiet_config, normalize_quiet

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "mk96-app-debian-rocket-tool")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")


def default_config() -> dict:
    return {
        "servidores": [],
        "reglas": [],
        "salas_cache": {},
        "reuniones": [],
        "no_molestar": default_quiet_config(),
    }


def normalize_server(raw_server: dict) -> dict:
    return {
        "id": raw_server.get("id") or str(uuid.uuid4()),
        "nombre": raw_server["nombre"],
        "activo": raw_server.get("activo", False),
        "poll_interval_s": raw_server.get("poll_interval_s", 30),
    }


def normalize_rule(raw_rule: dict) -> dict:
    """Rellena los campos opcionales de una regla con sus valores por defecto."""
    return {
        "id": raw_rule.get("id") or str(uuid.uuid4()),
        "servidor_id": raw_rule["servidor_id"],
        "tipo": raw_rule["tipo"],
        "room_id": raw_rule.get("room_id"),
        "room_type": raw_rule.get("room_type"),
        "sonido_id": raw_rule["sonido_id"],
        "etiqueta": raw_rule.get("etiqueta", ""),
        "activa": raw_rule.get("activa", True),
        "mencion_todos": raw_rule.get("mencion_todos", False),
        "repeticion_modo": raw_rule.get("repeticion_modo", "una_vez"),
        "repeticion_n": raw_rule.get("repeticion_n"),
        "repeticion_cada_polls": raw_rule.get("repeticion_cada_polls", 1),
    }


def parse_config(raw_text: str | None) -> dict:
    data = yaml.safe_load(raw_text) if raw_text else None
    data = data or {}

    config = default_config()
    config["salas_cache"] = data.get("salas_cache", {}) or {}
    config["servidores"] = [normalize_server(s) for s in data.get("servidores", []) or []]
    config["reglas"] = [normalize_rule(rule) for rule in data.get("reglas", []) or []]
    config["reuniones"] = [normalize_meeting(m) for m in data.get("reuniones", []) or []]
    config["no_molestar"] = normalize_quiet(data.get("no_molestar"))
    return config


def serialize_config(config: dict) -> str:
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def load_config(path: str = CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        return default_config()
    with open(path, "r", encoding="utf-8") as handle:
        return parse_config(handle.read())


def save_config(config: dict, path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(serialize_config(config))


def get_active_servers(config: dict) -> list:
    """Servidores marcados como conectados: se reconectan al arrancar la aplicación."""
    return [s for s in config["servidores"] if s["activo"]]


def set_server_active(config: dict, servidor_id: str, activo: bool) -> None:
    for server in config["servidores"]:
        if server["id"] == servidor_id:
            server["activo"] = activo


def rules_for_server(config: dict, servidor_id: str) -> list:
    return [rule for rule in config["reglas"] if rule["servidor_id"] == servidor_id]


def find_room_rule(config: dict, servidor_id: str, room_id: str) -> dict | None:
    """Regla de tipo 'sala' ya existente para esa sala/persona en ese servidor, si hay
    alguna -para no dejar dos sonidos apuntando al mismo sitio."""
    return next(
        (
            rule
            for rule in config["reglas"]
            if rule["servidor_id"] == servidor_id
            and rule["tipo"] == "sala"
            and rule["room_id"] == room_id
        ),
        None,
    )
