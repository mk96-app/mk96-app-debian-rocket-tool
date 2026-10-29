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


# -- backoff ----------------------------------------------------------------------

from mk96_app_debian_rocket_tool.poller import MAX_BACKOFF_TICKS, Poller, backoff_ticks
from mk96_app_debian_rocket_tool.rest_client import AuthError, RestApiError


def test_backoff_ticks_grows_and_is_capped():
    assert [backoff_ticks(n) for n in (0, 1, 2, 3, 4)] == [0, 0, 1, 3, 7]
    assert backoff_ticks(50) == MAX_BACKOFF_TICKS


# -- Poller con un cliente REST falso (sin hilos ni GLib) ---------------------------

class _FakeRest:
    def __init__(self):
        self.subs = []
        self.history = {}  # rid -> mensajes
        self.fail_subs = None
        self.fail_history = set()
        self.history_calls = []

    def list_subscriptions(self, updated_since=None):
        if self.fail_subs is not None:
            raise self.fail_subs
        return self.subs

    def get_own_username(self):
        return "yo"

    def room_history_since(self, rid, tipo, oldest):
        self.history_calls.append((rid, oldest))
        if rid in self.fail_history:
            raise RestApiError("boom")
        return self.history.get(rid, [])


def _poller(rest, reglas, **callbacks):
    log = {"events": [], "status": [], "read": [], "auth": 0}
    poller = Poller(
        rest,
        30,
        lambda: reglas,
        log["events"].append,
        log["status"].append,
        log["read"].append,
        lambda: log.__setitem__("auth", log["auth"] + 1),
    )
    return poller, log


def _tick(poller, reglas):
    """Un sondeo completo: trabajo de red + entrega en el 'hilo principal'."""
    poller._on_poll_done(poller._poll_once(reglas), None)


def _msg(ts, text="hola", sender="ana", mentions=()):
    return {"ts": ts, "text": text, "sender": sender, "mentions": list(mentions)}


def test_poller_notifies_new_unread_message_after_baseline():
    rest = _FakeRest()
    rest.subs = [{"rid": "r1", "t": "c", "ls": "2026-01-01T00:00:00.000Z"}]
    reglas = [_room_rule("r1")]
    poller, log = _poller(rest, reglas)

    _tick(poller, reglas)  # baseline
    assert log["events"] == [] and log["status"] == [True]

    rest.history["r1"] = [_msg("2026-01-01T00:05:00.000Z")]
    _tick(poller, reglas)
    assert len(log["events"]) == 1
    assert log["events"][0]["rid"] == "r1" and log["events"][0]["room_type"] == "c"


def test_poller_flags_at_all_mentions():
    rest = _FakeRest()
    rest.subs = [{"rid": "r1", "t": "c", "ls": "2026-01-01T00:00:00.000Z"}]
    reglas = [_mention_rule()]
    poller, log = _poller(rest, reglas)
    _tick(poller, reglas)
    rest.history["r1"] = [_msg("2026-01-01T00:05:00.000Z", mentions=["all"])]
    _tick(poller, reglas)
    # La regla no admite @all (mencion_todos falso): no hay evento.
    assert log["events"] == []

    reglas2 = [{**_mention_rule(), "mencion_todos": True}]
    rest.history["r1"] = [_msg("2026-01-01T00:06:00.000Z", mentions=["here"])]
    _tick(poller, reglas2)
    assert len(log["events"]) == 1 and log["events"][0]["mentioned_all"] is True


def test_poller_ignores_own_messages():
    rest = _FakeRest()
    rest.subs = [{"rid": "r1", "t": "c", "ls": "2026-01-01T00:00:00.000Z"}]
    reglas = [_room_rule("r1")]
    poller, log = _poller(rest, reglas)
    _tick(poller, reglas)
    rest.history["r1"] = [_msg("2026-01-01T00:05:00.000Z", sender="yo")]
    _tick(poller, reglas)
    assert log["events"] == []


def test_poller_network_failure_sets_backoff_and_reports_once():
    rest = _FakeRest()
    rest.fail_subs = RestApiError("down")
    poller, log = _poller(rest, [])
    for _ in range(3):
        _tick(poller, [])
    assert log["status"] == [False]
    assert poller._failures == 3 and poller._skip_ticks == backoff_ticks(3)

    rest.fail_subs = None
    _tick(poller, [])
    assert log["status"] == [False, True]
    assert poller._failures == 0


def test_poller_auth_error_stops_and_notifies():
    rest = _FakeRest()
    rest.fail_subs = AuthError("401", status=401)
    poller, log = _poller(rest, [])
    _tick(poller, [])
    assert log["auth"] == 1 and log["status"] == []
    assert poller._stopped is True


def test_poller_retries_room_whose_history_failed_even_without_new_activity():
    rest = _FakeRest()
    rest.subs = [{"rid": "r1", "t": "c", "ls": "2026-01-01T00:00:00.000Z"}]
    reglas = [_room_rule("r1")]
    poller, log = _poller(rest, reglas)
    _tick(poller, reglas)  # baseline

    rest.fail_history = {"r1"}
    _tick(poller, reglas)
    assert log["events"] == []

    rest.fail_history = set()
    rest.subs = []  # el delta de suscripciones ya no la trae
    rest.history["r1"] = [_msg("2026-01-01T00:05:00.000Z")]
    _tick(poller, reglas)
    assert len(log["events"]) == 1


def test_poller_reports_room_read_when_last_seen_catches_up():
    rest = _FakeRest()
    rest.subs = [{"rid": "r1", "t": "c", "ls": "2026-01-01T00:00:00.000Z"}]
    reglas = [_room_rule("r1")]
    poller, log = _poller(rest, reglas)
    _tick(poller, reglas)
    rest.history["r1"] = [_msg("2026-01-01T00:05:00.000Z")]
    _tick(poller, reglas)

    rest.history = {}
    rest.subs = [{"rid": "r1", "t": "c", "ls": "2026-01-01T00:10:00.000Z"}]
    _tick(poller, reglas)
    assert log["read"] == ["r1"]


def test_poller_ignores_results_after_stop():
    rest = _FakeRest()
    poller, log = _poller(rest, [])
    outcome = poller._poll_once([])
    poller.stop()
    poller._on_poll_done(outcome, None)
    assert log["status"] == []


def test_poller_unexpected_error_counts_as_failure():
    poller, log = _poller(_FakeRest(), [])
    poller._on_poll_done(None, RuntimeError("bug"))
    assert log["status"] == [False] and poller._failures == 1


def test_poller_exposes_username_after_successful_poll():
    poller, log = _poller(_FakeRest(), [])
    _tick(poller, [])
    assert poller.username == "yo" and poller.last_error is None


def test_poller_exposes_readable_error_after_failure():
    rest = _FakeRest()
    rest.fail_subs = RestApiError("Connection refused")
    poller, log = _poller(rest, [])
    _tick(poller, [])
    assert "Connection refused" in poller.last_error


def test_poller_auth_failure_has_readable_error():
    rest = _FakeRest()
    rest.fail_subs = AuthError("401", status=401)
    poller, log = _poller(rest, [])
    _tick(poller, [])
    assert "rechazadas" in poller.last_error


def test_poller_error_is_cleared_when_it_recovers():
    rest = _FakeRest()
    rest.fail_subs = RestApiError("down")
    poller, log = _poller(rest, [])
    _tick(poller, [])
    rest.fail_subs = None
    _tick(poller, [])
    assert poller.last_error is None
