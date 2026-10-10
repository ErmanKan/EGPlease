"""Tests for the TimeBar widget (src/gif_editor/ui/inspector/timebar.py).

The ``doc`` fixture opens 8 frames of 100 ms (total 800 ms). The bar is resized to
800 x 56 so pixel positions are easy to reason about.
"""

import time

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from gif_editor.core.decoder import GifSource
from gif_editor.ui.document import Document
from gif_editor.ui.inspector.timebar import TimeBar, format_seconds
from gifgen import make_gif, solid_frames

Y = 40  # a y inside the track


@pytest.fixture
def bar(qtbot, doc):
    w = TimeBar(doc)
    qtbot.addWidget(w)
    w.resize(800, 56)
    w.show()
    qtbot.waitExposed(w)
    return w


def pt(bar, ms):
    return QPoint(round(bar.x_for_time(ms)), Y)


def drag(qtbot, bar, start: QPoint, end: QPoint):
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(bar, pos=end)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=end)


def alt_move(bar, pos: QPoint):
    """Send a drag move with Alt held (qtbot.mouseMove cannot pass modifiers)."""
    p = QPointF(pos)
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        p,
        bar.mapToGlobal(p),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
    )
    QApplication.sendEvent(bar, ev)


def test_format_seconds():
    assert format_seconds(0) == "0 s"
    assert format_seconds(1500) == "1.5 s"
    assert format_seconds(100) == "0.1 s"


def test_basic_properties(bar):
    assert bar.accessibleName() == "Timeline"
    assert "Frame 1 of 8" in bar.accessibleDescription()
    assert bar.height() == 56
    assert bar.sizeHint().height() == 56
    assert bar.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_mapping_round_trip(bar):
    for t in (0, 1, 123.5, 400, 799, 800):
        assert bar.time_for_x(bar.x_for_time(t)) == pytest.approx(t)
    assert bar.x_for_time(0) < bar.x_for_time(800)
    assert bar.time_for_x(-100) == 0
    assert bar.time_for_x(10_000) == 800


def test_click_at_half_seeks_to_frame_4(qtbot, bar, doc):
    with qtbot.waitSignal(bar.scrubbed) as sig:
        qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(400, Y))
    assert doc.current_index == 4
    assert sig.args == [4]
    assert "Frame 5 of 8" in bar.accessibleDescription()
    assert doc.undo_stack.count() == 0  # seeking is not an edit


def test_drag_seeks_continuously(qtbot, bar, doc):
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 150))
    assert doc.current_index == 1
    qtbot.mouseMove(bar, pos=pt(bar, 650))
    assert doc.current_index == 6
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 650))


def test_handle_at(bar, doc):
    assert bar.handle_at(pt(bar, 0)) == "in"
    assert bar.handle_at(pt(bar, 800)) == "out"
    assert bar.handle_at(pt(bar, 400)) is None
    doc.set_trim(200, 300)
    assert bar.handle_at(pt(bar, 200)) == "in"
    assert bar.handle_at(pt(bar, 500)) == "out"
    assert bar.handle_at(pt(bar, 0)) is None


def test_in_handle_snaps_to_frame_boundary(qtbot, bar, doc):
    drag(qtbot, bar, pt(bar, 0), pt(bar, 250))
    start = doc.state.trim_start_ms
    assert start in (200, 300)
    assert start % 100 == 0
    assert doc.state.trim_duration_ms is None  # out stays at the end
    assert doc.current_index == 0  # handle drags do not seek


def test_alt_drag_is_free(qtbot, bar, doc):
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 0))
    alt_move(bar, pt(bar, 250))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 250))
    start = doc.state.trim_start_ms
    assert start % 100 != 0
    assert abs(start - 250) <= 2


def test_one_drag_is_one_undo_step(qtbot, bar, doc):
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 0))
    for t in (100, 150, 220, 310, 360):
        qtbot.mouseMove(bar, pos=pt(bar, t))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 360))
    assert doc.state.trim_start_ms == 400
    assert doc.undo_stack.count() == 1

    drag(qtbot, bar, pt(bar, 800), pt(bar, 600))
    assert doc.state.trim_duration_ms == 200
    assert doc.undo_stack.count() == 2

    doc.undo_stack.undo()
    assert (doc.state.trim_start_ms, doc.state.trim_duration_ms) == (400, None)
    doc.undo_stack.undo()
    assert (doc.state.trim_start_ms, doc.state.trim_duration_ms) == (0, None)


def test_in_drag_keeps_out_fixed(qtbot, bar, doc):
    doc.set_trim(0, 600, merge_key=None)
    drag(qtbot, bar, pt(bar, 0), pt(bar, 200))
    assert (doc.state.trim_start_ms, doc.state.trim_duration_ms) == (200, 400)


def test_out_handle_back_to_end_is_none(qtbot, bar, doc):
    drag(qtbot, bar, pt(bar, 800), pt(bar, 500))
    assert doc.state.trim_duration_ms == 500
    drag(qtbot, bar, pt(bar, 500), QPoint(799, Y))
    assert doc.state.trim_duration_ms is None
    # Alt near the end still clamps to the end -> None.
    drag(qtbot, bar, pt(bar, 800), pt(bar, 500))
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 500))
    alt_move(bar, QPoint(2000, Y))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(2000, Y))
    assert doc.state.trim_duration_ms is None


def test_in_less_than_out_enforced(qtbot, bar, doc):
    drag(qtbot, bar, pt(bar, 800), pt(bar, 500))  # out = 500
    drag(qtbot, bar, pt(bar, 0), QPoint(790, Y))  # in dragged far past out
    s, d = doc.state.trim_start_ms, doc.state.trim_duration_ms
    assert s == 400 and d == 100
    # free mode: still at least 10 ms window
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 400))
    alt_move(bar, QPoint(790, Y))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(790, Y))
    s, d = doc.state.trim_start_ms, doc.state.trim_duration_ms
    assert s == 490 and d == 10
    # out dragged before in: clamped to in + 10 ms
    doc.set_trim(300, 200, merge_key=None)
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=pt(bar, 500))
    alt_move(bar, QPoint(0, Y))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(0, Y))
    assert (doc.state.trim_start_ms, doc.state.trim_duration_ms) == (300, 10)


def test_cursor_and_tooltip(qtbot, bar):
    qtbot.mouseMove(bar, pos=pt(bar, 0))
    assert bar.cursor().shape() == Qt.CursorShape.SizeHorCursor
    qtbot.mouseMove(bar, pos=pt(bar, 450))
    assert bar.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert bar.tooltip_text(bar.x_for_time(450)) == "0.45 s · frame 5 of 8"


def test_keyboard(qtbot, bar, doc):
    bar.setFocus()
    qtbot.keyClick(bar, Qt.Key.Key_Right)
    assert doc.current_index == 1
    qtbot.keyClick(bar, Qt.Key.Key_Right)
    qtbot.keyClick(bar, Qt.Key.Key_Left)
    assert doc.current_index == 1
    qtbot.keyClick(bar, Qt.Key.Key_End)
    assert doc.current_index == 7
    qtbot.keyClick(bar, Qt.Key.Key_Home)
    assert doc.current_index == 0
    qtbot.keyClick(bar, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert doc.current_index == 7  # clamped
    qtbot.keyClick(bar, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    assert doc.current_index == 0


@pytest.mark.parametrize("width", [50, 3000])
def test_paints_at_extreme_widths(bar, doc, width):
    doc.delete_frames([2, 3, 5])
    doc.set_trim(100, 500)
    bar.setFocus()
    bar.resize(width, 56)
    img = bar.grab().toImage()
    assert img.width() >= width


def test_large_gif_paint_is_fast(qtbot, tmp_path):
    path = make_gif(tmp_path / "big.gif", solid_frames(1000, (4, 4)), 30)
    d = Document()
    d.set_source(GifSource.open(path), path)
    try:
        d.delete_frames(range(0, 1000, 2))  # 500 separate deleted runs
        d.set_trim(3000, 20_000)
        d.set_current_index(500)
        w = TimeBar(d)
        qtbot.addWidget(w)
        w.resize(800, 56)
        w.grab()  # warm-up (font loading etc.)
        best = min(_timed_grab(w) for _ in range(3))
        assert best < 0.030, f"paint took {best * 1000:.1f} ms"
    finally:
        d.close()


def _timed_grab(w):
    t0 = time.perf_counter()
    w.grab()
    return time.perf_counter() - t0


def test_no_source_no_crash(qtbot):
    d = Document()
    w = TimeBar(d)
    qtbot.addWidget(w)
    w.resize(800, 56)
    w.show()
    assert not w.isEnabled()
    assert w.accessibleDescription() == "No GIF loaded"
    w.grab()
    assert w.handle_at(QPoint(8, Y)) is None
    assert w.tooltip_text(100) == ""
    # A disabled widget ignores input; this must not change anything.
    qtbot.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(400, Y))
    assert d.undo_stack.count() == 0


def test_source_changes_refresh(qtbot, gif_path):
    d = Document()
    w = TimeBar(d)
    qtbot.addWidget(w)
    w.resize(800, 56)
    d.set_source(GifSource.open(gif_path), gif_path)
    assert w.isEnabled()
    assert w.time_for_x(400) == pytest.approx(400)
    d.close()
    assert not w.isEnabled()
    w.grab()
