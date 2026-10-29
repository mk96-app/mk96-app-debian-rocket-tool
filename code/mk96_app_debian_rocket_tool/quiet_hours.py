"""Modo No molestar: silencio manual temporal (desde la bandeja) y horario silencioso
recurrente (desde Ajustes). Lógica pura, sin GLib/GTK.

Solo afecta a los avisos de chats de Rocket.Chat: durante el silencio no suena ni se
muestra notificación de escritorio, pero el chat sigue apareciendo en la bandeja. Los
recordatorios de reuniones no se silencian.

Config (`no_molestar` en config.yaml):
  silenciado_hasta: None | "indefinido" | fecha ISO local (silencio manual)
  horario_activo:   bool
  desde / hasta:    "HH:MM"; si desde > hasta el tramo cruza la medianoche
"""

from datetime import datetime, time, timedelta

INDEFINIDO = "indefinido"
DURACIONES = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}


def default_quiet_config() -> dict:
    return {
        "silenciado_hasta": None,
        "horario_activo": False,
        "desde": "22:00",
        "hasta": "08:00",
    }


def parse_hhmm(text) -> time | None:
    try:
        hours, minutes = str(text).split(":")
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return None


def normalize_quiet(raw: dict | None) -> dict:
    raw = raw or {}
    config = default_quiet_config()
    config["silenciado_hasta"] = raw.get("silenciado_hasta")
    config["horario_activo"] = bool(raw.get("horario_activo", False))
    for key in ("desde", "hasta"):
        if parse_hhmm(raw.get(key)) is not None:
            config[key] = raw[key]
    return config


def in_schedule(desde: time, hasta: time, ahora: time) -> bool:
    if desde == hasta:
        return False
    if desde < hasta:
        return desde <= ahora < hasta
    return ahora >= desde or ahora < hasta


def _manual_until(config: dict, ahora: datetime):
    """None si no hay silencio manual vigente; INDEFINIDO o el datetime en que acaba."""
    value = config.get("silenciado_hasta")
    if value == INDEFINIDO:
        return INDEFINIDO
    if not value:
        return None
    try:
        until = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return until if until > ahora else None


def is_quiet(config: dict, ahora: datetime) -> bool:
    if _manual_until(config, ahora) is not None:
        return True
    if config.get("horario_activo"):
        desde, hasta = parse_hhmm(config.get("desde")), parse_hhmm(config.get("hasta"))
        if desde is not None and hasta is not None:
            return in_schedule(desde, hasta, ahora.time())
    return False


def silence_until(ahora: datetime, duracion: str) -> str | None:
    """Valor de `silenciado_hasta` para una opción del menú: "1h", "4h", "indefinido"
    u "off" (quita el silencio manual)."""
    if duracion == INDEFINIDO:
        return INDEFINIDO
    if duracion in DURACIONES:
        return (ahora + DURACIONES[duracion]).isoformat(timespec="seconds")
    return None


def quiet_status_text(config: dict, ahora: datetime) -> str | None:
    """Texto para la bandeja, o None si no hay silencio en este momento."""
    manual = _manual_until(config, ahora)
    if manual == INDEFINIDO:
        return "No molestar (hasta que lo desactives)"
    if manual is not None:
        return f"No molestar hasta las {manual.strftime('%H:%M')}"
    if is_quiet(config, ahora):
        return f"Horario silencioso (hasta las {config['hasta']})"
    return None


def has_manual_silence(config: dict, ahora: datetime) -> bool:
    return _manual_until(config, ahora) is not None
