"""Tests for ``CropItem``: drag/resize on a real canvas, the Document contract, painting."""

import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from gif_editor.core.models import CropRect
from gif_editor.ui.document import Document
from gif_editor.ui.inspector.canvas import FrameCanvas
from gif_editor.ui.inspector.crop_item import CURSORS, MIN_DRAG_SIZE, CropItem

LEFT = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


@pytest.fixture
def canvas(qtbot, doc):
    c = FrameCanvas(doc)
    qtbot.addWidget(c)
    c.resize(400, 300)
    c.show()
    qtbot.waitExposed(c)
    c.set_zoom(4)  # 40x30 image -> 160x120 on screen: comfortable handle sizes
    return c


@pytest.fixture
def item(canvas, doc):
    it = CropItem(doc)
    canvas.scene().addItem(it)
    return it


# ----------------------------------------------------------------- helpers
def _send(view, kind, scene_pt, buttons, button=Qt.MouseButton.NoButton, mods=NOMOD):
    """Send a mouse event to the viewport at an (float) scene point."""
    local = view.viewportTransform().map(QPointF(*scene_pt))
    glob = QPointF(view.viewport().mapToGlobal(local.toPoint()))
    ev = QMouseEvent(kind, local, glob, button, buttons, mods)
    QApplication.sendEvent(view.viewport(), ev)


def press(view, pt, mods=NOMOD):
    _send(view, QEvent.Type.MouseButtonPress, pt, LEFT, LEFT, mods)


def move(view, pt, mods=NOMOD, buttons=LEFT):
    _send(view, QEvent.Type.MouseMove, pt, buttons, mods=mods)


def release(view, pt, mods=NOMOD):
    _send(view, QEvent.Type.MouseButtonRelease, pt, Qt.MouseButton.NoButton, LEFT, mods)


def drag(view, a, b, mods=NOMOD, steps=4):
    press(view, a, mods)
    for i in range(1, steps + 1):
        t = i / steps
        move(view, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), mods)
    release(view, b, mods)


def rect_tuple(item):
    r = item.crop_rect()
    return r.x(), r.y(), r.width(), r.height()


def set_crop(doc, x, y, w, h):
    doc.apply(doc.state.with_(crop=CropRect(x, y, w, h)), "test")


# ------------------------------------------------------------------ state
def test_initial_full_image_inactive_and_visible(item, doc):
    assert rect_tuple(item) == (0, 0, 40, 30)
    assert not item.crop_active
    assert item.isVisible()
    assert item.handle_at(QPointF(20, 15)) == "move"


def test_hidden_without_source(qtbot, item, doc):
    doc.close()
    assert not item.isVisible()
    assert item.crop_rect().isEmpty()
    assert item.handle_at(QPointF(5, 5)) is None
    fresh = Document()
    other = CropItem(fresh)
    assert not other.isVisible()
    assert other.boundingRect().isEmpty()


def test_bounding_rect_covers_image(item):
    assert item.boundingRect().contains(QRectF(0, 0, 40, 30))


# ------------------------------------------------------------------ drags
def test_interior_drag_moves_and_writes_only_on_release(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    depth = doc.undo_stack.count()
    previews = []
    item.previewChanged.connect(previews.append)
    press(canvas, (15, 15))
    move(canvas, (18, 17))
    move(canvas, (20, 17))
    assert item.dragging
    assert rect_tuple(item) == (15, 12, 20, 10)
    assert doc.state.crop == CropRect(10, 10, 20, 10)  # untouched mid-drag
    assert doc.undo_stack.count() == depth
    assert previews and previews[-1].toRect() == QRect(15, 12, 20, 10)
    release(canvas, (20, 17))
    assert not item.dragging
    assert doc.state.crop == CropRect(15, 12, 20, 10)
    assert doc.undo_stack.count() == depth + 1


def test_two_drags_are_two_undo_steps(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    depth = doc.undo_stack.count()
    drag(canvas, (15, 15), (17, 15))
    drag(canvas, (17, 15), (19, 15))
    assert doc.state.crop == CropRect(14, 10, 20, 10)
    assert doc.undo_stack.count() == depth + 2
    doc.undo_stack.undo()
    assert doc.state.crop == CropRect(12, 10, 20, 10)


def test_click_without_move_pushes_nothing(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    depth = doc.undo_stack.count()
    press(canvas, (15, 15))
    release(canvas, (15, 15))
    assert doc.undo_stack.count() == depth


def test_corner_resize_keeps_opposite_corner(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    drag(canvas, (30, 20), (34, 25))  # br
    assert doc.state.crop == CropRect(10, 10, 24, 15)
    drag(canvas, (10, 10), (6, 8))  # tl: br corner (34, 25) stays
    assert doc.state.crop == CropRect(6, 8, 28, 17)


def test_edge_resize_changes_one_dimension(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    drag(canvas, (30, 15), (35, 18))  # r edge midpoint; the y movement is ignored
    assert doc.state.crop == CropRect(10, 10, 25, 10)
    drag(canvas, (22, 10), (20, 5))  # t edge
    assert doc.state.crop == CropRect(10, 5, 25, 15)


def test_shift_corner_drag_keeps_aspect(canvas, item, doc):
    set_crop(doc, 4, 4, 20, 10)  # aspect 2:1
    drag(canvas, (24, 14), (32, 15), mods=SHIFT)  # br, mostly horizontal
    c = doc.state.crop
    assert (c.x, c.y) == (4, 4)
    assert c.w == 28
    assert abs(c.h - c.w / 2) <= 1
    drag(canvas, (4, 4), (0, 2), mods=SHIFT)  # tl; br corner stays fixed
    c2 = doc.state.crop
    assert (c2.x + c2.w, c2.y + c2.h) == (c.x + c.w, c.y + c.h)
    assert abs(c2.w / c2.h - 2.0) <= 1 / c2.h + 1e-9


def test_shift_resize_clamped_still_keeps_aspect(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    drag(canvas, (30, 20), (80, 30), mods=SHIFT)  # far outside: room limits the width
    c = doc.state.crop
    assert c.x + c.w <= 40 and c.y + c.h <= 30
    assert abs(c.h - c.w / 2) <= 1


def test_clamping_inside_image_and_min_size(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    drag(canvas, (20, 15), (200, 200))  # move far away
    assert doc.state.crop == CropRect(20, 20, 20, 10)
    drag(canvas, (20, 20), (-100, -100))  # tl far past the opposite corner + image
    assert doc.state.crop == CropRect(0, 0, 40, 30) or doc.state.crop is None
    set_crop(doc, 10, 10, 20, 10)
    drag(canvas, (30, 20), (-50, -50))  # br shrunk past tl: stops at 8x8
    assert doc.state.crop == CropRect(10, 10, MIN_DRAG_SIZE, MIN_DRAG_SIZE)


def test_drag_back_to_full_image_stores_none(canvas, item, doc):
    set_crop(doc, 0, 0, 30, 30)
    drag(canvas, (30, 15), (50, 15))  # r edge to (and past) the image edge
    assert doc.state.crop is None
    assert rect_tuple(item) == (0, 0, 40, 30)


def test_state_changed_during_drag_does_not_snap_back(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    press(canvas, (15, 15))
    move(canvas, (18, 15))
    doc.apply(doc.state.with_(crop=CropRect(0, 0, 5, 5)), "elsewhere")
    assert rect_tuple(item) == (13, 10, 20, 10)
    move(canvas, (19, 15))
    assert rect_tuple(item) == (14, 10, 20, 10)
    release(canvas, (19, 15))
    assert doc.state.crop == CropRect(14, 10, 20, 10)


def test_release_after_ignored_state_change_resyncs(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    press(canvas, (15, 15))
    doc.apply(doc.state.with_(crop=CropRect(0, 0, 5, 5)), "elsewhere")
    release(canvas, (15, 15))  # no movement: nothing applied, rect follows the doc
    assert rect_tuple(item) == (0, 0, 5, 5)


def test_press_outside_rect_is_ignored(canvas, item, doc):
    set_crop(doc, 10, 10, 10, 10)
    press(canvas, (35, 25))
    assert not item.dragging
    release(canvas, (35, 25))


# --------------------------------------------------------------- handle_at
@pytest.mark.parametrize("zoom", [1.0, 4.0])
def test_handle_at_all_parts(canvas, item, doc, zoom):
    canvas.set_zoom(zoom)
    set_crop(doc, 10, 5, 20, 20)  # 20x20: big enough for distinct handles at zoom 1
    expect = {
        "tl": (10, 5),
        "t": (20, 5),
        "tr": (30, 5),
        "r": (30, 15),
        "br": (30, 25),
        "b": (20, 25),
        "bl": (10, 25),
        "l": (10, 15),
        "move": (20, 15),
    }
    for name, (x, y) in expect.items():
        assert item.handle_at(QPointF(x, y)) == name, name
    # Just outside the corner, within the screen-px tolerance: still the corner.
    eps = 4 / zoom
    assert item.handle_at(QPointF(10 - eps, 5 - eps)) == "tl"
    assert item.handle_at(QPointF(2, 28)) is None
    assert item.handle_at(QPointF(-10, -10)) is None


def test_handle_tolerance_is_in_screen_pixels(canvas, item, doc):
    set_crop(doc, 10, 5, 20, 20)
    canvas.set_zoom(1)
    assert item.handle_at(QPointF(10 + 5, 15)) == "l"  # 5 screen px from the edge
    canvas.set_zoom(4)
    assert item.handle_at(QPointF(10 + 5, 15)) == "move"  # 20 screen px: interior


def test_handle_at_without_view_assumes_zoom_one(doc):
    it = CropItem(doc)
    assert it.handle_at(QPointF(5, 15)) == "l"
    assert it.handle_at(QPointF(20, 15)) == "move"


def test_hover_cursor(canvas, item, doc):
    set_crop(doc, 10, 5, 20, 20)
    move(canvas, (20, 15), buttons=Qt.MouseButton.NoButton)
    assert canvas.viewport().cursor().shape() == CURSORS["move"]
    move(canvas, (30, 25), buttons=Qt.MouseButton.NoButton)
    assert canvas.viewport().cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    move(canvas, (20, 5), buttons=Qt.MouseButton.NoButton)
    assert canvas.viewport().cursor().shape() == Qt.CursorShape.SizeVerCursor


def test_handle_outside_image_is_draggable(canvas, item, doc):
    # Full image: the br handle is half outside the image, where only the child exists.
    press(canvas, (40.75, 30.75))
    assert item.dragging
    move(canvas, (30.75, 20.75))
    release(canvas, (30.75, 20.75))
    assert doc.state.crop == CropRect(0, 0, 30, 20)


# ------------------------------------------------------ discrete operations
def test_activate_and_reset_signals(qtbot, item, doc):
    with qtbot.waitSignal(item.cropActiveChanged) as sig:
        item.activate()
    assert sig.args == [True]
    assert doc.state.crop == CropRect(4, 3, 32, 24)
    assert item.crop_active
    assert rect_tuple(item) == (4, 3, 32, 24)
    depth = doc.undo_stack.count()
    item.activate()  # already active: no-op
    assert doc.undo_stack.count() == depth
    with qtbot.waitSignal(item.cropActiveChanged) as sig:
        item.reset()
    assert sig.args == [False]
    assert doc.state.crop is None


def test_active_signal_only_on_change(item, doc):
    seen = []
    item.cropActiveChanged.connect(seen.append)
    set_crop(doc, 1, 1, 10, 10)
    set_crop(doc, 2, 2, 10, 10)
    doc.apply(doc.state.with_(speed=2.0), "speed")
    assert seen == [True]


def test_undo_redo_moves_rectangle(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    drag(canvas, (15, 15), (19, 15))
    assert rect_tuple(item) == (14, 10, 20, 10)
    doc.undo_stack.undo()
    assert rect_tuple(item) == (10, 10, 20, 10)
    doc.undo_stack.undo()
    assert rect_tuple(item) == (0, 0, 40, 30)
    doc.undo_stack.redo()
    assert rect_tuple(item) == (10, 10, 20, 10)


def test_nudge_and_resize_one_step_each_and_clamped(item, doc):
    set_crop(doc, 10, 10, 20, 10)
    depth = doc.undo_stack.count()
    item.nudge(1, 0)
    assert doc.state.crop == CropRect(11, 10, 20, 10)
    item.nudge(1, 0)
    assert doc.undo_stack.count() == depth + 2  # never merged
    item.resize(1, 1)
    assert doc.state.crop == CropRect(12, 10, 21, 11)
    assert doc.undo_stack.count() == depth + 3
    item.nudge(100, 100)
    assert doc.state.crop == CropRect(19, 19, 21, 11)
    item.resize(100, 100)  # already touching the edges: no change, no step
    assert doc.state.crop == CropRect(19, 19, 21, 11)
    item.resize(-100, -100)
    assert doc.state.crop == CropRect(19, 19, 1, 1)
    item.nudge(-100, -100)
    assert doc.state.crop == CropRect(0, 0, 1, 1)


def test_nudge_without_crop_is_noop(item, doc):
    item.nudge(1, 1)
    assert doc.state.crop is None
    assert doc.undo_stack.count() == 0


def test_resize_from_full_creates_crop(item, doc):
    item.resize(-1, 0)
    assert doc.state.crop == CropRect(0, 0, 39, 30)


def test_drag_does_not_merge_with_spinbox_key(canvas, item, doc):
    doc.apply(doc.state.with_(crop=CropRect(10, 10, 20, 10)), "Crop", merge_key="crop")
    depth = doc.undo_stack.count()
    drag(canvas, (15, 15), (17, 15))
    doc.apply(doc.state.with_(crop=CropRect(0, 0, 5, 5)), "Crop", merge_key="crop")
    assert doc.undo_stack.count() == depth + 2


def test_set_tool_enabled(canvas, item, doc):
    item.set_tool_enabled(False)
    assert not item.isVisible()
    assert not item.tool_enabled
    press(canvas, (20, 15))
    assert not item.dragging
    release(canvas, (20, 15))
    item.nudge(1, 1)
    assert doc.undo_stack.count() == 0
    item.set_tool_enabled(True)
    assert item.isVisible()
    doc.close()
    assert not item.isVisible()


def test_disable_mid_drag_abandons_it(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    press(canvas, (15, 15))
    move(canvas, (20, 15))
    item.set_tool_enabled(False)
    assert not item.dragging
    assert rect_tuple(item) == (10, 10, 20, 10)
    assert doc.state.crop == CropRect(10, 10, 20, 10)


# ------------------------------------------------------------------- paint
def _brightness(canvas, scene_pt):
    img = canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    dpr = img.devicePixelRatio()
    p = canvas.viewportTransform().map(QPointF(*scene_pt)) * dpr
    p += QPointF(canvas.viewport().pos()) * dpr
    c = QColor(img.pixel(int(p.x()), int(p.y())))
    return c.red() + c.green() + c.blue()


@pytest.mark.parametrize("zoom", [0.5, 1.0, 4.0])
def test_paint_at_zooms(qtbot, canvas, item, doc, zoom):
    canvas.set_zoom(zoom)
    canvas.grab()
    item.activate()
    canvas.grab()
    press(canvas, (20, 15))
    move(canvas, (21, 15))
    canvas.grab()  # thirds + '@ X,Y' label while dragging
    release(canvas, (21, 15))


def test_outside_crop_is_dimmed(canvas, item, doc):
    pt = (38.5, 28.5)  # outside the activate() crop (4, 3, 32, 24), clear of handles
    before = _brightness(canvas, pt)
    item.activate()
    after = _brightness(canvas, pt)
    assert after < before * 0.7
    inside = _brightness(canvas, (20, 20))
    assert inside == pytest.approx(before, abs=6)


def test_label_text(canvas, item, doc):
    set_crop(doc, 10, 10, 20, 10)
    assert item._label.text == "20\u00d710"
    press(canvas, (15, 15))
    move(canvas, (16, 15))
    assert item._label.text == "20\u00d710 @ 11,10"
    release(canvas, (16, 15))
    assert item._label.text == "20\u00d710"
