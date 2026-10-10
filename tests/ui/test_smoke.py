"""Qt smoke test: the toolkit loads headlessly and widgets render."""

from PySide6.QtWidgets import QLabel


def test_qt_renders_offscreen(qtbot):
    w = QLabel("GIF Editor")
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    img = w.grab().toImage()
    assert img.width() > 0 and img.height() > 0
