"""Llamadas REST a Rocket.Chat: buscar salas, historial, suscripciones (para el
polling de poller.py), enviar mensajes.

El Personal Access Token se usa directamente como X-Auth-Token junto al user id como
X-User-Id -no requiere login previo.
"""

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

TIPO_LABELS = {"d": "DM", "c": "Canal", "p": "Privado"}
# Estados de presencia de Rocket.Chat (users.setStatus) -> etiqueta para el menú.
PRESENCE_STATUSES = {
    "online": "Disponible",
    "away": "Ausente",
    "busy": "Ocupado",
    "offline": "Invisible",
}


HISTORY_PAGE_SIZE = 100
HISTORY_MAX_PAGES = 10


class RestApiError(Exception):
    """La API REST de Rocket.Chat devolvió un error o no se pudo contactar."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AuthError(RestApiError):
    """El servidor rechazó las credenciales (401): reintentar no sirve de nada."""


def collect_pages(fetch_page, page_size: int, max_pages: int) -> list:
    """Lógica pura: concatena páginas (offset, count) hasta que una venga incompleta o
    se alcance max_pages."""
    result = []
    for page in range(max_pages):
        batch = fetch_page(page * page_size, page_size)
        result.extend(batch)
        if len(batch) < page_size:
            break
    return result


def parse_history_messages(raw_messages: list) -> list:
    """Lógica pura: mensajes de la API (más recientes primero) -> cronológico."""
    return [
        {
            "sender": message.get("u", {}).get("username"),
            "text": message.get("msg", ""),
            "ts": message.get("ts"),
            "mentions": [
                m.get("username") for m in message.get("mentions", []) if m.get("username")
            ],
        }
        for message in reversed(raw_messages)
    ]


def validate_server_url(server_url: str) -> str | None:
    """Mensaje de error si la URL no sirve para conectar, o None si es válida."""
    url = server_url.strip()
    scheme, _, rest = url.partition("://")
    if scheme.lower() not in ("http", "https") or not rest.strip("/"):
        return "La URL debe empezar por http:// o https:// y llevar el nombre del servidor."
    return None


def describe_connection_error(exc: RestApiError) -> str:
    """Mensaje en español, legible, para un fallo al probar la conexión."""
    if isinstance(exc, AuthError):
        return "Credenciales rechazadas: revisa el User Id y el token."
    if exc.status is not None:
        return f"El servidor respondió con el error {exc.status}: revisa la URL."
    return f"No se pudo contactar con el servidor: {exc}"


def check_connection(server_url: str, user_id: str, token: str) -> str:
    """Prueba unas credenciales sin guardarlas: devuelve el username si el servidor las
    acepta; lanza RestApiError (AuthError si las rechaza) en otro caso."""
    username = RestClient(server_url, user_id, token).get_own_username()
    if not username:
        raise RestApiError("el servidor no devolvió un usuario")
    return username


def is_insecure_url(server_url: str) -> bool:
    """http:// hacia un host que no es local: el token viajaría en claro."""
    url = server_url.strip().lower()
    if not url.startswith("http://"):
        return False
    host = url[len("http://"):].split("/")[0].split(":")[0]
    return host not in ("localhost", "127.0.0.1", "::1", "[::1]")


def resolve_room_name(room: dict, own_username: str | None = None) -> str:
    """Lógica pura: nombre identificable de una sala. Los DMs no tienen 'name'/'fname'
    útil, así que se resuelve a partir de 'usernames' (participantes), quitando el
    propio usuario si se conoce."""
    tipo = room.get("t")
    if tipo == "d":
        usernames = room.get("usernames", [])
        others = [u for u in usernames if u != own_username]
        if others:
            return ", ".join(others)
        if usernames:
            # DM contigo mismo: el único participante es tu propio username, así que
            # filtrarlo sin más dejaría la lista vacía -se muestra igualmente.
            return f"{usernames[0]} (tú)"
        return room.get("_id", "")
    return room.get("fname") or room.get("name") or room.get("_id", "")


def build_room_description(nombre: str, tipo: str | None) -> str:
    """Lógica pura: texto combinado 'Tipo · nombre' para mostrar/buscar en la UI."""
    etiqueta_tipo = TIPO_LABELS.get(tipo, tipo or "?")
    return f"{etiqueta_tipo} · {nombre}"


class RestClient:
    def __init__(self, server_url: str, user_id: str, token: str):
        self._base_url = server_url.rstrip("/")
        self._headers = {
            "X-Auth-Token": token,
            "X-User-Id": user_id,
            "Content-Type": "application/json",
        }
        self._own_username = None

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = f"{self._base_url}/api/v1/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            error_class = AuthError if exc.code == 401 else RestApiError
            raise error_class(str(exc), status=exc.code) from exc
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            # OSError cubre URLError y los timeouts de socket al leer la respuesta.
            raise RestApiError(str(exc)) from exc

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

        result = []
        for room in rooms:
            tipo = room.get("t")
            nombre = resolve_room_name(room, own_username)
            result.append(
                {
                    "room_id": room["_id"],
                    "nombre": nombre,
                    "tipo": tipo,
                    "descripcion": build_room_description(nombre, tipo),
                }
            )
        return result

    def list_subscriptions(self, updated_since: str | None = None) -> list:
        """Suscripciones (una por sala/DM) con su `ls` (last seen) y contador de no
        leídos. Con `updated_since`, Rocket.Chat devuelve solo lo cambiado desde esa
        fecha -se usa para el polling incremental en poller.py."""
        params = {"updatedSince": updated_since} if updated_since else None
        response = self._request("GET", "subscriptions.get", params=params)
        return response.get("update", []) + response.get("remove", [])

    def _history_page(
        self, room_id: str, tipo: str, count: int, oldest: str | None, offset: int = 0
    ) -> list:
        # Canales públicos ("c") usan channels.history, grupos privados ("p") usan
        # groups.history y DMs ("d") usan im.history -channels.history con un grupo
        # privado devuelve 400 Bad Request, no historial.
        endpoint = {"d": "im.history", "p": "groups.history"}.get(tipo, "channels.history")
        params = {"roomId": room_id, "count": count}
        if offset:
            params["offset"] = offset
        if oldest:
            params["oldest"] = oldest
        return self._request("GET", endpoint, params=params).get("messages", [])

    def room_history(
        self, room_id: str, tipo: str, count: int = 50, oldest: str | None = None
    ) -> list:
        return parse_history_messages(self._history_page(room_id, tipo, count, oldest))

    def room_history_since(self, room_id: str, tipo: str, oldest: str | None) -> list:
        """Todos los mensajes posteriores a `oldest`, paginando -una ráfaga de más de
        una página entre dos polls no pierde mensajes. Sin `oldest` solo trae la
        última página (no tiene sentido volcar todo el historial)."""
        if not oldest:
            return self.room_history(room_id, tipo)
        raw = collect_pages(
            lambda offset, count: self._history_page(room_id, tipo, count, oldest, offset),
            HISTORY_PAGE_SIZE,
            HISTORY_MAX_PAGES,
        )
        return parse_history_messages(raw)

    def mark_room_read(self, room_id: str) -> None:
        self._request("POST", "subscriptions.read", body={"rid": room_id})

    def set_presence(self, status: str) -> None:
        if status not in PRESENCE_STATUSES:
            raise ValueError(f"Estado de presencia desconocido: {status}")
        self._request("POST", "users.setStatus", body={"status": status})

    def send_message(self, room_id: str, text: str) -> None:
        self._request("POST", "chat.postMessage", body={"roomId": room_id, "text": text})
