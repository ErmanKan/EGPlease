"""Tests for ``FrameCanvas``: frame display, zoom API, overlays, empty state, mapping."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage

from gif_editor.ui.document import Document
from gif_editor.ui.inspector.canvas import (
    MAX_ZOOM,
    MIN_ZOOM,
    PLACEHOLDER_TEXT,
    FrameCanvas,
)
from gifgen import PALETTE


@pytest.fixture
def canvas(qtbot, doc):
    c = FrameCanvas(doc)
    qtbot.addWidget(c)
    c.resize(400, 300)
    c.show()
    qtbot.waitExposed(c)
    return c


def _pixel(canvas: FrameCanvas, x: int = 5, y: int = 5) -> tuple[int, int, int]:
    img = canvas.image_item.pixmap().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    c = QColor(img.pixel(x, y))
    return c.red(), c.green(), c.blue()


def _close(a, b, tol=3):
    return all(abs(p - q) <= tol for p, q in zip(a, b, strict=True))


def test_pixmap_matches_current_frame(canvas, doc):
    assert canvas.image_item.pixmap().size().toTuple() == (40, 30)
    assert _close(_pixel(canvas), PALETTE[0])
    doc.set_current_index(3)
    assert _close(_pixel(canvas), PALETTE[3])
    assert _close(_pixel(canvas, 39, 29), PALETTE[3])


def test_accessible_and_refuses_drops(canvas):
    assert canvas.accessibleName() == "Frame canvas"
    assert not canvas.acceptDrops()
    assert not canvas.viewport().acceptDrops()


def test_default_is_fit_and_fits_viewport(canvas):
    assert canvas.fit_mode
    canvas.set_zoom(10)
    canvas.zoom_fit()
    assert canvas.fit_mode
    shown = canvas.mapFromScene(canvas.image_rect()).boundingRect()
    vp = canvas.viewport().rect()
    assert vp.contains(shown)
    # One dimension is limited by the margin: the image is as big as allowed.
    assert shown.width() >= vp.width() - 40 or shown.height() >= vp.height() - 40


def test_refits_on_resize_in_fit_mode(qtbot, canvas):
    z = canvas.zoom
    canvas.resize(800, 600)
    qtbot.waitUntil(lambda: canvas.zoom > z)
    canvas.zoom_actual()
    canvas.resize(300, 200)
    qtbot.wait(20)
    assert canvas.zoom == 1.0


def test_zoom_actual_clamp_and_signal(qtbot, canvas):
    with qtbot.waitSignal(canvas.zoomChanged) as sig:
        canvas.zoom_actual()
    assert canvas.zoom == 1.0
    assert sig.args == [1.0]
    canvas.set_zoom(1000)
    assert canvas.zoom == MAX_ZOOM
    canvas.set_zoom(0.0001)
    assert canvas.zoom == MIN_ZOOM
    canvas.set_zoom(2)
    canvas.zoom_in()
    assert canvas.zoom == pytest.approx(2.5)
    canvas.zoom_out()
    assert canvas.zoom == pytest.approx(2.0)


def test_fit_mode_flips_on_manual_zoom(canvas):
    canvas.zoom_fit()
    assert canvas.fit_mode
    canvas.zoom_in()
    assert not canvas.fit_mode
    canvas.zoom_fit()
    canvas.zoom_actual()
    assert not canvas.fit_mode


def test_transformation_mode_flips_at_one(canvas):
    canvas.set_zoom(0.5)
    assert canvas.image_item.transformationMode() == Qt.TransformationMode.SmoothTransformation
    canvas.set_zoom(1.0)
    assert canvas.image_item.transformationMode() == Qt.TransformationMode.FastTransformation
    canvas.set_zoom(4.0)
    assert canvas.image_item.transformationMode() == Qt.TransformationMode.FastTransformation


def test_deleted_overlay(qtbot, canvas, doc):
    assert not canvas.deleted_overlay_visible
    doc.delete_frames([0])
    assert canvas.deleted_overlay_visible
    canvas.grab()  # paints drawForeground with the overlay; must not crash
    doc.set_current_index(1)
    assert not canvas.deleted_overlay_visible
    doc.set_current_index(0)
    doc.undo_stack.undo()
    assert not canvas.deleted_overlay_visible


def test_empty_document_shows_placeholder(qtbot):
    d = Document()
    c = FrameCanvas(d)
    qtbot.addWidget(c)
    c.resize(300, 200)
    c.show()
    qtbot.waitExposed(c)
    assert c.placeholder_visible
    assert PLACEHOLDER_TEXT == "Open a GIF (Ctrl+O) or drop it here"
    assert c.image_item.pixmap().isNull()
    assert c.image_rect().isEmpty()
    assert not c.grab().isNull()
    c.zoom_fit()  # harmless with nothing open
    c.zoom_in()


def test_close_clears_image(canvas, doc):
    assert not canvas.image_item.pixmap().isNull()
    doc.close()
    assert canvas.image_item.pixmap().isNull()
    assert canvas.placeholder_visible
    assert not canvas.deleted_overlay_visible


@pytest.mark.parametrize("zoom", [1.0, 2.0])
def test_map_to_image(canvas, zoom):
    canvas.set_zoom(zoom)
    origin = canvas.mapFromScene(QPointF(0, 0))
    p = canvas.map_to_image(origin + QPoint(20, 10))
    assert p.x() == pytest.approx(20 / zoom, abs=0.51)
    assert p.y() == pytest.approx(10 / zoom, abs=0.51)
    # Float positions are accepted too and map exactly through the view transform.
    exact = canvas.viewportTransform().map(QPointF(7.5, 3.25))
    q = canvas.map_to_image(exact)
    assert (q.x(), q.y()) == pytest.approx((7.5, 3.25))


def test_ctrl_wheel_zooms_plain_wheel_does_not(qtbot, canvas):
    from PySide6.QtCore import QPointF as P
    from PySide6.QtGui import QWheelEvent

    canvas.set_zoom(1.0)
    pos = P(canvas.viewport().rect().center())

    def wheel(mods):
        ev = QWheelEvent(
            pos,
            P(canvas.viewport().mapToGlobal(pos.toPoint())),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            mods,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        canvas.wheelEvent(ev)

    wheel(Qt.KeyboardModifier.ControlModifier)
    assert canvas.zoom == pytest.approx(1.25)
    wheel(Qt.KeyboardModifier.NoModifier)
    assert canvas.zoom == pytest.approx(1.25)


def test_space_and_middle_drag_toggle_hand_drag(qtbot, canvas):
    from PySide6.QtWidgets import QGraphicsView

    canvas.setFocus()
    qtbot.keyPress(canvas, Qt.Key.Key_Space)
    assert canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    qtbot.keyRelease(canvas, Qt.Key.Key_Space)
    assert canvas.dragMode() == QGraphicsView.DragMode.NoDrag

    vp = canvas.viewport()
    qtbot.mousePress(vp, Qt.MouseButton.MiddleButton, pos=QPoint(50, 50))
    assert canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    qtbot.mouseRelease(vp, Qt.MouseButton.MiddleButton, pos=QPoint(60, 60))
    assert canvas.dragMode() == QGraphicsView.DragMode.NoDrag
    assert canvas.isInteractive()


def test_middle_drag_pans_when_zoomed(qtbot, canvas):
    canvas.set_zoom(16)  # 640x480 image overflows the 400x300 viewport
    h = canvas.horizontalScrollBar()
    before = h.value()
    vp = canvas.viewport()
    qtbot.mousePress(vp, Qt.MouseButton.MiddleButton, pos=QPoint(200, 150))
    qtbot.mouseMove(vp, QPoint(150, 150))
    qtbot.mouseRelease(vp, Qt.MouseButton.MiddleButton, pos=QPoint(150, 150))
    assert h.value() != before
