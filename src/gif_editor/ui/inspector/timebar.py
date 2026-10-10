"""Custom-painted source timeline with a playhead and green/red trim handles.

``TimeBar`` draws the *source* timeline of the open GIF: the x axis is proportional to
source time in milliseconds (``doc.meta.delays_ms``). It shows a tick per frame
boundary, deleted frames (red hatching), the trim window (everything outside is
shaded), the in (green) and out (red) trim handles, the playhead and time labels.

Interaction:

* press/drag on the track -> seek (``doc.set_current_index``),
* drag a handle -> ``doc.set_trim(..., merge_key="trim-drag-N")`` (one undo step per drag),
  snapping to frame boundaries unless Alt is held,
* keyboard (when focused): Left/Right, Shift+Left/Right (±10), Home/End.

The widget talks only to ``Document``; it never modifies ``EditState`` directly.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QHelpEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QStyle, QStyleOptionFocusRect, QToolTip, QWidget

from gif_editor.core.timeline import frame_at_time, start_times_ms
from gif_editor.ui.document import Document

HEIGHT = 56  # fixed logical height of the widget
MARGIN = 8  # horizontal padding so handles at t=0 / t=total stay grabbable
LABEL_H = 16  # label row at the top
TRACK_TOP = LABEL_H + 2
TRACK_BOTTOM_PAD = 6
HANDLE_HIT = 4  # half-width of a handle's hit area (=> 8 px total)
MIN_TICK_GAP = 3.0  # thin out frame ticks closer than this (px)
MIN_LABEL_GAP = 60.0  # labels at least this far apart (px)
MIN_WINDOW_MS = 10  # smallest allowed trim window
# "Nice" label intervals in ms; the first one giving >= MIN_LABEL_GAP px is used.
NICE_STEPS_MS = (100, 200, 500, 1000, 2000, 5000, 10_000, 20_000, 50_000, 100_000, 300_000)

IN_COLOR = QColor(46, 160, 67)
OUT_COLOR = QColor(218, 54, 51)
DELETED_COLOR = QColor(218, 54, 51, 200)
SHADE_COLOR = QColor(0, 0, 0, 110)


def format_seconds(ms: float) -> str:
    """Format a time in ms as seconds, e.g. ``1500 -> '1.5 s'``, ``0 -> '0 s'``."""
    return f"{round(ms / 1000, 3):g} s"


class TimeBar(QWidget):
    """Horizontal source timeline: frame ticks, trim window, handles and playhead.

    Construct with the shared :class:`Document`. All edits go through the document,
    and the widget repaints on ``sourceChanged``, ``stateChanged`` and
    ``currentIndexChanged``.
    """

    scrubbed = Signal(int)  # source frame index, emitted while dragging the playhead

    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._delays: tuple[int, ...] = ()
        self._starts: list[int] = []
        self._bounds: list[int] = []  # frame starts + total (every snappable time)
        self._total = 0
        self._drag: str | None = None  # None | "seek" | "in" | "out"
        self._drag_counter = 0  # incremented on each press -> unique merge key per drag
        self._merge_key = ""

        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)  # hover cursor without a pressed button
        self.setAccessibleName("Timeline")

        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._on_changed)
        doc.currentIndexChanged.connect(self._on_changed)
        self._on_source_changed()

    # ------------------------------------------------------------------ sizing
    def sizeHint(self) -> QSize:
        """Preferred size: 400 x 56 logical px (width expands in layouts)."""
        return QSize(400, HEIGHT)

    def minimumSizeHint(self) -> QSize:
        """Smallest usable size: 50 x 56 logical px."""
        return QSize(50, HEIGHT)

    # ----------------------------------------------------------------- mapping
    def _track_width(self) -> float:
        return max(1.0, float(self.width() - 2 * MARGIN))

    def x_for_time(self, ms: float) -> float:
        """Widget x coordinate (logical px) of source time ``ms``."""
        if self._total <= 0:
            return float(MARGIN)
        return MARGIN + ms / self._total * self._track_width()

    def time_for_x(self, x: float) -> float:
        """Source time (ms) at widget x coordinate ``x``, clamped to ``[0, total]``."""
        if self._total <= 0:
            return 0.0
        t = (x - MARGIN) / self._track_width() * self._total
        return min(max(t, 0.0), float(self._total))

    def _window(self) -> tuple[int, int]:
        """Trim window ``(in_ms, out_ms)`` clamped to the source duration."""
        st = self._doc.state
        start = min(st.trim_start_ms, self._total)
        if st.trim_duration_ms is None:
            end = self._total
        else:
            end = min(self._total, st.trim_start_ms + st.trim_duration_ms)
        return start, max(start, end)

    def handle_at(self, pos: QPoint | QPointF) -> str | None:
        """Return ``'in'``, ``'out'`` or ``None`` for the handle under ``pos``.

        If both hit areas overlap (a tiny window), the nearer handle wins; on a tie the
        side of the cursor decides (left -> in, right -> out).
        """
        if not self._doc.is_open or self._total <= 0:
            return None
        x = pos.x()
        tin, tout = self._window()
        xin, xout = self.x_for_time(tin), self.x_for_time(tout)
        din, dout = abs(x - xin), abs(x - xout)
        hit_in, hit_out = din <= HANDLE_HIT, dout <= HANDLE_HIT
        if hit_in and hit_out:
            if din != dout:
                return "in" if din < dout else "out"
            return "in" if x <= (xin + xout) / 2 and xin < xout else "out"
        if hit_in:
            return "in"
        if hit_out:
            return "out"
        return None

    # ---------------------------------------------------------- doc reactions
    def _on_source_changed(self) -> None:
        meta = self._doc.meta
        self._delays = tuple(meta.delays_ms) if meta is not None else ()
        self._starts = start_times_ms(self._delays)
        self._total = sum(self._delays)
        self._bounds = [*self._starts, self._total] if self._delays else []
        self._drag = None
        self.setEnabled(self._doc.is_open)
        self._on_changed()

    def _on_changed(self, *_args: object) -> None:
        self._update_description()
        self.update()

    def _update_description(self) -> None:
        if not self._doc.is_open or not self._delays:
            self.setAccessibleDescription("No GIF loaded")
            return
        i = self._doc.current_index
        tin, tout = self._window()
        end = " (end)" if self._doc.state.trim_duration_ms is None else ""
        self.setAccessibleDescription(
            f"Frame {i + 1} of {len(self._delays)} at {format_seconds(self._starts[i])}; "
            f"trim {format_seconds(tin)} to {format_seconds(tout)}{end}"
        )

    # ------------------------------------------------------------------ snapping
    def _snap(self, t: float, lo: float, hi: float, free: bool) -> int:
        """Clamp ``t`` to ``[lo, hi]``; unless ``free``, snap to the nearest boundary inside."""
        t = min(max(t, lo), hi)
        if not free and self._bounds:
            i = bisect_left(self._bounds, lo)
            j = bisect_left(self._bounds, hi + 1e-9)  # boundaries <= hi
            cands = self._bounds[i:j]
            if cands:
                return min(cands, key=lambda b: (abs(b - t), b))
        return round(t)

    def _drag_handle(self, x: float, free: bool) -> None:
        tin, tout = self._window()
        t = self.time_for_x(x)
        total = self._total
        dur_none = self._doc.state.trim_duration_ms is None
        if self._drag == "in":
            new_in = self._snap(t, 0, max(0, tout - MIN_WINDOW_MS), free)
            duration = None if dur_none else tout - new_in
            self._doc.set_trim(new_in, duration, merge_key=self._merge_key)
        else:
            new_out = self._snap(t, min(total, tin + MIN_WINDOW_MS), total, free)
            duration = None if new_out >= total else new_out - tin
            self._doc.set_trim(tin, duration, merge_key=self._merge_key)

    def _seek(self, x: float) -> None:
        i = frame_at_time(self._delays, self.time_for_x(x))
        self._doc.set_current_index(i)
        self.scrubbed.emit(i)

    # --------------------------------------------------------------------- mouse
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a seek (track) or a trim drag (handle); each press gets a new merge key."""
        if not self._doc.is_open or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_counter += 1
        self._merge_key = f"trim-drag-{self._drag_counter}"
        pos = event.position()
        handle = self.handle_at(pos)
        if handle is not None:
            self._drag = handle
        else:
            self._drag = "seek"
            self._seek(pos.x())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Continue the current drag, or update the hover cursor."""
        pos = event.position()
        if self._drag == "seek":
            self._seek(pos.x())
        elif self._drag in ("in", "out"):
            free = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._drag_handle(pos.x(), free)
        else:
            self._update_cursor(pos)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish the drag.

        The release position is deliberately NOT re-applied: users often let go of Alt
        a moment before the button, which would otherwise re-snap a free (Alt) drag.
        """
        if self._drag is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self._update_cursor(event.position())
        event.accept()

    def _update_cursor(self, pos: QPointF) -> None:
        if not self._doc.is_open:
            self.unsetCursor()
        elif self.handle_at(pos) is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def tooltip_text(self, x: float) -> str:
        """Hover tooltip for widget x: time and (1-based) frame number at that point."""
        if not self._delays:
            return ""
        t = self.time_for_x(x)
        i = frame_at_time(self._delays, t)
        return f"{format_seconds(t)} · frame {i + 1} of {len(self._delays)}"

    def event(self, event: QEvent) -> bool:
        """Show the time/frame tooltip on ``QEvent.ToolTip``."""
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            text = self.tooltip_text(event.pos().x()) if self._doc.is_open else ""
            if text:
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    # ------------------------------------------------------------------ keyboard
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Left/Right step one frame (Shift: 10), Home/End jump to first/last frame."""
        if not self._doc.is_open:
            super().keyPressEvent(event)
            return
        key = event.key()
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        cur = self._doc.current_index
        if key == Qt.Key.Key_Left:
            self._doc.set_current_index(cur - step)
        elif key == Qt.Key.Key_Right:
            self._doc.set_current_index(cur + step)
        elif key == Qt.Key.Key_Home:
            self._doc.set_current_index(0)
        elif key == Qt.Key.Key_End:
            self._doc.set_current_index(len(self._delays) - 1)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # --------------------------------------------------------------------- paint
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw track, frame ticks, deleted frames, shading, labels, handles, playhead."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pal = self.palette()
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        base = pal.color(group, QPalette.ColorRole.Base)
        mid = pal.color(group, QPalette.ColorRole.Mid)
        text = pal.color(group, QPalette.ColorRole.WindowText)
        hi = pal.color(group, QPalette.ColorRole.Highlight)

        top, bottom = TRACK_TOP, self.height() - TRACK_BOTTOM_PAD
        left, right = float(MARGIN), float(self.width() - MARGIN)
        track = QRectF(left, top, max(1.0, right - left), bottom - top)
        p.fillRect(track, base)
        p.setPen(_pen(mid))
        p.drawRect(track)

        if not self._doc.is_open or self._total <= 0:
            p.setPen(_pen(text))
            p.drawText(track, Qt.AlignmentFlag.AlignCenter, "No GIF loaded")
            self._paint_focus(p)
            p.end()
            return

        self._paint_frames(p, track, mid)
        self._paint_deleted(p, track)
        self._paint_labels(p, track, text, mid)

        # Shade outside the trim window.
        tin, tout = self._window()
        xin, xout = self.x_for_time(tin), self.x_for_time(tout)
        if xin > left:
            p.fillRect(QRectF(left, top, xin - left, track.height()), SHADE_COLOR)
        if xout < right:
            p.fillRect(QRectF(xout, top, right - xout, track.height()), SHADE_COLOR)

        # Playhead at the current frame's start time.
        i = min(self._doc.current_index, len(self._starts) - 1)
        xp = self.x_for_time(self._starts[i])
        p.setPen(_pen(hi, 2))
        p.drawLine(QPointF(xp, top), QPointF(xp, bottom))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(hi)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPolygon(
            QPolygonF([QPointF(xp - 5, top - 6), QPointF(xp + 5, top - 6), QPointF(xp, top)])
        )

        self._paint_handle(p, xin, top, bottom, IN_COLOR, inward=1)
        self._paint_handle(p, xout, top, bottom, OUT_COLOR, inward=-1)
        self._paint_focus(p)
        p.end()

    def _paint_frames(self, p: QPainter, track: QRectF, mid: QColor) -> None:
        """Alternate faint segment fills (when wide enough) and thinned boundary ticks."""
        n = len(self._starts)
        avg_px = track.width() / n
        if avg_px >= MIN_TICK_GAP * 2:
            alt = QColor(mid)
            alt.setAlpha(40)
            for k in range(1, n, 2):
                x0 = self.x_for_time(self._starts[k])
                x1 = self.x_for_time(self._bounds[k + 1])
                p.fillRect(QRectF(x0, track.top(), x1 - x0, track.height()), alt)
        p.setPen(_pen(mid))
        last = -1e9
        tick_top = track.bottom() - track.height() * 0.35
        lines = []
        for t in self._starts[1:]:
            x = self.x_for_time(t)
            if x - last >= MIN_TICK_GAP:
                lines.append((x, tick_top))
                last = x
        for x, y in lines:
            p.drawLine(QPointF(x, y), QPointF(x, track.bottom()))

    def _paint_deleted(self, p: QPainter, track: QRectF) -> None:
        """Hatched red over deleted frames; consecutive runs are merged into one rect."""
        deleted = self._doc.state.deleted
        if not deleted:
            return
        brush = QBrush(DELETED_COLOR, Qt.BrushStyle.BDiagPattern)
        n = len(self._delays)
        for a, b in _runs(sorted(i for i in deleted if 0 <= i < n)):
            x0 = self.x_for_time(self._starts[a])
            x1 = self.x_for_time(self._bounds[b + 1])
            rect = QRectF(x0, track.top(), max(1.0, x1 - x0), track.height())
            tint = QColor(DELETED_COLOR)
            tint.setAlpha(45)
            p.fillRect(rect, tint)
            p.fillRect(rect, brush)

    def _paint_labels(self, p: QPainter, track: QRectF, text: QColor, mid: QColor) -> None:
        """Time labels at a 'nice' interval so they are >= MIN_LABEL_GAP px apart."""
        px_per_ms = track.width() / self._total
        step = next((s for s in NICE_STEPS_MS if s * px_per_ms >= MIN_LABEL_GAP), NICE_STEPS_MS[-1])
        fm = self.fontMetrics()
        t = 0
        while t <= self._total:
            x = self.x_for_time(t)
            label = format_seconds(t)
            if x + 2 + fm.horizontalAdvance(label) <= self.width():
                p.setPen(_pen(mid))
                p.drawLine(QPointF(x, track.top() - 4), QPointF(x, track.top()))
                p.setPen(_pen(text))
                p.drawText(QPointF(x + 2, LABEL_H - 3), label)
            t += step

    def _paint_handle(
        self, p: QPainter, x: float, top: float, bottom: float, color: QColor, inward: int
    ) -> None:
        """A vertical bar with a small grip flag pointing into the trim window."""
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(QRectF(x - 1.5, top, 3, bottom - top), color)
        grip = QRectF(x if inward > 0 else x - 7, top, 7, 10)
        p.fillRect(grip, color)
        p.setPen(_pen(QColor(255, 255, 255, 180)))
        gx = grip.center().x()
        p.drawLine(QPointF(gx, top + 3), QPointF(gx, top + 7))

    def _paint_focus(self, p: QPainter) -> None:
        if not self.hasFocus():
            return
        opt = QStyleOptionFocusRect()
        opt.initFrom(self)
        opt.rect = self.rect().adjusted(1, 1, -1, -1)
        opt.backgroundColor = self.palette().color(QPalette.ColorRole.Window)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, opt, p, self)


def _pen(color: QColor, width: float = 1) -> QPen:
    """A cosmetic pen (width in device-independent px, unaffected by transforms)."""
    pen = QPen(color, width)
    pen.setCosmetic(True)
    return pen


def _runs(indices: Sequence[int]) -> list[tuple[int, int]]:
    """Group sorted indices into inclusive ``(first, last)`` runs of consecutive values."""
    runs: list[tuple[int, int]] = []
    for i in indices:
        if runs and i == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs
