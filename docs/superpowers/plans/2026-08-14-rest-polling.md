# Sustitución de WS/DDP por polling REST — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir `rc_client.py` (WebSocket/DDP) por un nuevo `poller.py` que usa polling sobre la REST API oficial de Rocket.Chat, con intervalo configurable por servidor y repetición de aviso configurable por regla (una vez / N veces / infinito hasta que se lea).

**Architecture:** Un temporizador GLib llama periódicamente a `subscriptions.get` (modo delta), filtra las salas relevantes según las reglas activas, pide el historial nuevo de esas salas (`channels.history`/`im.history` con cursor `oldest`), decide si un mensaje ya fue leído comparando su `ts` contra el `ls` de la suscripción, y dispara `on_event` (mismo camino que ya usa `app.py`) la primera vez y en cada repetición que corresponda según la config de la regla.

**Tech Stack:** Python 3.10+, PyGObject (`GLib`), `urllib` (ya usado en `rest_client.py`), `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-14-rest-polling-design.md`

## Global Constraints

- Este directorio **no es un repositorio git** (`git status` falla con "no es un repositorio git"). Todos los pasos de "Commit" de la plantilla estándar se omiten en este plan — cada tarea termina en su lugar con "verificar que toda la suite de tests pasa".
- Estilo del proyecto: lógica pura testeable sin mocks de red/D-Bus/GTK, separada de las clases con efectos (igual que `rc_client.py` ya hacía con `build_*`/`extract_*` vs `RocketChatClient`). Mantener ese patrón en `poller.py`.
- Los tests viven en `code/tests/` y se ejecutan con `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest` (ver `pyproject.toml`: `testpaths = ["tests"]`).
- Los timestamps de Rocket.Chat (`ts` de mensaje, `ls` de suscripción) son cadenas ISO-8601 UTC (`"2026-08-14T10:00:00.000Z"`) — comparables lexicográficamente como strings, sin necesidad de parsear a `datetime` para decidir orden.
- Todo el código nuevo/modificado sigue el estilo ya presente: type hints simples (`str | None`), docstrings breves solo donde aportan un "por qué" no obvio, sin comentarios que expliquen el "qué".

---

### Task 1: Modelo de datos — intervalo de poll y repetición en `config.py`

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/config.py:22-41` (`normalize_server`, `normalize_rule`)
- Test: `code/tests/test_config_logic.py`

**Interfaces:**
- Produces: `normalize_server(raw_server)` ahora incluye `poll_interval_s` (int, uno de 15/30/60, por defecto 30). `normalize_rule(raw_rule)` ahora incluye `repeticion_modo` (`"una_vez"|"n_veces"|"infinito"`, por defecto `"una_vez"`), `repeticion_n` (`int | None`, por defecto `None`), `repeticion_cada_polls` (`int`, por defecto `1`).

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `code/tests/test_config_logic.py`:

```python
def test_normalize_server_defaults_poll_interval_to_30():
    server = normalize_server({"id": "s1", "nombre": "Personal"})
    assert server["poll_interval_s"] == 30


def test_normalize_server_keeps_explicit_poll_interval():
    server = normalize_server({"id": "s1", "nombre": "Personal", "poll_interval_s": 15})
    assert server["poll_interval_s"] == 15


def test_normalize_rule_defaults_repeticion_to_una_vez():
    rule = normalize_rule({"servidor_id": "s1", "tipo": "sala", "room_id": "r1", "sonido_id": "cat"})
    assert rule["repeticion_modo"] == "una_vez"
    assert rule["repeticion_n"] is None
    assert rule["repeticion_cada_polls"] == 1


def test_normalize_rule_keeps_explicit_repeticion_values():
    rule = normalize_rule(
        {
            "servidor_id": "s1",
            "tipo": "sala",
            "room_id": "r1",
            "sonido_id": "cat",
            "repeticion_modo": "n_veces",
            "repeticion_n": 3,
            "repeticion_cada_polls": 2,
        }
    )
    assert rule["repeticion_modo"] == "n_veces"
    assert rule["repeticion_n"] == 3
    assert rule["repeticion_cada_polls"] == 2
```

Y actualizar el test existente `test_normalize_rule_keeps_explicit_values` (línea 58-71) para incluir los nuevos campos en el diccionario esperado:

```python
def test_normalize_rule_keeps_explicit_values():
    rule = normalize_rule(
        {"servidor_id": "s1", "tipo": "mencion", "sonido_id": "bell", "activa": False, "id": "m1"}
    )
    assert rule == {
        "id": "m1",
        "servidor_id": "s1",
        "tipo": "mencion",
        "sonido_id": "bell",
        "etiqueta": "",
        "activa": False,
        "room_id": None,
        "room_type": None,
        "repeticion_modo": "una_vez",
        "repeticion_n": None,
        "repeticion_cada_polls": 1,
    }
```

Y `test_normalize_server_keeps_explicit_values` (línea 74-76) para incluir el nuevo campo:

```python
def test_normalize_server_keeps_explicit_values():
    server = normalize_server(
        {"id": "s1", "nombre": "Personal", "activo": True, "poll_interval_s": 60}
    )
    assert server == {"id": "s1", "nombre": "Personal", "activo": True, "poll_interval_s": 60}
```

- [ ] **Step 2: Ejecutar los tests y comprobar que fallan**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest tests/test_config_logic.py -v`
Expected: FAIL (KeyError o AssertionError) en los tests nuevos/modificados de este paso.

- [ ] **Step 3: Implementar los campos nuevos**

Reemplazar `normalize_server` y `normalize_rule` en `code/mk96_app_debian_rocket_tool/config.py`:

```python
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
        "repeticion_modo": raw_rule.get("repeticion_modo", "una_vez"),
        "repeticion_n": raw_rule.get("repeticion_n"),
        "repeticion_cada_polls": raw_rule.get("repeticion_cada_polls", 1),
    }
```

- [ ] **Step 4: Ejecutar los tests y comprobar que pasan**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest tests/test_config_logic.py -v`
Expected: PASS (todos).

---

### Task 2: `rest_client.py` — listar suscripciones y cursor temporal en el historial

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/rest_client.py`
- Test: `code/tests/test_rest_client_logic.py`

**Interfaces:**
- Consumes: nada nuevo de otras tareas.
- Produces:
  - `RestClient.get_own_username() -> str | None` (renombrado desde `_get_own_username`, ahora público — lo necesitará `poller.py` en la Task 4).
  - `RestClient.list_subscriptions(updated_since: str | None = None) -> list[dict]` — cada dict trae al menos `rid`, `t`, `ls` cuando la suscripción sigue viva.
  - `RestClient.room_history(room_id, tipo, count=50, oldest=None) -> list[dict]` — cada dict trae ahora `sender`, `text`, `ts`, `mentions` (lista de usernames mencionados).

**Nota:** `list_subscriptions`/`room_history` con efectos de red no se testean con mocks (mismo criterio que el resto del proyecto) — los tests de este paso cubren solo la lógica pura ya existente (`resolve_room_name`, `build_room_description`) más los que ya hay; los cambios de red se validan manualmente contra un servidor real más adelante. Sí se testea, sin red, `RestClient._request` construyendo bien la URL con `oldest`/`date` — ver Step 1.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `code/tests/test_rest_client_logic.py`, junto a los imports existentes cambiar la primera línea a:

```python
from urllib.parse import parse_qs, urlparse

from mk96_app_debian_rocket_tool.rest_client import RestClient, build_room_description, resolve_room_name
```

Y añadir al final del fichero:

```python
class _RecordingRestClient(RestClient):
    """Subclase que captura la URL pedida en vez de hacer una petición HTTP real,
    para poder comprobar qué parámetros construye cada método sin red."""

    def __init__(self):
        super().__init__("https://chat.example.com", "uid1", "tok1")
        self.requested_urls = []

    def _request(self, method, path, params=None, body=None):
        url = f"{self._base_url}/api/v1/{path}"
        if params:
            from urllib.parse import urlencode

            url += "?" + urlencode(params)
        self.requested_urls.append(url)
        return {}


def test_list_subscriptions_without_updated_since_omits_date_param():
    client = _RecordingRestClient()
    client.list_subscriptions()
    url = client.requested_urls[0]
    assert "subscriptions.get" in url
    assert "date" not in parse_qs(urlparse(url).query)


def test_list_subscriptions_with_updated_since_sends_date_param():
    client = _RecordingRestClient()
    client.list_subscriptions("2026-08-14T10:00:00.000Z")
    query = parse_qs(urlparse(client.requested_urls[0]).query)
    assert query["date"] == ["2026-08-14T10:00:00.000Z"]


def test_room_history_without_oldest_omits_param():
    client = _RecordingRestClient()
    client.room_history("room1", "c")
    query = parse_qs(urlparse(client.requested_urls[0]).query)
    assert "oldest" not in query


def test_room_history_with_oldest_sends_param():
    client = _RecordingRestClient()
    client.room_history("room1", "c", oldest="2026-08-14T10:00:00.000Z")
    query = parse_qs(urlparse(client.requested_urls[0]).query)
    assert query["oldest"] == ["2026-08-14T10:00:00.000Z"]
```

- [ ] **Step 2: Ejecutar los tests y comprobar que fallan**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest tests/test_rest_client_logic.py -v`
Expected: FAIL con `AttributeError: 'RestClient' object has no attribute 'list_subscriptions'` (y similares).

- [ ] **Step 3: Implementar los métodos nuevos**

En `code/mk96_app_debian_rocket_tool/rest_client.py`, renombrar `_get_own_username` a `get_own_username` y actualizar su única llamada (dentro de `list_rooms`):

```python
    def get_own_username(self) -> str | None:
        if self._own_username is None:
            response = self._request("GET", "me")
            self._own_username = response.get("username")
        return self._own_username

    def list_rooms(self) -> list:
        """Lista de salas/DMs visibles para el usuario, para el buscador de reglas."""
        response = self._request("GET", "rooms.get")
        rooms = response.get("update", []) + response.get("remove", [])
        own_username = self.get_own_username()
        ...
```

(el resto de `list_rooms` no cambia). Añadir el nuevo método `list_subscriptions` justo debajo de `list_rooms`:

```python
    def list_subscriptions(self, updated_since: str | None = None) -> list:
        """Suscripciones (una por sala/DM) con su `ls` (last seen) y contador de no
        leídos. Con `updated_since`, Rocket.Chat devuelve solo lo cambiado desde esa
        fecha -se usa para el polling incremental en poller.py."""
        params = {"date": updated_since} if updated_since else None
        response = self._request("GET", "subscriptions.get", params=params)
        return response.get("update", []) + response.get("remove", [])
```

Y reemplazar `room_history`:

```python
    def room_history(
        self, room_id: str, tipo: str, count: int = 50, oldest: str | None = None
    ) -> list:
        # Las salas ("c"/"p") usan channels.history; los DMs ("d") usan im.history.
        endpoint = "im.history" if tipo == "d" else "channels.history"
        params = {"roomId": room_id, "count": count}
        if oldest:
            params["oldest"] = oldest
        response = self._request("GET", endpoint, params=params)
        messages = response.get("messages", [])
        return [
            {
                "sender": message.get("u", {}).get("username"),
                "text": message.get("msg", ""),
                "ts": message.get("ts"),
                "mentions": [
                    m.get("username") for m in message.get("mentions", []) if m.get("username")
                ],
            }
            for message in reversed(messages)
        ]
```

- [ ] **Step 4: Ejecutar los tests y comprobar que pasan**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest tests/test_rest_client_logic.py -v`
Expected: PASS (todos, incluidos los ya existentes).

---

### Task 3: `poller.py` — funciones puras (leído / a quién preguntar / cuándo repetir)

**Files:**
- Create: `code/mk96_app_debian_rocket_tool/poller.py` (solo las funciones puras en este task; la clase con efectos se añade en la Task 4)
- Test: `code/tests/test_poller_logic.py`

**Interfaces:**
- Produces:
  - `is_message_read(message_ts: str | None, last_seen_ts: str | None) -> bool`
  - `should_fetch_room(rid: str, reglas_activas: list, hay_mencion_activa: bool) -> bool`
  - `should_repeat(pending: dict, regla: dict, tick_actual: int) -> bool` — `pending` es `{"count": int, "last_sound_tick": int}` (subconjunto de lo que guardará el `Poller` de la Task 4).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `code/tests/test_poller_logic.py`:

```python
from mk96_app_debian_rocket_tool.poller import is_message_read, should_fetch_room, should_repeat


def _room_rule(room_id, rule_id="r1"):
    return {"id": rule_id, "tipo": "sala", "room_id": room_id, "sonido_id": "cat"}


def _mention_rule(rule_id="m1"):
    return {"id": rule_id, "tipo": "mencion", "sonido_id": "bell"}


# -- is_message_read ----------------------------------------------------------------

def test_is_message_read_true_when_ts_not_after_last_seen():
    assert is_message_read("2026-08-14T10:00:00.000Z", "2026-08-14T10:00:00.000Z") is True
    assert is_message_read("2026-08-14T09:59:00.000Z", "2026-08-14T10:00:00.000Z") is True


def test_is_message_read_false_when_ts_after_last_seen():
    assert is_message_read("2026-08-14T10:01:00.000Z", "2026-08-14T10:00:00.000Z") is False


def test_is_message_read_false_when_no_last_seen():
    assert is_message_read("2026-08-14T10:01:00.000Z", None) is False


def test_is_message_read_false_when_no_message_ts():
    assert is_message_read(None, "2026-08-14T10:00:00.000Z") is False


# -- should_fetch_room ---------------------------------------------------------------

def test_should_fetch_room_true_when_room_rule_matches():
    assert should_fetch_room("room1", [_room_rule("room1")], hay_mencion_activa=False) is True


def test_should_fetch_room_false_when_no_matching_rule_and_no_mention_rule():
    assert should_fetch_room("room2", [_room_rule("room1")], hay_mencion_activa=False) is False


def test_should_fetch_room_true_for_any_room_when_mention_rule_active():
    assert should_fetch_room("room9", [_room_rule("room1")], hay_mencion_activa=True) is True


# -- should_repeat ---------------------------------------------------------------------

def test_should_repeat_false_for_una_vez():
    regla = {"repeticion_modo": "una_vez", "repeticion_n": None, "repeticion_cada_polls": 1}
    pending = {"count": 1, "last_sound_tick": 0}
    assert should_repeat(pending, regla, tick_actual=1) is False


def test_should_repeat_true_for_infinito_once_interval_elapsed():
    regla = {"repeticion_modo": "infinito", "repeticion_n": None, "repeticion_cada_polls": 2}
    pending = {"count": 1, "last_sound_tick": 0}
    assert should_repeat(pending, regla, tick_actual=1) is False
    assert should_repeat(pending, regla, tick_actual=2) is True


def test_should_repeat_false_for_n_veces_once_count_reached():
    regla = {"repeticion_modo": "n_veces", "repeticion_n": 2, "repeticion_cada_polls": 1}
    pending = {"count": 2, "last_sound_tick": 0}
    assert should_repeat(pending, regla, tick_actual=5) is False


def test_should_repeat_true_for_n_veces_below_count_and_interval_elapsed():
    regla = {"repeticion_modo": "n_veces", "repeticion_n": 3, "repeticion_cada_polls": 1}
    pending = {"count": 1, "last_sound_tick": 0}
    assert should_repeat(pending, regla, tick_actual=1) is True
```

- [ ] **Step 2: Ejecutar los tests y comprobar que fallan**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest tests/test_poller_logic.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'mk96_app_debian_rocket_tool.poller'`.

- [ ] **Step 3: Crear `poller.py` con las funciones puras**

Crear `code/mk96_app_debian_rocket_tool/poller.py`:

```python
"""Polling sobre la REST API de Rocket.Chat: sustituye a la antigua conexión
WebSocket/DDP (rc_client.py, eliminado). Ver docs/superpowers/specs/2026-08-14-rest-polling-design.md
para el porqué del cambio.

Las funciones de este módulo son puras (sin red/GLib) y testeables directamente; la
clase Poller (más abajo) las orquesta con efectos -mismo patrón que rc_client.py
separaba build_*/extract_* de RocketChatClient.
"""


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
```

- [ ] **Step 4: Ejecutar los tests y comprobar que pasan**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest tests/test_poller_logic.py -v`
Expected: PASS (todos).

---

### Task 4: `poller.py` — clase `Poller` (orquestación con efectos)

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/poller.py` (añadir la clase, debajo de las funciones puras de la Task 3)

**Interfaces:**
- Consumes: `RestClient.list_subscriptions`, `RestClient.room_history`, `RestClient.get_own_username` (Task 2); `is_message_read`, `should_fetch_room`, `should_repeat` (Task 3); `match_rule` de `rules.py` (ya existente, sin cambios).
- Produces: `Poller(rest_client, poll_interval_s, get_reglas_activas, on_event, on_status_changed)` con `.start()` / `.stop()` — misma forma de uso que la `RocketChatClient` que sustituye, para minimizar cambios en `app.py` (Task 5).

Esta clase no lleva tests automáticos de pytest (igual que `RocketChatClient` tampoco los llevaba): depende de `GLib` real para el temporizador y de red real para las peticiones. Se verifica manualmente en la Task 5/6 al probar la app completa. Este es el único paso del plan sin ciclo TDD por esa razón -documentado explícitamente, no es un olvido.

- [ ] **Step 1: Añadir la clase `Poller` al final de `poller.py`**

```python
from datetime import datetime, timezone

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from mk96_app_debian_rocket_tool.rest_client import RestApiError
from mk96_app_debian_rocket_tool.rules import match_rule


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Poller:
    """Sustituye a RocketChatClient: en vez de una conexión WS persistente, hace
    polling periódico sobre la REST API. `on_event(event)` y `on_status_changed(bool)`
    tienen la misma forma que en rc_client.py, para que app.py no tenga que cambiar
    su lógica de manejo de eventos."""

    def __init__(
        self,
        rest_client,
        poll_interval_s: int,
        get_reglas_activas,
        on_event,
        on_status_changed,
    ):
        self._rest_client = rest_client
        self._poll_interval_s = poll_interval_s
        self._get_reglas_activas = get_reglas_activas
        self._on_event = on_event
        self._on_status_changed = on_status_changed

        self._tick = 0
        self._cursors = {}  # rid -> ts (str) del último mensaje ya procesado
        self._pending = {}  # rid -> {"event", "regla_id", "count", "last_sound_tick", "message_ts"}
        self._last_poll_iso = None
        self._baseline_done = False
        self._timeout_id = None

    def start(self) -> None:
        self._tick_poll()
        self._timeout_id = GLib.timeout_add_seconds(self._poll_interval_s, self._tick_poll)

    def stop(self) -> None:
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _tick_poll(self) -> bool:
        try:
            subs = self._rest_client.list_subscriptions(self._last_poll_iso)
        except RestApiError:
            self._on_status_changed(False)
            return GLib.SOURCE_CONTINUE

        self._on_status_changed(True)
        self._last_poll_iso = _now_iso()
        self._tick += 1

        reglas_activas = [r for r in self._get_reglas_activas() if r.get("activa", True)]

        if not self._baseline_done:
            for sub in subs:
                rid = sub.get("rid")
                if rid:
                    self._cursors[rid] = sub.get("ls") or self._last_poll_iso
            self._baseline_done = True
            return GLib.SOURCE_CONTINUE

        hay_mencion_activa = any(r["tipo"] == "mencion" for r in reglas_activas)
        own_username = self._rest_client.get_own_username()

        for sub in subs:
            rid = sub.get("rid")
            if not rid:
                continue
            self._clear_pending_if_read(rid, sub)
            if should_fetch_room(rid, reglas_activas, hay_mencion_activa):
                self._process_room(rid, sub, reglas_activas, own_username)

        self._fire_due_reminders(reglas_activas)
        return GLib.SOURCE_CONTINUE

    def _clear_pending_if_read(self, rid: str, sub: dict) -> None:
        pending = self._pending.get(rid)
        if pending is not None and is_message_read(pending["message_ts"], sub.get("ls")):
            del self._pending[rid]

    def _process_room(self, rid: str, sub: dict, reglas_activas: list, own_username) -> None:
        room_type = sub.get("t", "c")
        cursor = self._cursors.get(rid)
        try:
            messages = self._rest_client.room_history(rid, room_type, oldest=cursor)
        except RestApiError:
            return

        for message in messages:
            ts = message.get("ts")
            if ts:
                self._cursors[rid] = ts
            if message.get("sender") == own_username:
                continue

            event = {
                "rid": rid,
                "mentioned": own_username in (message.get("mentions") or []),
                "sender": message.get("sender"),
                "text": message.get("text"),
            }
            rule = match_rule(event, reglas_activas)
            if rule is None or is_message_read(ts, sub.get("ls")):
                continue

            self._on_event(event)
            if rule.get("repeticion_modo", "una_vez") != "una_vez":
                self._pending[rid] = {
                    "event": event,
                    "regla_id": rule["id"],
                    "count": 1,
                    "last_sound_tick": self._tick,
                    "message_ts": ts,
                }

    def _fire_due_reminders(self, reglas_activas: list) -> None:
        reglas_por_id = {r["id"]: r for r in reglas_activas}
        for rid in list(self._pending.keys()):
            pending = self._pending[rid]
            regla = reglas_por_id.get(pending["regla_id"])
            if regla is None:
                del self._pending[rid]
                continue
            if not should_repeat(pending, regla, self._tick):
                continue
            self._on_event(pending["event"])
            pending["count"] += 1
            pending["last_sound_tick"] = self._tick
```

- [ ] **Step 2: Comprobar que el módulo importa sin errores**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -c "from mk96_app_debian_rocket_tool.poller import Poller; print('ok')"`
Expected: `ok` (si falla por `gi`/`GLib` no disponible en el entorno de desarrollo, confirmar que es el mismo tipo de fallo que ya daría `rc_client.py` hoy -no es una regresión nueva).

- [ ] **Step 3: Ejecutar toda la suite de tests para confirmar que nada se rompió**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest -v`
Expected: PASS (todos los tests existentes más los de las Tasks 1-3).

---

### Task 5: `app.py` — sustituir `RocketChatClient` por `Poller`

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/app.py:10-20` (imports), `:26-36` (`__init__`), `:42-72` (`_connect`), `:74-83` (`_disconnect`), `:189-191` (`shutdown`)

**Interfaces:**
- Consumes: `Poller` (Task 4), `config_module.rules_for_server` (ya existente).
- Produces: sin cambios de interfaz pública de `Application` -mismo comportamiento observable, solo cambia el transporte interno.

- [ ] **Step 1: Cambiar el import**

En `code/mk96_app_debian_rocket_tool/app.py:15`, reemplazar:

```python
from mk96_app_debian_rocket_tool.rc_client import RocketChatClient
```

por:

```python
from mk96_app_debian_rocket_tool.poller import Poller
```

- [ ] **Step 2: Renombrar `self._rc_client` a `self._poller` en todo el fichero**

En `__init__` (línea 27): `self._rc_client = None` -> `self._poller = None`.

En `_connect` (líneas 52-53 y 62-69):

```python
        if self._poller is not None:
            self._poller.stop()

        self._active_server_id = servidor_id
        config_module.set_active_server(self._config, servidor_id)
        config_module.save_config(self._config)

        server_config = next(
            s for s in self._config["servidores"] if s["id"] == servidor_id
        )

        self._rest_client = RestClient(
            credentials["server_url"], credentials["user_id"], credentials["token"]
        )
        self._poller = Poller(
            self._rest_client,
            server_config.get("poll_interval_s", 30),
            lambda: config_module.rules_for_server(self._config, self._active_server_id),
            self._on_event,
            self._on_connection_status_changed,
        )
        self._poller.start()
```

En `_disconnect` (líneas 77-79):

```python
        if self._poller is not None:
            self._poller.stop()
        self._poller = None
        self._rest_client = None
```

En `shutdown` (líneas 190-191):

```python
    def shutdown(self) -> None:
        if self._poller is not None:
            self._poller.stop()
```

- [ ] **Step 3: Ejecutar toda la suite de tests**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest -v`
Expected: PASS. (Estos cambios son de integración/orquestación sin lógica pura nueva -no llevan test propio, se validan por la suite completa más la verificación manual de la Task 7).

---

### Task 6: `settings_window.py` — UI de intervalo de poll y repetición de aviso

**Files:**
- Modify: `code/mk96_app_debian_rocket_tool/settings_window.py:142-202` (`_build_connection_section`, `_save_server`), `:268-381` (`_build_room_rule_form`, `_build_mention_rule_form`), `:619-631` (`_load_rule_into_form`), `:862-933` (`_add_room_rule`, `_set_mention_rule`)

**Interfaces:**
- Consumes: `normalize_server`/`normalize_rule` (Task 1) ya rellenan los defaults; esta tarea solo añade los widgets que leen/escriben esos campos.
- Produces: sin cambios de interfaz pública de `SettingsWindow`.

- [ ] **Step 1: Añadir un helper compartido para los controles de repetición**

Añadir este método a `SettingsWindow` (por ejemplo, justo antes de `_build_room_rule_form`, línea 268):

```python
    def _build_repeat_controls(self):
        """Controles de repetición (modo/N/cada X revisiones), compartidos entre el
        formulario de regla de sala y el de mención. Devuelve
        (box, combo_modo, spin_n, spin_cada_polls)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        combo = Gtk.ComboBoxText()
        combo.append("una_vez", "Solo una vez")
        combo.append("n_veces", "N veces")
        combo.append("infinito", "Hasta que lo leas")
        combo.set_active_id("una_vez")
        box.pack_start(combo, False, False, 0)

        details = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        n_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        n_box.pack_start(Gtk.Label(label="N:"), False, False, 0)
        n_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        n_spin.set_value(3)
        n_box.pack_start(n_spin, False, False, 0)
        details.pack_start(n_box, False, False, 0)

        details.pack_start(Gtk.Label(label="Cada X revisiones:"), False, False, 0)
        every_spin = Gtk.SpinButton.new_with_range(1, 20, 1)
        every_spin.set_value(1)
        details.pack_start(every_spin, False, False, 0)
        box.pack_start(details, False, False, 0)

        def update_visibility(_combo=None):
            modo = combo.get_active_id()
            details.set_visible(modo != "una_vez")
            n_box.set_visible(modo == "n_veces")

        combo.connect("changed", update_visibility)
        update_visibility()

        return box, combo, n_spin, every_spin
```

- [ ] **Step 2: Selector de intervalo de poll en la sección de conexión**

En `_build_connection_section` (línea 142), tras el bloque de `self._token_entry` (línea 175) y antes de `button_row` (línea 177), añadir:

```python
        box.pack_start(Gtk.Label(label="Comprobar mensajes nuevos cada:", xalign=0), False, False, 0)
        self._poll_interval_combo = Gtk.ComboBoxText()
        self._poll_interval_combo.append("15", "15 segundos")
        self._poll_interval_combo.append("30", "30 segundos")
        self._poll_interval_combo.append("60", "60 segundos")
        self._poll_interval_combo.set_active_id(
            str(existing_server.get("poll_interval_s", 30)) if existing_server else "30"
        )
        box.pack_start(self._poll_interval_combo, False, False, 0)
```

- [ ] **Step 3: Guardar el intervalo al pulsar "Guardar"**

En `_save_server` (línea 204), tras la validación de campos obligatorios (línea 209-210), leer el combo y guardarlo en el servidor:

```python
        poll_interval_s = int(self._poll_interval_combo.get_active_id())

        is_new = servidor_id is None
        if is_new:
            server = normalize_server(
                {"nombre": nombre, "activo": False, "poll_interval_s": poll_interval_s}
            )
            servidor_id = server["id"]
            self._config["servidores"].append(server)
        else:
            for server in self._config["servidores"]:
                if server["id"] == servidor_id:
                    server["nombre"] = nombre
                    server["poll_interval_s"] = poll_interval_s
```

(esto reemplaza el bloque `is_new = ...` ya existente en líneas 212-220).

- [ ] **Step 4: Controles de repetición en el formulario de regla de sala**

En `_build_room_rule_form` (línea 268), tras el bloque de `add_room_rule_button` (línea 340) y antes del `if not connected:` (línea 342), insertar:

```python
        grid.attach(Gtk.Label(label="Repetir sonido:", xalign=0), 0, 3, 1, 1)
        repeat_box, self._room_repeat_combo, self._room_repeat_n, self._room_repeat_every = (
            self._build_repeat_controls()
        )
        grid.attach(repeat_box, 1, 3, 2, 1)
```

Y cambiar la fila del hint de conexión (línea 342-348) de la fila `3` a la fila `4`:

```python
        if not connected:
            hint = Gtk.Label(
                label="Conecta este servidor para poder buscar salas y añadir reglas nuevas.",
                xalign=0,
            )
            hint.set_line_wrap(True)
            grid.attach(hint, 0, 4, 3, 1)
```

- [ ] **Step 5: Controles de repetición en el formulario de regla de mención**

Reemplazar `_build_mention_rule_form` completo (líneas 352-381) por:

```python
    def _build_mention_rule_form(self, servidor_id: str) -> Gtk.Frame:
        frame = Gtk.Frame(label="Regla de mención global")
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        grid.set_border_width(10)
        frame.add(grid)

        self._selected_mention_sonido_id = None
        grid.attach(Gtk.Label(label="Sonido:", xalign=0), 0, 0, 1, 1)
        self._mention_sound_label = Gtk.Label(label="(ninguno)", xalign=0)
        grid.attach(self._mention_sound_label, 1, 0, 1, 1)

        choose_sound_button = Gtk.Button(label="Elegir sonido...")
        choose_sound_button.connect("clicked", lambda _b: self._choose_mention_sound())
        grid.attach(choose_sound_button, 2, 0, 1, 1)

        grid.attach(Gtk.Label(label="Repetir sonido:", xalign=0), 0, 1, 1, 1)
        repeat_box, self._mention_repeat_combo, self._mention_repeat_n, self._mention_repeat_every = (
            self._build_repeat_controls()
        )
        grid.attach(repeat_box, 1, 1, 2, 1)

        self._mention_preview_button = Gtk.Button(label="▶ Probar")
        self._mention_preview_button.set_sensitive(False)
        self._mention_preview_button.connect(
            "clicked", lambda _b: self._preview_selected_sound(self._selected_mention_sonido_id)
        )
        grid.attach(self._mention_preview_button, 0, 2, 1, 1)

        add_mention_rule_button = Gtk.Button(label="Configurar regla de mención")
        add_mention_rule_button.set_halign(Gtk.Align.END)
        add_mention_rule_button.connect(
            "clicked", lambda _b: self._set_mention_rule(servidor_id)
        )
        grid.attach(add_mention_rule_button, 1, 2, 2, 1)

        return frame
```

- [ ] **Step 6: Leer los controles al añadir/actualizar una regla de sala**

En `_add_room_rule` (línea 862), tras obtener `room_id, _descripcion = self._selected_room` (línea 877) y antes de `room = next(...)` (línea 879), añadir:

```python
        repeticion_modo = self._room_repeat_combo.get_active_id()
        repeticion_n = int(self._room_repeat_n.get_value()) if repeticion_modo == "n_veces" else None
        repeticion_cada_polls = (
            int(self._room_repeat_every.get_value()) if repeticion_modo != "una_vez" else 1
        )
```

Y actualizar el bloque `if existing_rule is not None: ... else: ...` (líneas 882-899) para incluir estos valores:

```python
        if existing_rule is not None:
            # Ya hay una regla para esta sala/persona: se actualiza el sonido en vez
            # de dejar dos reglas apuntando al mismo sitio.
            existing_rule["sonido_id"] = sonido_id
            existing_rule["repeticion_modo"] = repeticion_modo
            existing_rule["repeticion_n"] = repeticion_n
            existing_rule["repeticion_cada_polls"] = repeticion_cada_polls
            if room:
                existing_rule["room_type"] = room["tipo"]
                existing_rule["etiqueta"] = room["nombre"]
        else:
            rule = normalize_rule(
                {
                    "servidor_id": servidor_id,
                    "tipo": "sala",
                    "room_id": room_id,
                    "room_type": room["tipo"] if room else None,
                    "sonido_id": sonido_id,
                    "etiqueta": room["nombre"] if room else room_id,
                    "repeticion_modo": repeticion_modo,
                    "repeticion_n": repeticion_n,
                    "repeticion_cada_polls": repeticion_cada_polls,
                }
            )
            self._config["reglas"].append(rule)
```

- [ ] **Step 7: Leer los controles al configurar la regla de mención**

En `_set_mention_rule` (línea 907), aplicar el mismo patrón que el Step 6:

```python
    def _set_mention_rule(self, servidor_id: str) -> None:
        sonido_id = self._selected_mention_sonido_id
        if not sonido_id:
            self._show_error(
                "Falta el sonido",
                "Usa 'Elegir sonido...' antes de configurar la regla de mención.",
            )
            return

        repeticion_modo = self._mention_repeat_combo.get_active_id()
        repeticion_n = (
            int(self._mention_repeat_n.get_value()) if repeticion_modo == "n_veces" else None
        )
        repeticion_cada_polls = (
            int(self._mention_repeat_every.get_value()) if repeticion_modo != "una_vez" else 1
        )

        self._config["reglas"] = [
            r
            for r in self._config["reglas"]
            if not (r["servidor_id"] == servidor_id and r["tipo"] == "mencion")
        ]
        self._config["reglas"].append(
            normalize_rule(
                {
                    "servidor_id": servidor_id,
                    "tipo": "mencion",
                    "sonido_id": sonido_id,
                    "etiqueta": "Mención",
                    "repeticion_modo": repeticion_modo,
                    "repeticion_n": repeticion_n,
                    "repeticion_cada_polls": repeticion_cada_polls,
                }
            )
        )
        self._callbacks["on_config_changed"](self._config)
        self._refresh_rules_list(servidor_id)
```

- [ ] **Step 8: Cargar los valores de repetición al editar una regla existente**

Reemplazar `_load_rule_into_form` (líneas 619-631) por:

```python
    def _load_rule_into_form(self, rule: dict) -> None:
        if rule["tipo"] == "mencion":
            self._selected_mention_sonido_id = rule["sonido_id"]
            self._mention_sound_label.set_text(sonido_display_name(rule["sonido_id"]))
            self._mention_preview_button.set_sensitive(True)
            self._mention_repeat_combo.set_active_id(rule.get("repeticion_modo", "una_vez"))
            self._mention_repeat_n.set_value(rule.get("repeticion_n") or 3)
            self._mention_repeat_every.set_value(rule.get("repeticion_cada_polls") or 1)
            return

        descripcion = self._config["salas_cache"].get(rule["room_id"], rule["room_id"])
        self._selected_room = (rule["room_id"], descripcion)
        self._set_room_search_text(descripcion)
        self._selected_room_sonido_id = rule["sonido_id"]
        self._room_preview_button.set_sensitive(True)
        self._room_sound_label.set_text(sonido_display_name(rule["sonido_id"]))
        self._room_repeat_combo.set_active_id(rule.get("repeticion_modo", "una_vez"))
        self._room_repeat_n.set_value(rule.get("repeticion_n") or 3)
        self._room_repeat_every.set_value(rule.get("repeticion_cada_polls") or 1)
```

(`.set_active_id(...)` dispara la señal `"changed"` del combo, que ya actualiza la visibilidad de los spin buttons via `update_visibility` del Step 1 -no hace falta llamarla a mano).

- [ ] **Step 9: Ejecutar toda la suite de tests**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest -v`
Expected: PASS (esta tarea es UI GTK sin lógica pura nueva -no lleva tests propios; se verifica manualmente abriendo la app en la Task 7).

---

### Task 7: Limpieza — eliminar `rc_client.py` y actualizar packaging/docs

**Files:**
- Delete: `code/mk96_app_debian_rocket_tool/rc_client.py`
- Delete: `code/tests/test_rc_client_logic.py`
- Modify: `code/debian/control` (quitar `gir1.2-soup-2.4`)
- Modify: `code/DESIGN.md` (arquitectura y riesgo técnico)

- [ ] **Step 1: Eliminar el módulo WS y su test**

```bash
rm /repos/mk96-app-debian-rocket-tool/code/mk96_app_debian_rocket_tool/rc_client.py
rm /repos/mk96-app-debian-rocket-tool/code/tests/test_rc_client_logic.py
rm -f /repos/mk96-app-debian-rocket-tool/code/mk96_app_debian_rocket_tool/__pycache__/rc_client.cpython-310.pyc
```

- [ ] **Step 2: Quitar la dependencia de libsoup del paquete Debian**

En `code/debian/control` línea 11, cambiar:

```
Depends: ${misc:Depends}, python3-gi, gir1.2-ayatanaappindicator3-0.1, gir1.2-secret-1, gir1.2-soup-2.4, python3-yaml
```

por:

```
Depends: ${misc:Depends}, python3-gi, gir1.2-ayatanaappindicator3-0.1, gir1.2-secret-1, python3-yaml
```

- [ ] **Step 3: Actualizar `DESIGN.md`**

En la sección "Requisitos de sistema" (línea 15), eliminar la línea:

```
- `gir1.2-soup-2.4` — cliente WebSocket para la Realtime API de Rocket.Chat.
```

En "Arquitectura", reemplazar el punto de `rc_client.py` (líneas 29-34) por:

```
- **`poller.py`** — polling periódico (GLib) sobre la REST API de Rocket.Chat:
  `subscriptions.get` en modo delta para detectar salas con actividad, e
  historial (`channels.history`/`im.history` con cursor `oldest`) para los
  mensajes nuevos de las salas que interesan a alguna regla. Decide si un
  mensaje ya fue leído comparando su `ts` contra el `ls` de la suscripción -así
  no suena si ya lo leíste en el propio Rocket.Chat. Intervalo configurable por
  servidor (15/30/60s); repetición de aviso configurable por regla (una vez / N
  veces / infinito) mientras el mensaje siga sin leer.
```

Y reemplazar la sección "Riesgo técnico principal — validar con un servidor real" (líneas 74-87) por:

```
## Historial: por qué REST y no WebSocket

La primera versión usaba la Realtime API (WebSocket/DDP) de Rocket.Chat. Se
descartó en favor del polling REST actual porque el `login` DDP (necesario
para autenticar el socket) es justo el mecanismo que Rocket.Chat marca como
deprecado y sin mantenimiento activo, con comportamiento dependiente de 2FA y
sin manejo de errores fiable. El polling sobre REST usa endpoints estables y
activamente mantenidos. Detalle completo del análisis y del diseño en
`docs/superpowers/specs/2026-08-14-rest-polling-design.md`.

También relevante para las reglas de tipo `sala`: si una sala configurada no
dispara sonido, lo primero a revisar es su preferencia de notificación en
Rocket.Chat (aunque el polling no depende de las push notifications como sí
dependía el WebSocket, conviene descartar primero que la sala esté archivada o
que el usuario ya no sea miembro).
```

- [ ] **Step 4: Ejecutar toda la suite de tests**

Run: `cd /repos/mk96-app-debian-rocket-tool/code && python3 -m pytest -v`
Expected: PASS (todos -ya no debe aparecer `test_rc_client_logic.py` en la colección).

- [ ] **Step 5: Verificación manual contra un servidor real**

Esto no es automatizable (requiere un servidor Rocket.Chat real, tal y como ya advertía el `DESIGN.md` original para la integración WS). Arrancar la app (`python3 -m mk96_app_debian_rocket_tool.app`), conectar un servidor real, configurar una regla de sala con repetición "infinito" y comprobar:

1. Al llegar un mensaje no leído, suena y se repite cada `poll_interval_s * repeticion_cada_polls` segundos.
2. Al leer el mensaje desde la propia app de Rocket.Chat (móvil/web), el siguiente poll dejar de repetir.
3. Los mensajes propios (enviados por el propio usuario) no disparan sonido.
