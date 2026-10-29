import threading

from gi.repository import GLib

from mk96_app_debian_rocket_tool.async_utils import run_in_thread


def _run(work):
    loop = GLib.MainLoop()
    got = {}

    def done(result, error):
        got["thread"] = threading.current_thread()
        got["result"], got["error"] = result, error
        loop.quit()

    run_in_thread(work, done)
    GLib.timeout_add_seconds(5, loop.quit)
    loop.run()
    return got


def test_result_is_delivered_on_the_main_thread_not_the_worker():
    worker = {}

    def work():
        worker["thread"] = threading.current_thread()
        return 42

    got = _run(work)
    assert got["result"] == 42 and got["error"] is None
    assert worker["thread"] is not threading.main_thread()
    assert got["thread"] is threading.main_thread()


def test_exception_is_delivered_as_error():
    def work():
        raise ValueError("x")

    got = _run(work)
    assert got["result"] is None and isinstance(got["error"], ValueError)
