"""Interactive crop rectangle drawn on top of the frame canvas.

``CropItem`` is a ``QGraphicsObject`` that the canvas adds to its scene. The canvas'
scene uses *source image pixels* as coordinates (scene point (x, y) == pixel (x, y)), and
the item sits at (0, 0) with no transform of its own, so its rectangle maps one-to-one
onto ``CropRect(x, y, w, h)``. Zooming only changes the view transform; nothing here
needs zoom maths except the two things that must stay a fixed size *on screen*: the
handles and the size label (child items with ``ItemIgnoresTransformations``) and the
handle hit areas in ``handle_at`` (converted with the view zoom).

Document contract:

* While the mouse is dragging, the item never writes to ``Document``. It only updates its
  own rectangle, repaints and emits ``previewChanged``. On release it applies the final
  rectangle as ONE undo step with a per-drag merge key ``"crop-drag-N"``.
* ``nudge`` / ``resize`` / ``activate`` / ``reset`` apply immediately, one undo step each.
* The visible rectangle always follows ``doc.state.crop`` (full image when ``None``), so
  undo/redo and the crop panel move it too, except mid-drag where the pointer wins.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

from gif_editor.core.models import CropRect
from gif_editor.ui.document import Document

HANDLE_PX = 9.0  # visible handle side, logical screen px (constant at every zoom)
HANDLE_HIT_PX = 13.0  # clickable square around each handle centre, logical screen px
MIN_DRAG_SIZE = 8  # smallest crop a drag can produce (image px), unless the image is smaller
ACTIVATE_INSET = 0.10  # activate(): inset the full image by 10% on each side
DIM_COLOR = QColor(0, 0, 0, 128)  # ~50% black over the area that will be cropped away
# Half a cosmetic pen pixel at the canvas' minimum zoom (0.05) is 10 image px; the bounds
# must include it so the border at the image edge is repainted correctly.
BOUNDS_MARGIN = 12.0
TIMES = "\u00d7"  # multiplication sign (escaped so ruff's confusable-char rule stays quiet)
DRAG_NAMES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")

CURSORS: dict[str, Qt.CursorShape] = {
    "tl": Qt.CursorShape.SizeFDiagCursor,
    "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor,
    "bl": Qt.CursorShape.SizeBDiagCursor,
    "l": Qt.CursorShape.SizeHorCursor,
    "r": Qt.CursorShape.SizeHorCursor,
    "t": Qt.CursorShape.SizeVerCursor,
    "b": Qt.CursorShape.SizeVerCursor,
    "move": Qt.CursorShape.SizeAllCursor,
}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


class _HandleItem(QGraphicsItem):
    """One fixed-screen-size resize handle (a child of ``CropItem``).

    ``ItemIgnoresTransformations`` makes Qt draw this item in *device* (screen) pixels
    while still placing its origin at ``pos()`` in the parent's image-pixel coordinates.
    So the square stays ~9 px at 5% and at 3200% zoom. Its bounding rect is the larger
    hit square: mouse presses that land on it (also outside the image, where the parent
    has no area) are forwarded to the parent, which decides with ``handle_at``.
    """

    def __init__(self, name: str, parent: CropItem) -> None:
        """Create the handle ``name`` (one of ``DRAG_NAMES``) under ``parent``."""
        super().__init__(parent)
        self.name = name
        self._crop = parent
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setCursor(CURSORS[name])
        self.setAcceptHoverEvents(True)

    def boundingRect(self) -> QRectF:
        """The hit square, centred on the handle position (screen px)."""
        h = HANDLE_HIT_PX / 2
        return QRectF(-h, -h, HANDLE_HIT_PX, HANDLE_HIT_PX)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        """White square with a dark 1-px border."""
        h = HANDLE_PX / 2
        pen = QPen(QColor(20, 20, 20))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRect(QRectF(-h, -h, HANDLE_PX - 1, HANDLE_PX - 1))

    # Forward the mouse to the parent; it owns the drag logic and the Document contract.
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Start a parent drag; ignore (propagate) if the parent declines."""
        self._crop._press(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Continue the parent drag (this handle is the mouse grabber)."""
        self._crop._move(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Finish the parent drag."""
        self._crop._release(event)


class _LabelItem(QGraphicsItem):
    """Fixed-screen-size 'WxH' size label: white text on a semi-opaque dark plate.

    The plate makes the text legible on both light and dark images. It ignores the
    mouse, so clicks on it reach the crop interior underneath (a move).
    """

    OFFSET = HANDLE_PX / 2 + 4  # screen px from the crop's top-left corner (clear of 'tl')
    PAD = 3.0

    def __init__(self, parent: CropItem) -> None:
        """Create an empty label under ``parent``."""
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._font = QFont()
        self._font.setPointSizeF(8.5)
        self._text = ""
        self._rect = QRectF()

    @property
    def text(self) -> str:
        """The text currently shown."""
        return self._text

    def set_text(self, text: str) -> None:
        """Change the text (geometry change announced to the scene first)."""
        if text == self._text:
            return
        self.prepareGeometryChange()
        self._text = text
        fm = QFontMetricsF(self._font)
        self._rect = QRectF(
            self.OFFSET,
            self.OFFSET,
            fm.horizontalAdvance(text) + 2 * self.PAD,
            fm.height() + self.PAD,
        )

    def boundingRect(self) -> QRectF:
        """The plate rectangle in screen px relative to the crop's top-left corner."""
        return QRectF(self._rect)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        """Dark rounded plate, then the text."""
        if not self._text:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(self._rect, 3, 3)
        painter.setFont(self._font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self._rect, int(Qt.AlignmentFlag.AlignCenter), self._text)


class CropItem(QGraphicsObject):
    """Draggable crop rectangle over the canvas image, synced with ``doc.state.crop``.

    Coordinates are image pixels (the canvas' scene convention). The rectangle is kept as
    an integer ``QRect`` inside the image at all times.
    """

    previewChanged = Signal(QRectF)  # live rectangle while dragging (image px)
    cropActiveChanged = Signal(bool)  # doc.state.crop switched between None / set

    def __init__(self, doc: Document, parent: QGraphicsItem | None = None) -> None:
        """Create the overlay bound to ``doc``; add it to the canvas scene at (0, 0)."""
        super().__init__(parent)
        self._doc = doc
        self._img_w = 0
        self._img_h = 0
        self._rect = QRect()
        self._tool_enabled = True
        self._active = False
        # Drag state: handle name ("move", "tl", ...) or None when idle.
        self._drag: str | None = None
        self._drag_counter = 0  # incremented on every press -> unique merge key per drag
        self._press_pos = QPointF()
        self._press_rect = QRect()

        self.setZValue(10)  # above the frame pixmap
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

        self._handles = {name: _HandleItem(name, self) for name in DRAG_NAMES}
        self._label = _LabelItem(self)

        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._on_state_changed)
        self._on_source_changed()

    # ------------------------------------------------------------- public API
    @property
    def crop_active(self) -> bool:
        """True when the document has a crop (``doc.state.crop is not None``)."""
        return self._doc.is_open and self._doc.state.crop is not None

    @property
    def tool_enabled(self) -> bool:
        """Whether the crop tool is on (see ``set_tool_enabled``)."""
        return self._tool_enabled

    @property
    def dragging(self) -> bool:
        """True between a mouse press on the rectangle and its release."""
        return self._drag is not None

    def crop_rect(self) -> QRect:
        """The rectangle currently shown, in integer image pixels (live during a drag)."""
        return QRect(self._rect)

    def image_size(self) -> tuple[int, int]:
        """Source canvas size ``(w, h)``; ``(0, 0)`` when nothing is open."""
        return self._img_w, self._img_h

    def set_tool_enabled(self, enabled: bool) -> None:
        """Turn the crop tool on/off. Off = hidden and ignoring the mouse."""
        enabled = bool(enabled)
        if enabled == self._tool_enabled:
            return
        self._tool_enabled = enabled
        if not enabled and self._drag is not None:
            self._drag = None  # abandon the drag; nothing was written to the Document
            self._sync_from_doc()
        self._update_visibility()

    def handle_at(self, scene_pos: QPointF) -> str | None:
        """Which part of the rectangle is at ``scene_pos``.

        Returns ``'tl','t','tr','r','br','b','bl','l'`` for handles, ``'move'`` for the
        interior and ``None`` elsewhere (or when hidden / nothing is open). Hit areas are
        ``HANDLE_HIT_PX`` *screen* pixels, so they are converted to image pixels with the
        view zoom; corners win over edges, edges over the interior. An edge is grabbable
        along its whole length, not only at its midpoint handle.
        """
        if not self.isVisible() or self._rect.isEmpty():
            return None
        p = self.mapFromScene(QPointF(scene_pos))
        tol = HANDLE_HIT_PX / 2 / self._view_zoom()
        r = QRectF(self._rect)
        left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
        near_l = abs(p.x() - left) <= tol
        near_r = abs(p.x() - right) <= tol
        near_t = abs(p.y() - top) <= tol
        near_b = abs(p.y() - bottom) <= tol
        if near_t and near_l:
            return "tl"
        if near_t and near_r:
            return "tr"
        if near_b and near_r:
            return "br"
        if near_b and near_l:
            return "bl"
        in_x = left <= p.x() <= right
        in_y = top <= p.y() <= bottom
        if near_t and in_x:
            return "t"
        if near_b and in_x:
            return "b"
        if near_l and in_y:
            return "l"
        if near_r and in_y:
            return "r"
        if in_x and in_y:
            return "move"
        return None

    def nudge(self, dx: int, dy: int) -> None:
        """Move the crop by ``(dx, dy)`` image pixels (clamped), as one undo step.

        ``merge_key=None`` on purpose: every arrow-key press is its own undo step, and a
        nudge must never merge into a preceding drag or a spinbox scrub ('crop').
        """
        if not self._can_edit():
            return
        r = self._doc_rect()
        x = _clamp(r.x() + int(dx), 0, self._img_w - r.width())
        y = _clamp(r.y() + int(dy), 0, self._img_h - r.height())
        self._commit(QRect(x, y, r.width(), r.height()), "Move crop", None)

    def resize(self, dw: int, dh: int) -> None:
        """Grow/shrink the right and bottom edges by ``(dw, dh)`` (clamped, min 1).

        One undo step per call (``merge_key=None``), for the same reason as ``nudge``.
        """
        if not self._can_edit():
            return
        r = self._doc_rect()
        w = _clamp(r.width() + int(dw), 1, self._img_w - r.x())
        h = _clamp(r.height() + int(dh), 1, self._img_h - r.y())
        self._commit(QRect(r.x(), r.y(), w, h), "Resize crop", None)

    def activate(self) -> None:
        """Start cropping: if there is no crop, set one 10% inside each image edge.

        A visible box appears that the user can then adjust. No-op if a crop exists or the
        image is too small (1-2 px) to inset.
        """
        if not self._can_edit() or self._doc.state.crop is not None:
            return
        w, h = self._img_w, self._img_h
        ix = int(w * ACTIVATE_INSET)
        iy = int(h * ACTIVATE_INSET)
        if w > 2:
            ix = max(ix, 1)
        if h > 2:
            iy = max(iy, 1)
        self._commit(QRect(ix, iy, w - 2 * ix, h - 2 * iy), "Crop", None)

    def reset(self) -> None:
        """Remove the crop (``crop=None``) as one undo step."""
        if not self._can_edit() or self._doc.state.crop is None:
            return
        self._try_apply(None, "Reset crop", None)

    # --------------------------------------------------------- QGraphicsItem
    def boundingRect(self) -> QRectF:
        """The whole image (the dimming covers it) plus a margin for the cosmetic border.

        Handles and the label are child items with their own (screen-size) bounds.
        """
        if self._img_w <= 0 or self._img_h <= 0:
            return QRectF()
        m = BOUNDS_MARGIN
        return QRectF(0, 0, self._img_w, self._img_h).adjusted(-m, -m, m, m)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        """Dim outside the crop, thirds while dragging, two-tone 1-px border."""
        if self._rect.isEmpty():
            return
        image = QRectF(0, 0, self._img_w, self._img_h)
        crop = QRectF(self._rect)
        painter.save()
        # Outside = image minus crop; the path subtraction leaves the crop as a hole.
        outside = QPainterPath()
        outside.addRect(image)
        hole = QPainterPath()
        hole.addRect(crop)
        painter.fillPath(outside.subtracted(hole), QBrush(DIM_COLOR))

        if self._drag is not None:
            pen = QPen(QColor(255, 255, 255, 150))
            pen.setCosmetic(True)
            painter.setPen(pen)
            for i in (1, 2):
                x = crop.left() + crop.width() * i / 3
                y = crop.top() + crop.height() * i / 3
                painter.drawLine(QPointF(x, crop.top()), QPointF(x, crop.bottom()))
                painter.drawLine(QPointF(crop.left(), y), QPointF(crop.right(), y))

        # Cosmetic pens are 1 screen pixel wide at any zoom. Black solid underneath and
        # white dashed on top reads on both light and dark images.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        solid = QPen(QColor(0, 0, 0))
        solid.setCosmetic(True)
        painter.setPen(solid)
        painter.drawRect(crop)
        dashed = QPen(QColor(255, 255, 255))
        dashed.setCosmetic(True)
        dashed.setDashPattern([4.0, 4.0])
        painter.setPen(dashed)
        painter.drawRect(crop)
        painter.restore()

    # ------------------------------------------------------------------ mouse
    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """Show the resize/move cursor for the part under the pointer."""
        name = self.handle_at(event.scenePos())
        if name is None:
            self.unsetCursor()
        else:
            self.setCursor(CURSORS[name])

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """Restore the default cursor."""
        self.unsetCursor()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Start a move/resize drag; presses outside the rectangle are ignored."""
        self._press(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Update the live rectangle (no Document write)."""
        self._move(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Commit the drag to the Document as one undo step."""
        self._release(event)

    # Shared by this item and the handle children (which forward their mouse events).
    def _press(self, event: QGraphicsSceneMouseEvent) -> None:
        if (
            event.button() != Qt.MouseButton.LeftButton
            or not self._can_edit()
            or self._drag is not None
        ):
            event.ignore()
            return
        name = self.handle_at(event.scenePos())
        if name is None:
            event.ignore()  # let items below (the pixmap) have it
            return
        self._drag_counter += 1
        self._drag = name
        self._press_pos = QPointF(event.scenePos())
        self._press_rect = QRect(self._rect)
        self._update_label()
        self.update()
        event.accept()

    def _move(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag is None:
            event.ignore()
            return
        delta = event.scenePos() - self._press_pos
        keep = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        new = self._dragged_rect(round(delta.x()), round(delta.y()), keep)
        if new != self._rect:
            self._set_rect(new)
            self.previewChanged.emit(QRectF(new))
        event.accept()

    def _release(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag is None or event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._drag = None
        final = QRect(self._rect)
        if final != self._press_rect:
            self._commit(final, "Crop", f"crop-drag-{self._drag_counter}")
        # Re-read the Document either way: a stateChanged ignored mid-drag (or a no-op
        # apply) must still be reflected, and the label drops the '@ X,Y' part.
        self._sync_from_doc()
        self.update()
        event.accept()

    # ------------------------------------------------------------- geometry
    def _dragged_rect(self, dx: int, dy: int, keep_aspect: bool) -> QRect:
        """The rectangle for a pointer offset of ``(dx, dy)`` image px from the press."""
        r = self._press_rect
        iw, ih = self._img_w, self._img_h
        if self._drag == "move":
            x = _clamp(r.x() + dx, 0, iw - r.width())
            y = _clamp(r.y() + dy, 0, ih - r.height())
            return QRect(x, y, r.width(), r.height())
        name = self._drag or ""
        min_w, min_h = min(MIN_DRAG_SIZE, iw), min(MIN_DRAG_SIZE, ih)
        left, top = r.x(), r.y()
        right, bottom = left + r.width(), top + r.height()  # exclusive edges
        if keep_aspect:
            return self._aspect_rect(name, dx, dy, min_w, min_h)
        if "l" in name:
            left = _clamp(left + dx, 0, right - min_w)
        if "r" in name:
            right = _clamp(right + dx, left + min_w, iw)
        if "t" in name:
            top = _clamp(top + dy, 0, bottom - min_h)
        if "b" in name:
            bottom = _clamp(bottom + dy, top + min_h, ih)
        return QRect(left, top, right - left, bottom - top)

    def _aspect_rect(self, name: str, dx: int, dy: int, min_w: int, min_h: int) -> QRect:
        """Shift-resize: keep the press rectangle's aspect ratio.

        The opposite corner stays fixed. For an edge handle the edge's own axis drives
        the size and the perpendicular axis grows from the top/left edge (also fixed).
        """
        r = self._press_rect
        iw, ih = self._img_w, self._img_h
        aspect = r.width() / r.height()
        left, top = r.x(), r.y()
        right, bottom = left + r.width(), top + r.height()
        # Anchor (fixed) coordinate per axis and the available room from it.
        if "l" in name:
            raw_w, max_w = right - (left + dx), right
        elif "r" in name:
            raw_w, max_w = (right + dx) - left, iw - left
        else:
            raw_w, max_w = r.width(), iw - left
        if "t" in name:
            raw_h, max_h = bottom - (top + dy), bottom
        elif "b" in name:
            raw_h, max_h = (bottom + dy) - top, ih - top
        else:
            raw_h, max_h = r.height(), ih - top
        # Which axis drives: an edge's own axis, or the corner's dominant direction.
        if name in ("l", "r"):
            w = float(raw_w)
            h = w / aspect
        elif name in ("t", "b"):
            h = float(raw_h)
            w = h * aspect
        elif raw_w / aspect >= raw_h:
            w = float(raw_w)
            h = w / aspect
        else:
            h = float(raw_h)
            w = h * aspect
        if w < min_w:
            w, h = float(min_w), min_w / aspect
        if h < min_h:
            h, w = float(min_h), min_h * aspect
        if w > max_w:
            w, h = float(max_w), max_w / aspect
        if h > max_h:
            h, w = float(max_h), max_h * aspect
        # Integer pixels; the final clamp may cost up to 1 px of aspect accuracy.
        wi = _clamp(round(w), min_w, max_w)
        hi = _clamp(round(h), min_h, max_h)
        x = right - wi if "l" in name else left
        y = bottom - hi if "t" in name else top
        return QRect(x, y, wi, hi)

    # ------------------------------------------------------------- internals
    def _view_zoom(self) -> float:
        """Screen px per image px, from the first view's transform (1.0 without a view)."""
        scene = self.scene()
        views = scene.views() if scene is not None else []
        if not views:
            return 1.0
        z = abs(views[0].transform().m11())
        return z if z > 0 else 1.0

    def _can_edit(self) -> bool:
        return self._doc.is_open and self._tool_enabled and self._img_w > 0

    def _doc_rect(self) -> QRect:
        """``doc.state.crop`` as a QRect (the full image when ``None``)."""
        crop = self._doc.state.crop if self._doc.is_open else None
        if crop is None:
            return QRect(0, 0, self._img_w, self._img_h)
        return QRect(crop.x, crop.y, crop.w, crop.h)

    def _commit(self, rect: QRect, text: str, merge_key: str | None) -> None:
        """Apply ``rect`` to the Document; a full-image rectangle is stored as ``None``."""
        if rect == QRect(0, 0, self._img_w, self._img_h):
            crop = None  # "no crop" is canonically None (see crop_panel.md)
        else:
            crop = CropRect(rect.x(), rect.y(), rect.width(), rect.height())
        self._try_apply(crop, text, merge_key)

    def _try_apply(self, crop: CropRect | None, text: str, merge_key: str | None) -> None:
        try:
            self._doc.apply(self._doc.state.with_(crop=crop), text, merge_key=merge_key)
        except ValueError:
            self._sync_from_doc()  # apply is atomic: the Document is unchanged

    def _set_rect(self, rect: QRect) -> None:
        self._rect = QRect(rect)
        r = self._rect
        left, top = float(r.x()), float(r.y())
        right, bottom = left + r.width(), top + r.height()
        cx, cy = (left + right) / 2, (top + bottom) / 2
        positions = {
            "tl": (left, top),
            "t": (cx, top),
            "tr": (right, top),
            "r": (right, cy),
            "br": (right, bottom),
            "b": (cx, bottom),
            "bl": (left, bottom),
            "l": (left, cy),
        }
        for name, (x, y) in positions.items():
            self._handles[name].setPos(x, y)
        self._label.setPos(left, top)
        self._update_label()
        self.update()

    def _update_label(self) -> None:
        r = self._rect
        text = f"{r.width()}{TIMES}{r.height()}"
        if self._drag is not None:
            text += f" @ {r.x()},{r.y()}"
        self._label.set_text(text)

    def _sync_from_doc(self) -> None:
        self._set_rect(self._doc_rect() if self._doc.is_open else QRect())

    def _update_visibility(self) -> None:
        self.setVisible(self._doc.is_open and self._tool_enabled)

    def _update_active(self) -> None:
        active = self.crop_active
        if active != self._active:
            self._active = active
            self.cropActiveChanged.emit(active)

    def _on_source_changed(self) -> None:
        meta = self._doc.meta
        w, h = (meta.width, meta.height) if meta is not None else (0, 0)
        if (w, h) != (self._img_w, self._img_h):
            self.prepareGeometryChange()  # boundingRect depends on the image size
            self._img_w, self._img_h = w, h
        self._drag = None  # a new/closed file cancels any drag
        self._sync_from_doc()
        self._update_visibility()
        self._update_active()

    def _on_state_changed(self, _state: object) -> None:
        self._update_active()
        if self._drag is not None:
            return  # the pointer wins mid-drag; _release re-reads the Document
        self._sync_from_doc()
