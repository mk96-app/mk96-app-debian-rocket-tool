from mk96_app_debian_rocket_tool.rules import match_rule, rooms_to_mark_read


def _room_rule(room_id, sonido_id="cat", activa=True, rule_id="r1"):
    return {
        "id": rule_id,
        "tipo": "sala",
        "room_id": room_id,
        "sonido_id": sonido_id,
        "etiqueta": "Regla de prueba",
        "activa": activa,
    }


def _mention_rule(sonido_id="mention-bell", activa=True, rule_id="m1"):
    return {
        "id": rule_id,
        "tipo": "mencion",
        "sonido_id": sonido_id,
        "etiqueta": "Menciones",
        "activa": activa,
    }


def test_no_rules_no_match():
    event = {"rid": "room1", "mentioned": False}
    assert match_rule(event, []) is None


def test_room_rule_matches_by_rid():
    event = {"rid": "room1", "mentioned": False}
    rule = _room_rule("room1")
    assert match_rule(event, [rule]) == rule


def test_room_rule_does_not_match_other_room():
    event = {"rid": "room2", "mentioned": False}
    rule = _room_rule("room1")
    assert match_rule(event, [rule]) is None


def test_inactive_room_rule_is_ignored():
    event = {"rid": "room1", "mentioned": False}
    rule = _room_rule("room1", activa=False)
    assert match_rule(event, [rule]) is None


def test_mention_rule_matches_when_mentioned():
    event = {"rid": "room3", "mentioned": True}
    rule = _mention_rule()
    assert match_rule(event, [rule]) == rule


def test_mention_rule_ignored_when_not_mentioned():
    event = {"rid": "room3", "mentioned": False}
    rule = _mention_rule()
    assert match_rule(event, [rule]) is None


def test_inactive_mention_rule_is_ignored():
    event = {"rid": "room3", "mentioned": True}
    rule = _mention_rule(activa=False)
    assert match_rule(event, [rule]) is None


def test_room_rule_takes_priority_over_mention_rule():
    event = {"rid": "room1", "mentioned": True}
    room_rule = _room_rule("room1")
    mention_rule = _mention_rule()
    assert match_rule(event, [mention_rule, room_rule]) == room_rule


def test_falls_back_to_mention_rule_when_room_not_configured():
    event = {"rid": "room9", "mentioned": True}
    room_rule = _room_rule("room1")
    mention_rule = _mention_rule()
    assert match_rule(event, [room_rule, mention_rule]) == mention_rule


def _sub(rid, unread=0, alert=False):
    return {"rid": rid, "unread": unread, "alert": alert}


def test_rooms_to_mark_read_all_picks_only_unread():
    subs = [_sub("a", unread=3), _sub("b"), _sub("c", alert=True)]
    assert rooms_to_mark_read(subs, [], solo_no_configuradas=False) == ["a", "c"]


def test_rooms_to_mark_read_all_includes_configured_rooms():
    subs = [_sub("a", unread=1), _sub("b", unread=1)]
    rules = [_room_rule("a")]
    assert rooms_to_mark_read(subs, rules, solo_no_configuradas=False) == ["a", "b"]


def test_rooms_to_mark_read_unconfigured_skips_active_room_rule():
    subs = [_sub("a", unread=1), _sub("b", unread=1)]
    rules = [_room_rule("a")]
    assert rooms_to_mark_read(subs, rules, solo_no_configuradas=True) == ["b"]


def test_rooms_to_mark_read_unconfigured_includes_silenced_room_rule():
    subs = [_sub("a", unread=1)]
    rules = [_room_rule("a", activa=False)]
    assert rooms_to_mark_read(subs, rules, solo_no_configuradas=True) == ["a"]


def test_rooms_to_mark_read_unconfigured_ignores_mention_rule():
    subs = [_sub("a", unread=1)]
    assert rooms_to_mark_read(subs, [_mention_rule()], solo_no_configuradas=True) == ["a"]


def test_rooms_to_mark_read_skips_subs_without_rid():
    assert rooms_to_mark_read([{"unread": 2}], [], solo_no_configuradas=False) == []


def test_mention_all_ignored_by_default():
    event = {"rid": "room1", "mentioned": False, "mentioned_all": True}
    assert match_rule(event, [_mention_rule()]) is None


def test_mention_all_matches_when_rule_opts_in():
    event = {"rid": "room1", "mentioned": False, "mentioned_all": True}
    rule = {**_mention_rule(), "mencion_todos": True}
    assert match_rule(event, [rule]) == rule


def test_mention_all_does_not_match_inactive_rule():
    event = {"rid": "room1", "mentioned": False, "mentioned_all": True}
    rule = {**_mention_rule(activa=False), "mencion_todos": True}
    assert match_rule(event, [rule]) is None
