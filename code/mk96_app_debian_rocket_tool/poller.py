"""Polling sobre la REST API de Rocket.Chat: sustituye a la antigua conexión
WebSocket/DDP (rc_client.py, eliminado). Ver docs/superpowers/specs/2026-08-14-rest-polling-design.md
para el porqué del cambio.

Las funciones de este módulo son puras (sin red/GLib) y testeables directamente; la
clase Poller (más abajo) las orquesta con efectos -mismo patrón que rc_client.py
separaba build_*/extract_* de RocketChatClient.
"""

import logging
from datetime import datetime, timezone

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from mk96_app_debian_rocket_tool.async_utils import run_in_thread
from mk96_app_debian_rocket_tool.rest_client import AuthError, RestApiError, describe_connection_error
from mk96_app_debian_rocket_tool.rules import match_rule

log = logging.getLogger(__name__)

# Tras un fallo de red se saltan ticks (reintento exponencial) para no martillear un
# servidor caído cada 15 s; con el intervalo por defecto (30 s) el tope es ~5 min.
MAX_BACKOFF_TICKS = 10
# Usernames con los que Rocket.Chat representa @all y @here en la lista de menciones.
MENTION_ALL_NAMES = frozenset({"all", "here"})


def is_message_read(message_ts: str | None, last_seen_ts: str | None) -> bool:
    """Un mensaje se considera leído si su timestamp no es posterior al `ls`
    (last seen) de la suscripción -ese campo lo actualiza cualquier cliente real de
    Rocket.Chat (web/móvil/desktop) al abrir la sala, nunca nuestras propias
    peticiones de solo lectura."""
    if not message_ts or not last_seen_ts:
        return False
    return message_ts <= last_seen_ts


def should_fetch_room(rid: str, reglas_activas: list, hay_mencion_activa: bool) -> bool:
    """Decide si merece la pena pedir el historial de una sala: solo si hay una
    regla de sala para ese rid concreto, o si hay una regla de mención activa (que
    podría aplicar a cualquier sala)."""
    if hay_mencion_activa:
        return True
    return any(r["tipo"] == "sala" and r["room_id"] == rid for r in reglas_activas)


def backoff_ticks(failures: int) -> int:
    """Ticks a saltar tras `failures` fallos seguidos: 0, 1, 3, 7, ... hasta el tope."""
    if failures <= 0:
        return 0
    return min(2 ** (failures - 1) - 1, MAX_BACKOFF_TICKS)


def should_repeat(pending: dict, regla: dict, tick_actual: int) -> bool:
    """Decide si toca volver a sonar en este tick para un aviso pendiente. `pending`
    trae al menos `count` (sonidos ya emitidos para este aviso) y `last_sound_tick`
    (tick en el que sonó la última vez)."""
    modo = regla.get("repeticion_modo", "una_vez")
    if modo == "una_vez":
        return False
    if modo == "n_veces" and pending["count"] >= regla.get("repeticion_n", 1):
        return False
    cada_polls = regla.get("repeticion_cada_polls", 1)
    return (tick_actual - pending["last_sound_tick"]) >= cada_polls


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _empty_outcome() -> dict:
    return {
        "connected": False,
        "auth_error": False,
        "error": None,
        "username": None,
        "events": [],
        "rooms_read": [],
    }


class Poller:
    """Polling periódico sobre la REST API de Rocket.Chat. Las peticiones se hacen en un
    hilo (un servidor lento no congela la bandeja); `on_event(event)`,
    `on_status_changed(bool)`, `on_room_read(rid)` y `on_auth_error()` siempre se llaman
    en el hilo principal. Solo hay un sondeo en vuelo a la vez, así que el estado
    interno (cursores, pendientes) solo lo toca ese hilo."""

    def __init__(
        self,
        rest_client,
        poll_interval_s: int,
        get_reglas_activas,
        on_event,
        on_status_changed,
        on_room_read=None,
        on_auth_error=None,
    ):
        self._rest_client = rest_client
        self._poll_interval_s = poll_interval_s
        self._get_reglas_activas = get_reglas_activas
        self._on_event = on_event
        self._on_status_changed = on_status_changed
        self._on_room_read = on_room_read or (lambda rid: None)
        self._on_auth_error = on_auth_error or (lambda: None)

        self._tick = 0
        self._cursors = {}  # rid -> ts (str) del último mensaje ya procesado
        self._pending = {}  # rid -> {"event", "regla_id", "count", "last_sound_tick", "message_ts"}
        # rid -> ts del último mensaje notificado en esa sala, esté o no en modo repetición
        # -se usa solo para saber cuándo avisar de que ya se ha leído (on_room_read).
        self._notified = {}
        # rid -> sub de salas cuyo historial falló: el delta de suscripciones no las
        # volvería a traer hasta que haya actividad nueva, así que se reintentan aparte.
        self._retry = {}
        self._last_poll_iso = None
        self._baseline_done = False
        self._timeout_id = None
        self._connected = None  # None = aún no se sabe; evita notificar en cada tick
        self._busy = False
        self._stopped = False
        self._failures = 0
        self._skip_ticks = 0
        # Para que la interfaz muestre quién está conectado o por qué falla.
        self.username = None
        self.last_error = None

    def start(self) -> None:
        self._stopped = False
        self._tick_poll()
        self._timeout_id = GLib.timeout_add_seconds(self._poll_interval_s, self._tick_poll)

    def stop(self) -> None:
        self._stopped = True
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _set_connected(self, connected: bool) -> None:
        # on_status_changed reconstruye la UI de ajustes si está abierta -solo debe
        # llamarse en una transición real, nunca en cada tick (si no, cada poll
        # tiraría cualquier cambio sin guardar en el formulario abierto).
        if connected != self._connected:
            self._connected = connected
            self._on_status_changed(connected)

    def _tick_poll(self) -> bool:
        if self._stopped or self._busy:
            return GLib.SOURCE_CONTINUE
        if self._skip_ticks > 0:
            self._skip_ticks -= 1
            return GLib.SOURCE_CONTINUE

        self._busy = True
        # Las reglas se leen aquí, en el hilo principal, no desde el hilo de red.
        reglas_activas = [r for r in self._get_reglas_activas() if r.get("activa", True)]
        run_in_thread(lambda: self._poll_once(reglas_activas), self._on_poll_done)
        return GLib.SOURCE_CONTINUE

    def _on_poll_done(self, outcome, error) -> None:
        self._busy = False
        if self._stopped:
            return
        if error is not None:
            log.warning("Fallo inesperado en el sondeo: %r", error)
            outcome = {**_empty_outcome(), "error": f"Error inesperado: {error}"}

        if not outcome["connected"]:
            self.last_error = outcome["error"]
            if outcome["auth_error"]:
                # Solo on_auth_error (aviso específico), no el genérico "sin conexión".
                self.stop()
                self._connected = False
                self._on_auth_error()
                return
            self._failures += 1
            self._skip_ticks = backoff_ticks(self._failures)
            self._set_connected(False)
            return

        self._failures = 0
        self.username = outcome["username"]
        self.last_error = None
        self._set_connected(True)
        for rid in outcome["rooms_read"]:
            self._on_room_read(rid)
        for event in outcome["events"]:
            self._on_event(event)

    def _poll_once(self, reglas_activas: list) -> dict:
        """Se ejecuta en el hilo de red; no llama a ningún callback, devuelve qué hacer."""
        outcome = _empty_outcome()
        poll_started = _now_iso()
        try:
            subs = self._rest_client.list_subscriptions(self._last_poll_iso)
            own_username = self._rest_client.get_own_username()
        except AuthError as exc:
            outcome["auth_error"] = True
            outcome["error"] = describe_connection_error(exc)
            return outcome
        except RestApiError as exc:
            outcome["error"] = describe_connection_error(exc)
            return outcome

        outcome["connected"] = True
        outcome["username"] = own_username
        # El instante se toma ANTES de pedir las suscripciones: un cambio ocurrido
        # durante la petición se vuelve a ver en el siguiente delta, no se pierde.
        self._last_poll_iso = poll_started
        self._tick += 1

        if not self._baseline_done:
            for sub in subs:
                rid = sub.get("rid")
                if rid:
                    self._cursors[rid] = sub.get("ls") or self._last_poll_iso
            self._baseline_done = True
            return outcome

        subs_by_rid = {sub["rid"]: sub for sub in subs if sub.get("rid")}
        for rid, sub in self._retry.items():
            subs_by_rid.setdefault(rid, sub)
        self._retry = {}

        hay_mencion_activa = any(r["tipo"] == "mencion" for r in reglas_activas)
        for rid, sub in subs_by_rid.items():
            self._clear_pending_if_read(rid, sub, outcome)
            if should_fetch_room(rid, reglas_activas, hay_mencion_activa):
                self._process_room(rid, sub, reglas_activas, own_username, outcome)

        self._fire_due_reminders(reglas_activas, outcome)
        return outcome

    def _clear_pending_if_read(self, rid: str, sub: dict, outcome: dict) -> None:
        pending = self._pending.get(rid)
        if pending is not None and is_message_read(pending["message_ts"], sub.get("ls")):
            del self._pending[rid]

        notified_ts = self._notified.get(rid)
        if notified_ts is not None and is_message_read(notified_ts, sub.get("ls")):
            del self._notified[rid]
            outcome["rooms_read"].append(rid)

    def _process_room(
        self, rid: str, sub: dict, reglas_activas: list, own_username, outcome: dict
    ) -> None:
        room_type = sub.get("t", "c")
        cursor = self._cursors.get(rid)
        try:
            messages = self._rest_client.room_history_since(rid, room_type, cursor)
        except RestApiError:
            self._retry[rid] = sub
            return

        for message in messages:
            ts = message.get("ts")
            if ts:
                self._cursors[rid] = ts
            if message.get("sender") == own_username:
                continue

            mentions = message.get("mentions") or []
            event = {
                "rid": rid,
                "room_type": room_type,
                "mentioned": own_username in mentions,
                "mentioned_all": bool(MENTION_ALL_NAMES.intersection(mentions)),
                "sender": message.get("sender"),
                "text": message.get("text"),
            }
            rule = match_rule(event, reglas_activas)
            if rule is None or is_message_read(ts, sub.get("ls")):
                continue

            outcome["events"].append(event)
            self._notified[rid] = ts
            if rule.get("repeticion_modo", "una_vez") != "una_vez":
                self._pending[rid] = {
                    "event": event,
                    "regla_id": rule["id"],
                    "count": 1,
                    "last_sound_tick": self._tick,
                    "message_ts": ts,
                }

    def _fire_due_reminders(self, reglas_activas: list, outcome: dict) -> None:
        reglas_por_id = {r["id"]: r for r in reglas_activas}
        for rid in list(self._pending.keys()):
            pending = self._pending[rid]
            regla = reglas_por_id.get(pending["regla_id"])
            if regla is None:
                del self._pending[rid]
                continue
            if not should_repeat(pending, regla, self._tick):
                continue
            outcome["events"].append(pending["event"])
            pending["count"] += 1
            pending["last_sound_tick"] = self._tick
