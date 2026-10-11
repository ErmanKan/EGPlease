"""Qt smoke test: the toolkit loads headlessly and widgets render."""

from PySide6.QtWidgets import QLabel


def test_qt_renders_offscreen(qtbot):
    w = QLabel("GIF Editor")
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    img = w.grab().toImage()
    assert img.width() > 0 and img.height() > 0


def test_failed_selftest_explains_and_exits(qtbot, monkeypatch):
    """A broken build stops with a plain message (details kept) instead of misbehaving."""
    from PySide6.QtWidgets import QMessageBox

    from gif_editor import app
    from gif_editor.core import selftest

    def broken() -> None:
        raise selftest.SelfTestError("gif decoder args changed")

    shown = []

    def fake_exec(box: QMessageBox) -> int:
        shown.append((box.text(), box.informativeText(), box.detailedText()))
        return 0

    monkeypatch.setattr(selftest, "run_selftest", broken)
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    assert app.main(["gif-editor"]) == 1
    ((text, info, details),) = shown
    assert "can't start" in text and "Download it again" in info
    assert "gif decoder args changed" in details
