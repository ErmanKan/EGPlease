"""Horizontal thumbnail strip of every SOURCE frame (bottom of the inspector).

Three cooperating classes:

* ``FrameListModel``: a Qt list model with one row per source frame. It serves the
  label, tooltip, thumbnail and two custom roles (``DeletedRole``, ``InTrimRole``).
  Thumbnails are decoded lazily, in batches, on a worker thread.
* ``FrameDelegate``: paints one cell (thumbnail, label, deleted strike, trim dimming,
  current-frame border).
* ``Filmstrip``: the ``QListView`` that wires the model to the ``Document``: selection,
  current frame, Delete/Restore keys and the context menu.

Like every widget, it talks only to ``Document``; it never knows about other widgets.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QIcon,
    QKeyEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)
from shiboken6 import isValid

from gif_editor.core.timeline import start_times_ms
from gif_editor.ui.document import Document
from gif_editor.ui.qt_image import pil_to_qimage
from gif_editor.ui.workers import run_async

THUMB_MAX_SIDE = 96  # pixels requested from GifSource.thumbnail (headroom for HiDPI)
BATCH_SIZE = 32  # thumbnails decoded per worker job
PREFETCH_MARGIN = 16  # rows beyond the visible range that are loaded too
ICON_BOX = QSize(80, 80)  # logical size the thumbnail is fitted into when painted
CELL_WIDTH = 92
PLACEHOLDER_COLOR = QColor(128, 128, 128)

_Index = QModelIndex | QPersistentModelIndex


class FrameListModel(QAbstractListModel):
    """List model with one row per source frame of ``doc``.

    Roles: ``DisplayRole`` ('#3\\n100 ms'), ``DecorationRole`` (thumbnail ``QPixmap`` or a
    grey placeholder), ``ToolTipRole``, ``DeletedRole`` (bool) and ``InTrimRole`` (bool).
    """

    DeletedRole = Qt.ItemDataRole.UserRole + 1
    InTrimRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._generation = 0  # bumped on every sourceChanged; stale results are dropped
        self._cache: dict[int, QPixmap] = {}  # row -> thumbnail (GUI thread only)
        self._failed: set[int] = set()  # rows whose thumbnail could not be decoded
        self._loading: set[int] = set()  # rows in the batch currently on a worker
        self._requested: set[int] = set()  # rows asked for by data() but not loaded yet
        self._visible: tuple[int, int] | None = None  # (first, last) reported by the view
        self._busy = False  # one batch in flight at a time keeps priorities fresh
        self._placeholder: QPixmap | None = None
        self._starts: list[int] = []  # source start time of every frame (ms)
        self._rows = 0
        # Coalesce many data() calls during one paint into a single scheduling pass.
        self._kick = QTimer(self)
        self._kick.setSingleShot(True)
        self._kick.setInterval(0)
        self._kick.timeout.connect(self._schedule)
        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._on_state_changed)
        self._reload_meta()

    # ------------------------------------------------------------ Qt model API
    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        """Number of source frames (0 when nothing is open)."""
        return 0 if parent.isValid() else self._rows

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        """Return the value for ``role`` at ``index`` (see class docstring)."""
        meta = self._doc.meta
        if meta is None or not index.isValid() or not 0 <= index.row() < self._rows:
            return None
        row = index.row()
        delay = meta.frames[row].effective_delay_ms
        if role == Qt.ItemDataRole.DisplayRole:
            return f"#{row + 1}\n{delay} ms"
        if role == Qt.ItemDataRole.DecorationRole:
            pm = self._cache.get(row)
            if pm is not None:
                return pm
            if row not in self._failed and row not in self._loading:
                self._requested.add(row)
                self._kick.start()
            return self.placeholder()
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = f"Frame {row + 1} · starts {self._starts[row] / 1000:.2f} s · delay {delay} ms"
            if row in self._doc.state.deleted:
                tip += " · deleted"
            if not self.in_trim(row):
                tip += " · outside trim"
            return tip
        if role == self.DeletedRole:
            return row in self._doc.state.deleted
        if role == self.InTrimRole:
            return self.in_trim(row)
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        """Selectable and enabled, never editable or draggable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # -------------------------------------------------------------- helpers
    @property
    def generation(self) -> int:
        """Counter bumped on every ``sourceChanged``; thumbnail jobs carry it."""
        return self._generation

    @property
    def is_loading(self) -> bool:
        """True while a thumbnail batch is running on a worker thread."""
        return self._busy

    def has_thumbnail(self, row: int) -> bool:
        """True once the real thumbnail of ``row`` is cached."""
        return row in self._cache

    def in_trim(self, row: int) -> bool:
        """True if frame ``row`` is visible somewhere inside the trim window."""
        meta = self._doc.meta
        if meta is None or not 0 <= row < self._rows:
            return False
        st = self._doc.state
        total = meta.total_duration_ms
        start = st.trim_start_ms
        end = total if st.trim_duration_ms is None else min(total, start + st.trim_duration_ms)
        f_start = self._starts[row]
        f_end = f_start + meta.frames[row].effective_delay_ms
        # Same overlap rule as timeline._trim: any visible time inside [start, end).
        return max(f_start, start) < min(f_end, end)

    def frame_start_ms(self, row: int) -> int:
        """Source start time of frame ``row`` (ms)."""
        return self._starts[row]

    def placeholder(self) -> QPixmap:
        """Grey pixmap with the thumbnail's aspect ratio, shown until it loads."""
        if self._placeholder is None:
            meta = self._doc.meta
            w, h = (meta.width, meta.height) if meta is not None else (4, 3)
            scale = min(1.0, THUMB_MAX_SIDE / max(w, h))
            pm = QPixmap(max(1, round(w * scale)), max(1, round(h * scale)))
            pm.fill(PLACEHOLDER_COLOR)
            self._placeholder = pm
        return self._placeholder

    def set_visible_rows(self, first: int, last: int) -> None:
        """Called by the view: rows ``first..last`` are on screen; load those first."""
        if self._rows == 0:
            self._visible = None
            return
        first = max(0, min(first, self._rows - 1))
        last = max(first, min(last, self._rows - 1))
        if self._visible != (first, last):
            self._visible = (first, last)
            self._kick.start()

    # ---------------------------------------------------------- thumbnails
    def _candidates(self) -> list[int]:
        """Rows that still need a thumbnail, nearest to the visible range first."""
        done = self._cache.keys() | self._failed | self._loading
        want = set(self._requested)
        if self._visible is not None:
            first, last = self._visible
            lo = max(0, first - PREFETCH_MARGIN)
            hi = min(self._rows - 1, last + PREFETCH_MARGIN)
            want.update(range(lo, hi + 1))
            # Forget requests for rows the user has scrolled far away from.
            far = 4 * PREFETCH_MARGIN
            want = {r for r in want if first - far <= r <= last + far}
            centre = (first + last) / 2
        else:
            centre = 0.0
        self._requested = want - done
        return sorted(self._requested, key=lambda r: (abs(r - centre), r))

    def _schedule(self) -> None:
        """Start one batch of up to ``BATCH_SIZE`` thumbnails if none is running."""
        source = self._doc.source
        if self._busy or source is None:
            return
        rows = self._candidates()[:BATCH_SIZE]
        if not rows:
            return
        self._busy = True
        self._loading = set(rows)
        self._requested -= self._loading
        gen = self._generation

        def work() -> list[tuple[int, object]]:
            # Runs on a pool thread: PIL decode + QImage conversion only (no QPixmap).
            out: list[tuple[int, object]] = []
            for r in rows:
                try:
                    out.append((r, pil_to_qimage(source.thumbnail(r, THUMB_MAX_SIDE))))
                except Exception:  # corrupt frame or closed source: keep the placeholder
                    out.append((r, None))
            return out

        def done(results: list[tuple[int, object]]) -> None:
            if isValid(self):  # the C++ model may have been deleted meanwhile
                self.on_thumbnails_loaded(gen, results)

        def failed(_msg: str, _exc: BaseException) -> None:
            if isValid(self):
                self.on_thumbnails_loaded(gen, [(r, None) for r in rows])

        run_async(work, on_done=done, on_error=failed)

    def on_thumbnails_loaded(self, generation: int, results: Iterable[tuple[int, object]]) -> None:
        """GUI-thread callback for a finished batch: ``results`` is ``[(row, QImage|None)]``.

        Results whose ``generation`` is older than the current one belong to a file that
        is no longer open and are ignored.
        """
        if generation != self._generation:
            return  # stale: a sourceChanged happened while the worker ran
        results = list(results)
        # Only the rows this result covers stop being "in flight"; the batch is over
        # once none are left (robust against extra/manual deliveries).
        self._loading.difference_update(r for r, _ in results)
        self._busy = bool(self._loading)
        rows: list[int] = []
        for row, img in results:
            if not 0 <= row < self._rows:
                continue
            if img is None:
                self._failed.add(row)
                continue
            self._cache[row] = QPixmap.fromImage(img)  # QPixmap: GUI thread only
            rows.append(row)
        for row in rows:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
        self._kick.start()  # continue with the next batch, if any rows are still wanted

    # -------------------------------------------------------- doc signals
    def _reload_meta(self) -> None:
        meta = self._doc.meta
        self._rows = meta.frame_count if meta is not None else 0
        self._starts = start_times_ms(meta.delays_ms) if meta is not None else []

    def _on_source_changed(self) -> None:
        self.beginResetModel()
        self._generation += 1
        self._cache.clear()
        self._failed.clear()
        self._loading.clear()
        self._requested.clear()
        self._visible = None
        self._busy = False
        self._placeholder = None
        self._reload_meta()
        self.endResetModel()

    def _on_state_changed(self, _state: object) -> None:
        # Deleted/trim flags may have changed for any row; this is cheap (no decoding).
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(self._rows - 1))


class FrameDelegate(QStyledItemDelegate):
    """Paints one filmstrip cell: thumbnail, '#N / delay' label and status overlays."""

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        """Fixed cell size: icon box plus two lines of text."""
        line = option.fontMetrics.height()
        return QSize(CELL_WIDTH, ICON_BOX.height() + 2 * line + 12)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        """Draw the cell. All geometry is in logical pixels; pens are cosmetic."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        view = option.widget
        style = view.style() if view is not None else None
        # Selection/hover background from the active style (Fusion).
        opt = QStyleOptionViewItem(option)
        opt.text = ""
        opt.icon = QIcon()  # no icon; we draw the pixmap ourselves
        if style is not None:
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, view)

        deleted = bool(index.data(FrameListModel.DeletedRole))
        in_trim = bool(index.data(FrameListModel.InTrimRole))
        rect = option.rect
        icon_rect = QRect(
            rect.x() + (rect.width() - ICON_BOX.width()) // 2,
            rect.y() + 4,
            ICON_BOX.width(),
            ICON_BOX.height(),
        )
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        target = icon_rect
        if isinstance(pm, QPixmap) and not pm.isNull():
            size = pm.size().scaled(ICON_BOX, Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(
                icon_rect.x() + (icon_rect.width() - size.width()) // 2,
                icon_rect.y() + (icon_rect.height() - size.height()) // 2,
                size.width(),
                size.height(),
            )
            painter.setOpacity(0.3 if deleted else (0.4 if not in_trim else 1.0))
            painter.drawPixmap(target, pm)
            painter.setOpacity(1.0)
        if deleted:
            # Grey wash + red diagonal strike so "deleted" reads even in greyscale.
            painter.fillRect(target, QColor(128, 128, 128, 110))
            pen = QPen(QColor(220, 30, 30), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(target.bottomLeft(), target.topRight())

        text_rect = QRect(
            rect.x(), icon_rect.bottom() + 3, rect.width(), rect.bottom() - icon_rect.bottom() - 3
        )
        text_color = option.palette.color(
            option.palette.ColorRole.HighlightedText
            if option.state & QStyle.StateFlag.State_Selected
            else option.palette.ColorRole.Text
        )
        if deleted or not in_trim:
            text_color.setAlpha(140)
        painter.setPen(text_color)
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, str(index.data())
        )

        if deleted:
            small = QFont(option.font)
            small.setPointSizeF(max(6.0, option.font.pointSizeF() * 0.8))
            painter.setFont(small)
            painter.setPen(QColor(220, 30, 30))
            painter.drawText(target, Qt.AlignmentFlag.AlignCenter, "deleted")

        current = getattr(view, "currentIndex", None)
        if current is not None and current().row() == index.row():
            pen = QPen(option.palette.color(option.palette.ColorRole.Highlight), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
        painter.restore()


class Filmstrip(QListView):
    """Single-row horizontal strip of frame thumbnails bound to a ``Document``.

    Selection is mirrored into ``doc.selection``; the current item is kept in sync with
    ``doc.current_index`` in both directions. Delete/Backspace deletes the selection,
    Ctrl+Shift+Delete or Insert restores it.

    Signals: ``errorOccurred(str)``: an edit was refused (e.g. deleting every frame);
    the main window shows the message.
    """

    errorOccurred = Signal(str)

    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._syncing = False  # guards against doc <-> view feedback loops
        self.setAccessibleName("Frame strip")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)  # IconMode wraps by default: force one row
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(2)
        self.setFixedHeight(140)
        self.setMouseTracking(True)

        # Re-reports the visible rows once the pending layout pass has placed the cells.
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(0)
        self._relayout_timer.timeout.connect(self._report_visible)

        self._model = FrameListModel(doc, self)
        self.setModel(self._model)
        self.setItemDelegate(FrameDelegate(self))

        self.selectionModel().selectionChanged.connect(self._on_view_selection)
        self.selectionModel().currentChanged.connect(self._on_view_current)
        self.horizontalScrollBar().valueChanged.connect(self._report_visible)
        self._model.modelReset.connect(self._on_model_reset)
        doc.currentIndexChanged.connect(self._on_doc_current)
        doc.selectionChanged.connect(self._on_doc_selection)
        doc.stateChanged.connect(self._on_doc_state)
        self._on_model_reset()

    # ----------------------------------------------------------------- API
    @property
    def frame_model(self) -> FrameListModel:
        """The ``FrameListModel`` shown by this view."""
        return self._model

    def selected_rows(self) -> frozenset[int]:
        """Selected source indices; falls back to the current frame if nothing is selected."""
        rows = frozenset(i.row() for i in self.selectionModel().selectedIndexes())
        if not rows and self._doc.is_open:
            rows = frozenset({self._doc.current_index})
        return rows

    def delete_selected(self) -> None:
        """Delete the selected frames (one undo step); emits ``errorOccurred`` if refused."""
        if not self._doc.is_open:
            return
        try:
            self._doc.delete_frames(self.selected_rows())
        except ValueError as exc:
            self.errorOccurred.emit(str(exc))

    def restore_selected(self) -> None:
        """Restore the selected frames (one undo step)."""
        if self._doc.is_open:
            self._doc.restore_frames(self.selected_rows())

    def set_trim_start_at(self, row: int) -> None:
        """Make frame ``row``'s start time the trim start, keeping the trim end fixed."""
        meta = self._doc.meta
        if meta is None:
            return
        st = self._doc.state
        start = self._model.frame_start_ms(row)
        duration = st.trim_duration_ms
        if duration is not None:
            end = min(meta.total_duration_ms, st.trim_start_ms + duration)
            duration = end - start if end > start else None  # end before start: to the end
        self._set_trim(start, duration)

    def set_trim_end_at(self, row: int) -> None:
        """Make frame ``row``'s end the trim end (``None`` duration for the last frame)."""
        meta = self._doc.meta
        if meta is None:
            return
        start = self._doc.state.trim_start_ms
        if row >= meta.frame_count - 1:
            duration = None
        else:
            end = self._model.frame_start_ms(row) + meta.frames[row].effective_delay_ms
            duration = end - start
            if duration <= 0:
                self.errorOccurred.emit("The trim end must be after the trim start")
                return
        self._set_trim(start, duration)

    def build_context_menu(self, row: int | None = None) -> QMenu:
        """Build (but do not show) the context menu for frame ``row`` (default: current).

        Actions: 'Delete frame(s)', 'Restore frame(s)', 'Select all', 'Set trim start
        here', 'Set trim end here'. Returned so tests can ``trigger()`` the actions.
        """
        menu = QMenu(self)
        is_open = self._doc.is_open
        if row is None:
            row = self._doc.current_index
        sel = self.selected_rows() if is_open else frozenset()
        deleted = self._doc.state.deleted

        def add(text: str, name: str, slot, enabled: bool) -> None:
            act = menu.addAction(text)
            act.setObjectName(name)
            act.setEnabled(enabled)
            act.triggered.connect(slot)

        add("Delete frame(s)", "deleteFrames", self.delete_selected, bool(sel - deleted))
        add("Restore frame(s)", "restoreFrames", self.restore_selected, bool(sel & deleted))
        menu.addSeparator()
        add("Select all", "selectAll", self.selectAll, is_open)
        menu.addSeparator()
        add("Set trim start here", "trimStart", lambda: self.set_trim_start_at(row), is_open)
        add("Set trim end here", "trimEnd", lambda: self.set_trim_end_at(row), is_open)
        return menu

    # ------------------------------------------------------- Qt overrides
    def event(self, e: QEvent) -> bool:
        """Claim Delete/Backspace/Insert before window-level shortcuts see them."""
        if (
            e.type() == QEvent.Type.ShortcutOverride
            and isinstance(e, QKeyEvent)
            and e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace, Qt.Key.Key_Insert)
        ):
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        """Delete/Backspace delete; Ctrl+Shift+Delete or Insert restore; rest is native."""
        key = e.key()
        mods = e.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        )
        ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        if key == Qt.Key.Key_Insert or (key == Qt.Key.Key_Delete and mods == ctrl_shift):
            self.restore_selected()
            e.accept()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not mods:
            self.delete_selected()
            e.accept()
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e: QContextMenuEvent) -> None:
        """Right-click: the clicked frame becomes current (and selected if it wasn't)."""
        if not self._doc.is_open:
            return
        idx = self.indexAt(e.pos())
        row = None
        if idx.isValid():
            row = idx.row()
            if not self.selectionModel().isSelected(idx):
                self.selectionModel().setCurrentIndex(
                    idx, QItemSelectionModel.SelectionFlag.ClearAndSelect
                )
            else:
                self.selectionModel().setCurrentIndex(
                    idx, QItemSelectionModel.SelectionFlag.NoUpdate
                )
        self.build_context_menu(row).exec(e.globalPos())

    def resizeEvent(self, e) -> None:
        """Re-report the visible rows so thumbnails for newly exposed cells load."""
        super().resizeEvent(e)
        self._report_visible()

    # ------------------------------------------------------------ syncing
    def _set_trim(self, start: int, duration: int | None) -> None:
        try:
            self._doc.set_trim(start, duration, merge_key=None)
        except ValueError as exc:
            self.errorOccurred.emit(str(exc))

    def _report_visible(self, *_args: object) -> None:
        rows = self._model.rowCount()
        if rows == 0:
            return
        vp = self.viewport().rect()
        y = vp.center().y()
        first = self.indexAt(QPoint(vp.left() + 1, y))
        last = self.indexAt(QPoint(vp.right() - 1, y))
        f = first.row() if first.isValid() else 0
        # No cell at the right edge (gap after the last cell): estimate from cell width.
        l_row = last.row() if last.isValid() else f + max(1, vp.width() // CELL_WIDTH) + 1
        self._model.set_visible_rows(f, l_row)

    def _on_model_reset(self) -> None:
        self.setEnabled(self._doc.is_open)
        if self._doc.is_open:
            self._on_doc_current(self._doc.current_index)
            self._on_doc_selection(self._doc.selection)
        self._relayout_timer.start()  # report again after the layout pass
        self._report_visible()

    def _on_doc_state(self, _state: object) -> None:
        # A bound method (not a lambda) so Qt drops the connection when we are deleted.
        self.viewport().update()

    def _on_view_selection(self, *_args: object) -> None:
        if self._syncing:
            return
        rows = frozenset(i.row() for i in self.selectionModel().selectedIndexes())
        self._syncing = True
        try:
            self._doc.set_selection(rows)
        finally:
            self._syncing = False

    def _on_view_current(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.viewport().update()  # repaint the current-frame border
        if self._syncing or not current.isValid():
            return
        self._syncing = True
        try:
            self._doc.set_current_index(current.row())
        finally:
            self._syncing = False

    def _on_doc_current(self, i: int) -> None:
        if not 0 <= i < self._model.rowCount():
            return
        idx = self._model.index(i)
        if self.currentIndex() != idx and not self._syncing:
            self._syncing = True
            try:
                # NoUpdate: moving the playhead must not change the selection.
                self.selectionModel().setCurrentIndex(
                    idx, QItemSelectionModel.SelectionFlag.NoUpdate
                )
            finally:
                self._syncing = False
        self.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)

    def _on_doc_selection(self, sel: frozenset[int]) -> None:
        if self._syncing:
            return
        current = frozenset(i.row() for i in self.selectionModel().selectedIndexes())
        if current == sel:
            return
        selection = QItemSelection()
        for r in sel:
            if 0 <= r < self._model.rowCount():
                idx = self._model.index(r)
                selection.select(idx, idx)
        self._syncing = True
        try:
            self.selectionModel().select(
                selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
        finally:
            self._syncing = False
