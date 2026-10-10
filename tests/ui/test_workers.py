import threading

from gif_editor.ui.workers import run_async


def test_result_delivered_on_gui_thread(qtbot):
    main = threading.get_ident()
    got = {}

    def work():
        got["worker"] = threading.get_ident()
        return 42

    def done(v):
        got["value"] = v
        got["cb"] = threading.get_ident()

    run_async(work, on_done=done)
    qtbot.waitUntil(lambda: "value" in got, timeout=3000)
    assert got["value"] == 42 and got["cb"] == main and got["worker"] != main


def test_error_and_progress(qtbot):
    got = {"progress": []}

    def work(progress):
        progress(1, 2)
        progress(2, 2)
        raise RuntimeError("boom")

    run_async(
        work,
        on_progress=lambda d, t: got["progress"].append((d, t)),
        on_error=lambda msg, exc: got.setdefault("err", msg),
    )
    qtbot.waitUntil(lambda: "err" in got, timeout=3000)
    assert got["err"] == "boom" and got["progress"] == [(1, 2), (2, 2)]
