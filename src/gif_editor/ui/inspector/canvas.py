"""Zoomable, pannable viewer for the current source frame.

``FrameCanvas`` is a ``QGraphicsView`` whose scene uses *source image pixels* as its
coordinate system: scene point (x, y) is pixel (x, y) of the GIF canvas. The frame is a
``QGraphicsPixmapItem`` at (0, 0); zooming only changes the view transform, so anything
added to the scene later (the M3 crop rectangle) can work in plain image pixels.

The canvas is display-only: it reads ``Document`` and never edits it. Drag-and-drop of
files is handled by the main window, so the canvas refuses drops and lets them bubble up.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QResizeEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from gif_editor.ui.document import Document
from gif_editor.ui.qt_image import checkerboard_brush, pil_to_qimage

MIN_ZOOM = 0.05
MAX_ZOOM = 32.0
ZOOM_STEP = 1.25
FIT_MARGIN = 16  # logical px kept free around the image in fit mode
PLACEHOLDER_TEXT = "Open a GIF (Ctrl+O) or drop it here"
DELETED_TINT = QColor(220, 30, 30, 90)


class FrameCanvas(QGraphicsView):
    """Shows ``doc.source.frame(doc.current_index)`` with zoom, pan and a deleted overlay.

    Scene coordinates == source image pixels. Zoom is a uniform scale on the view
    transform (``zoom`` == screen logical px per image px).
    """

    zoomChanged = Signal(float)

    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        """Create the canvas bound to ``doc`` and show the current frame (if any)."""
        super().__init__(parent)
        self._doc = doc
        self._zoom = 1.0
        self._fit_mode = True
        self._space_held = False
        self._middle_panning = False
        self._checker = checkerboard_brush()

        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._item.setPos(0, 0)
        # Pixel edges must line up with scene integers; the default ShapeMode is fine.
        self._scene.addItem(self._item)
        self.setScene(self._scene)

        self.setAccessibleName("Frame canvas")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # The checkerboard is painted in viewport coordinates, so scroll-blitting would
        # misalign it; repaint the whole viewport instead (cheap: one pixmap blit).
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Display only: file drops are handled by the main window. QGraphicsView accepts
        # drops on its viewport by default, which would swallow them.
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)

        doc.sourceChanged.connect(self._on_source_changed)
        doc.currentIndexChanged.connect(self._on_current_changed)
        doc.stateChanged.connect(self._on_state_changed)
        self._on_source_changed()

    # ------------------------------------------------------------- public API
    @property
    def image_item(self) -> QGraphicsPixmapItem:
        """The pixmap item showing the current frame (parent for M3 overlays)."""
        return self._item

    @property
    def zoom(self) -> float:
        """Current zoom factor (1.0 = one image pixel per logical screen pixel)."""
        return self._zoom

    @property
    def fit_mode(self) -> bool:
        """True after ``zoom_fit()`` (re-fits on resize); False after a manual zoom."""
        return self._fit_mode

    @property
    def placeholder_visible(self) -> bool:
        """True when no GIF is open and the placeholder text is drawn."""
        return not self._doc.is_open

    @property
    def deleted_overlay_visible(self) -> bool:
        """True when the current frame is deleted and the red overlay is drawn."""
        return self._doc.is_open and self._doc.current_index in self._doc.state.deleted

    def image_rect(self) -> QRectF:
        """Image bounds in scene (= image pixel) coordinates; empty if nothing is open."""
        meta = self._doc.meta
        if meta is None:
            return QRectF()
        return QRectF(0, 0, meta.width, meta.height)

    def map_to_image(self, view_pos: QPoint | QPointF) -> QPointF:
        """Map a viewport position (logical px) to image pixel coordinates (may be outside)."""
        inv, _ok = self.viewportTransform().inverted()
        return inv.map(QPointF(view_pos))

    def set_zoom(self, factor: float) -> None:
        """Set the zoom (clamped to 0.05 to 32) and leave fit mode."""
        self._fit_mode = False
        self._apply_zoom(factor)

    def zoom_in(self) -> None:
        """Zoom in one step (times 1.25)."""
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        """Zoom out one step (divide by 1.25)."""
        self.set_zoom(self._zoom / ZOOM_STEP)

    def zoom_actual(self) -> None:
        """Show the image at 100% (one image pixel per logical pixel)."""
        self.set_zoom(1.0)

    def zoom_fit(self) -> None:
        """Fit the whole image into the viewport with a margin and enter fit mode."""
        self._fit_mode = True
        rect = self.image_rect()
        vp = self.viewport().size()
        avail_w = vp.width() - 2 * FIT_MARGIN
        avail_h = vp.height() - 2 * FIT_MARGIN
        if rect.isEmpty() or avail_w <= 0 or avail_h <= 0:
            return  # not laid out yet; resizeEvent will fit again
        self._apply_zoom(min(avail_w / rect.width(), avail_h / rect.height()))
        self.centerOn(rect.center())

    # -------------------------------------------------------------- internals
    def _apply_zoom(self, factor: float) -> None:
        factor = max(MIN_ZOOM, min(MAX_ZOOM, float(factor)))
        # setTransform honours transformationAnchor (view centre or mouse position).
        self.setTransform(QTransform.fromScale(factor, factor))
        self._update_transformation_mode(factor)
        if factor != self._zoom:
            self._zoom = factor
            self.zoomChanged.emit(factor)

    def _update_transformation_mode(self, factor: float) -> None:
        # Downscaling needs filtering to avoid aliasing; upscaling must stay crisp so
        # individual pixels are visible (important for pixel-art GIFs and cropping).
        mode = (
            Qt.TransformationMode.SmoothTransformation
            if factor < 1.0
            else Qt.TransformationMode.FastTransformation
        )
        self._item.setTransformationMode(mode)

    def _on_source_changed(self) -> None:
        self._update_pixmap()
        rect = self.image_rect()
        # A non-null rect stops QGraphicsScene from growing its rect automatically.
        self._scene.setSceneRect(rect if not rect.isEmpty() else QRectF(0, 0, 1, 1))
        if self._doc.is_open:
            self.zoom_fit()
        else:
            self._fit_mode = True
            self._apply_zoom(1.0)
        self.viewport().update()

    def _on_current_changed(self, _index: int) -> None:
        self._update_pixmap()
        self.viewport().update()

    def _on_state_changed(self, _state: object) -> None:
        self.viewport().update()  # deleted overlay may have changed

    def _update_pixmap(self) -> None:
        source = self._doc.source
        if source is None:
            self._item.setPixmap(QPixmap())
            return
        index = self._doc.current_index
        if not 0 <= index < source.meta.frame_count:
            self._item.setPixmap(QPixmap())
            return
        # Synchronous on purpose: GifSource caches composited frames, so this is a
        # dictionary lookup + one RGBA conversion for typical GIFs. (M3/M4 may move
        # large-frame decoding off-thread.)
        img = source.frame(index)
        self._item.setPixmap(QPixmap.fromImage(pil_to_qimage(img)))

    # --------------------------------------------------------------- painting
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        """Dark neutral fill outside the image, checkerboard behind the image."""
        painter.save()
        painter.resetTransform()  # paint in viewport (logical pixel) coordinates
        bg = self.palette().color(QPalette.ColorRole.Window).darker(150)
        painter.fillRect(self.viewport().rect(), bg)
        img = self.image_rect()
        if not img.isEmpty():
            # Checker cells stay a constant on-screen size regardless of zoom.
            device = self.viewportTransform().mapRect(img)
            painter.setBrushOrigin(device.topLeft())
            painter.fillRect(device, self._checker)
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """Placeholder text when empty; red tint + 'Deleted' badge on deleted frames."""
        if self.placeholder_visible:
            painter.save()
            painter.resetTransform()
            painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                self.viewport().rect(),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                PLACEHOLDER_TEXT,
            )
            painter.restore()
            return
        if not self.deleted_overlay_visible:
            return
        painter.save()
        painter.resetTransform()
        device = self.viewportTransform().mapRect(self.image_rect())
        painter.fillRect(device, DELETED_TINT)
        # Badge in the top-left corner of the visible part of the image.
        visible = device.intersected(QRectF(self.viewport().rect()))
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text = "Deleted"
        pad = 6
        badge = QRectF(
            visible.left() + 8,
            visible.top() + 8,
            fm.horizontalAdvance(text) + 2 * pad,
            fm.height() + pad,
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(255, 255, 255, 200))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(190, 20, 20, 230))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()

    # ------------------------------------------------------------------ input
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-fit while in fit mode so the image tracks the panel size."""
        super().resizeEvent(event)
        if self._fit_mode and self._doc.is_open:
            self.zoom_fit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl+wheel zooms around the mouse; a plain wheel scrolls."""
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y() / 120.0  # 120 units = one notch
        if steps == 0 or not self._doc.is_open:
            event.accept()
            return
        old_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.set_zoom(self._zoom * ZOOM_STEP**steps)
        self.setTransformationAnchor(old_anchor)
        event.accept()

    def _begin_pan(self) -> None:
        # Non-interactive: scene items (future crop handles) must not see pan drags.
        self.setInteractive(False)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def _end_pan(self) -> None:
        if self._space_held or self._middle_panning:
            return
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setInteractive(True)

    @staticmethod
    def _as_left(event: QMouseEvent, kind: QEvent.Type) -> QMouseEvent:
        # ScrollHandDrag only reacts to the left button, so re-issue middle as left.
        buttons = (
            Qt.MouseButton.LeftButton
            if kind != QEvent.Type.MouseButtonRelease
            else (Qt.MouseButton.NoButton)
        )
        return QMouseEvent(
            kind,
            event.position(),
            event.globalPosition(),
            Qt.MouseButton.LeftButton,
            buttons,
            event.modifiers(),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Middle button starts a hand-drag pan."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_panning = True
            self._begin_pan()
            super().mousePressEvent(self._as_left(event, QEvent.Type.MouseButtonPress))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Forward moves; during a middle pan they are re-issued as left-button moves."""
        if self._middle_panning:
            super().mouseMoveEvent(self._as_left(event, QEvent.Type.MouseMove))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Middle release ends the pan."""
        if event.button() == Qt.MouseButton.MiddleButton and self._middle_panning:
            super().mouseReleaseEvent(self._as_left(event, QEvent.Type.MouseButtonRelease))
            self._middle_panning = False
            self._end_pan()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Holding Space turns left-drag into panning."""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self._begin_pan()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            event.accept()  # swallow auto-repeat while held
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Releasing Space ends Space+drag panning."""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self._end_pan()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        """Losing focus while Space is held would otherwise leave pan mode stuck."""
        if self._space_held:
            self._space_held = False
            self._end_pan()
        super().focusOutEvent(event)
