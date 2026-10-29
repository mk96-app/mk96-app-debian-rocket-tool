from mk96_app_debian_rocket_tool.chat_window import trailing_new_start


def _msg(sender, text="hola"):
    return {"sender": sender, "text": text}


def test_no_messages_highlights_nothing():
    assert trailing_new_start([], "yo") == 0


def test_last_message_from_self_highlights_nothing():
    messages = [_msg("otro"), _msg("yo")]
    assert trailing_new_start(messages, "yo") == 2


def test_trailing_run_from_others_is_highlighted():
    messages = [_msg("yo"), _msg("otro"), _msg("otro")]
    assert trailing_new_start(messages, "yo") == 1


def test_all_messages_from_others_highlights_everything():
    messages = [_msg("otro"), _msg("otro")]
    assert trailing_new_start(messages, "yo") == 0


def test_unknown_own_username_highlights_nothing():
    messages = [_msg("otro"), _msg("otro")]
    assert trailing_new_start(messages, None) == 2
