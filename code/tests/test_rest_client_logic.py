from urllib.parse import parse_qs, urlencode, urlparse

from mk96_app_debian_rocket_tool.rest_client import RestClient, build_room_description, resolve_room_name


def test_resolve_room_name_channel_uses_fname():
    room = {"t": "c", "fname": "General", "name": "general"}
    assert resolve_room_name(room) == "General"


def test_resolve_room_name_channel_falls_back_to_name():
    room = {"t": "c", "name": "general"}
    assert resolve_room_name(room) == "general"


def test_resolve_room_name_channel_falls_back_to_id_as_last_resort():
    room = {"t": "c", "_id": "room123"}
    assert resolve_room_name(room) == "room123"


def test_resolve_room_name_dm_uses_usernames_excluding_own():
    room = {"t": "d", "usernames": ["yo", "colega"], "_id": "dm1"}
    assert resolve_room_name(room, own_username="yo") == "colega"


def test_resolve_room_name_dm_group_joins_remaining_usernames():
    room = {"t": "d", "usernames": ["yo", "ana", "luis"], "_id": "dm1"}
    assert resolve_room_name(room, own_username="yo") == "ana, luis"


def test_resolve_room_name_dm_falls_back_to_id_when_no_usernames():
    room = {"t": "d", "_id": "dm1"}
    assert resolve_room_name(room, own_username="yo") == "dm1"


def test_resolve_room_name_dm_without_known_own_username_keeps_all():
    room = {"t": "d", "usernames": ["yo", "colega"], "_id": "dm1"}
    assert resolve_room_name(room) == "yo, colega"


def test_resolve_room_name_self_dm_shows_own_username():
    # DM contigo mismo: 'usernames' solo trae tu propio username (eres el único
    # participante), así que filtrarlo sin más deja la lista vacía.
    room = {"t": "d", "usernames": ["yo"], "_id": "dm1"}
    assert resolve_room_name(room, own_username="yo") == "yo (tú)"


def test_build_room_description_known_types():
    assert build_room_description("General", "c") == "Canal · General"
    assert build_room_description("colega", "d") == "DM · colega"
    assert build_room_description("equipo-x", "p") == "Privado · equipo-x"


def test_build_room_description_unknown_type_falls_back_to_raw_value():
    assert build_room_description("algo", "z") == "z · algo"


def test_build_room_description_none_type():
    assert build_room_description("algo", None) == "? · algo"


class _RecordingRestClient(RestClient):
    """Subclase que captura la URL pedida en vez de hacer una petición HTTP real,
    para poder comprobar qué parámetros construye cada método sin red."""

    def __init__(self):
        super().__init__("https://chat.example.com", "uid1", "tok1")
        self.requested_urls = []

    def _request(self, method, path, params=None, body=None):
        url = f"{self._base_url}/api/v1/{path}"
        if params:
            url += "?" + urlencode(params)
        self.requested_urls.append(url)
        return {}


def test_list_subscriptions_without_updated_since_omits_date_param():
    client = _RecordingRestClient()
    client.list_subscriptions()
    url = client.requested_urls[0]
    assert "subscriptions.get" in url
    assert "updatedSince" not in parse_qs(urlparse(url).query)


def test_list_subscriptions_with_updated_since_sends_date_param():
    client = _RecordingRestClient()
    client.list_subscriptions("2026-08-14T10:00:00.000Z")
    query = parse_qs(urlparse(client.requested_urls[0]).query)
    assert query["updatedSince"] == ["2026-08-14T10:00:00.000Z"]


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


def test_room_history_uses_im_history_for_dms():
    client = _RecordingRestClient()
    client.room_history("room1", "d")
    assert "im.history" in client.requested_urls[0]


def test_room_history_uses_groups_history_for_private_rooms():
    # Rocket.Chat separa canales públicos ("c", channels.history) de grupos privados
    # ("p", groups.history) -pedir el historial de un grupo privado por channels.history
    # devuelve 400 Bad Request, así que nunca llegan mensajes ni se dispara ninguna regla.
    client = _RecordingRestClient()
    client.room_history("room1", "p")
    assert "groups.history" in client.requested_urls[0]


def test_room_history_uses_channels_history_for_public_channels():
    client = _RecordingRestClient()
    client.room_history("room1", "c")
    assert "channels.history" in client.requested_urls[0]


def test_set_presence_posts_status(monkeypatch):
    client = RestClient("https://chat.example.com", "uid", "tok")
    calls = []
    monkeypatch.setattr(client, "_request", lambda method, path, params=None, body=None: calls.append((method, path, body)))
    client.set_presence("busy")
    assert calls == [("POST", "users.setStatus", {"status": "busy"})]


def test_set_presence_rejects_unknown_status():
    import pytest

    client = RestClient("https://chat.example.com", "uid", "tok")
    with pytest.raises(ValueError):
        client.set_presence("dormido")


# -- paginación, errores de autenticación, URL insegura ----------------------------

import io
import urllib.error

import pytest

from mk96_app_debian_rocket_tool.rest_client import (
    AuthError,
    RestApiError,
    collect_pages,
    is_insecure_url,
    parse_history_messages,
)


def test_collect_pages_stops_on_incomplete_page():
    pages = {0: [1, 2], 2: [3]}
    assert collect_pages(lambda offset, count: pages.get(offset, []), 2, 10) == [1, 2, 3]


def test_collect_pages_respects_max_pages():
    calls = []

    def fetch(offset, count):
        calls.append(offset)
        return [0] * count

    assert len(collect_pages(fetch, 3, 4)) == 12
    assert calls == [0, 3, 6, 9]


def test_parse_history_messages_is_chronological_and_keeps_mentions():
    raw = [
        {"u": {"username": "b"}, "msg": "dos", "ts": "2", "mentions": [{"username": "all"}]},
        {"u": {"username": "a"}, "msg": "uno", "ts": "1"},
    ]
    parsed = parse_history_messages(raw)
    assert [m["text"] for m in parsed] == ["uno", "dos"]
    assert parsed[1]["mentions"] == ["all"]


class _PagedClient(RestClient):
    def __init__(self, total):
        super().__init__("https://chat.example.com", "uid", "tok")
        self.total = total  # mensajes disponibles, más reciente primero
        self.offsets = []

    def _request(self, method, path, params=None, body=None):
        offset, count = params.get("offset", 0), params["count"]
        self.offsets.append(offset)
        batch = list(range(self.total, 0, -1))[offset : offset + count]
        return {"messages": [{"u": {"username": "x"}, "msg": str(n), "ts": str(n)} for n in batch]}


def test_room_history_since_paginates_bursts():
    client = _PagedClient(total=250)
    messages = client.room_history_since("r", "c", "0")
    assert len(messages) == 250
    assert messages[0]["text"] == "1" and messages[-1]["text"] == "250"
    assert client.offsets == [0, 100, 200]


def test_room_history_since_without_cursor_fetches_one_page():
    client = _PagedClient(total=250)
    assert len(client.room_history_since("r", "c", None)) == 50
    assert client.offsets == [0]


def _raise_http(code):
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b""))

    return fake_urlopen


def test_request_401_raises_auth_error(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(401))
    with pytest.raises(AuthError) as exc_info:
        RestClient("https://x", "u", "t").get_own_username()
    assert exc_info.value.status == 401


def test_request_500_raises_plain_rest_error(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(500))
    with pytest.raises(RestApiError) as exc_info:
        RestClient("https://x", "u", "t").get_own_username()
    assert not isinstance(exc_info.value, AuthError)
    assert exc_info.value.status == 500


def test_request_socket_timeout_raises_rest_error(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RestApiError):
        RestClient("https://x", "u", "t").get_own_username()


def test_is_insecure_url():
    assert is_insecure_url("http://chat.example.com") is True
    assert is_insecure_url("https://chat.example.com") is False
    assert is_insecure_url("http://localhost:3000") is False
    assert is_insecure_url("http://127.0.0.1:3000/x") is False


# -- probar conexión -----------------------------------------------------------------

from mk96_app_debian_rocket_tool.rest_client import (
    check_connection,
    describe_connection_error,
    validate_server_url,
)


def test_validate_server_url_requires_scheme_and_host():
    assert validate_server_url("https://chat.example.com") is None
    assert validate_server_url("http://localhost:3000") is None
    assert "http" in validate_server_url("chat.example.com")
    assert validate_server_url("https://") is not None


def test_describe_connection_error_auth():
    assert "rechazad" in describe_connection_error(AuthError("401", status=401)).lower()


def test_describe_connection_error_http_status_mentions_code():
    text = describe_connection_error(RestApiError("x", status=404))
    assert "404" in text and "URL" in text


def test_describe_connection_error_network_includes_detail():
    text = describe_connection_error(RestApiError("[Errno -2] Name or service not known"))
    assert "contactar" in text and "Name or service not known" in text


def test_check_connection_returns_username(monkeypatch):
    monkeypatch.setattr(RestClient, "_request", lambda self, m, p, params=None, body=None: {"username": "ana"})
    assert check_connection("https://x", "u", "t") == "ana"


def test_check_connection_without_username_is_an_error(monkeypatch):
    monkeypatch.setattr(RestClient, "_request", lambda self, m, p, params=None, body=None: {})
    with pytest.raises(RestApiError):
        check_connection("https://x", "u", "t")
