"""Top-level window: layout, menus, keyboard shortcuts, file open (incl. drag-and-drop),
Generate with progress/cancel, and Save-frame-as-PNG.

The window owns the one ``Document`` and the one ``Player``. Widgets are composed here
but never call each other: the window only wires *actions* (menu items/shortcuts) to
widget methods and shows dialogs. All slow work (decoding a GIF, generating) runs
through ``run_async`` so the UI stays responsive.

Dialogs that report errors use ``QMessageBox.open()`` (window-modal, non-blocking) so
tests can run headlessly; the last message is also kept in ``last_error``.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QScrollArea,
    QSplitter,
    QWidget,
)

from gif_editor.core.decoder import GifSource
from gif_editor.core.encoder import Cancelled
from gif_editor.core.pipeline import GenerateResult, export_frame_png, generate
from gif_editor.ui.document import Document
from gif_editor.ui.inspector.crop_item import CropItem
from gif_editor.ui.inspector.inspector import Inspector
from gif_editor.ui.inspector.player import Player
from gif_editor.ui.inspector.preview import PreviewService
from gif_editor.ui.settings_panel import SettingsPanel
from gif_editor.ui.workers import run_async

APP_NAME = "GIF Editor"
GIF_FILTER = "GIF images (*.gif)"
PNG_FILTER = "PNG images (*.png)"


def _local_gif(urls: list[QUrl]) -> Path | None:
    """First local ``.gif`` path among dropped URLs, if any."""
    for url in urls:
        if url.isLocalFile() and url.toLocalFile().lower().endswith(".gif"):
            return Path(url.toLocalFile())
    return None


class MainWindow(QMainWindow):
    """The application window. ``doc`` may be injected (tests)."""

    def __init__(self, doc: Document | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc = doc or Document(self)
        self.player = Player(self.doc, self)
        # Renders cropped/resized preview frames and keeps the output size estimate.
        self.preview = PreviewService(self.doc, self)
        self.last_error: str | None = None
        self.last_result: GenerateResult | None = None
        self._loading = False
        self._generating = False
        self._cancel: threading.Event | None = None
        self._progress: QProgressDialog | None = None

        # ---- layout: settings (scrollable) | inspector
        self.settings = SettingsPanel(self.doc, preview=self.preview)
        scroll = QScrollArea()
        scroll.setAccessibleName("Output settings")
        scroll.setWidget(self.settings)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(self.settings.minimumSizeHint().width() + 24)
        self.inspector = Inspector(self.doc, self.player)
        # The draggable crop rectangle lives in the canvas scene (scene = image pixels).
        self.crop_item = CropItem(self.doc)
        self.inspector.canvas.scene().addItem(self.crop_item)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 980])
        self.setCentralWidget(splitter)

        self._zoom_label = QLabel()
        self.statusBar().addPermanentWidget(self._zoom_label)

        self._build_actions()
        self._build_menus()
        self._connect()
        self.setAcceptDrops(True)  # the canvas refuses drops so they bubble up here
        self.resize(1300, 820)
        self._refresh_title()
        self._refresh_enabled()

    # ------------------------------------------------------------- actions
    def _action(self, text: str, slot, shortcut=None, *, tip: str = "") -> QAction:
        act = QAction(text, self)
        if isinstance(shortcut, QKeySequence.StandardKey):
            act.setShortcuts(shortcut)  # all platform bindings, not just the first
        elif shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
        act.triggered.connect(slot)
        self.addAction(act)  # window-wide shortcut even when menus are hidden
        return act

    def _build_actions(self) -> None:
        sc = QKeySequence.StandardKey
        insp = self.inspector
        self.act_open = self._action("&Open\u2026", self.open_dialog, sc.Open)
        self.act_generate = self._action(
            "&Generate\u2026", self.generate_dialog, "Ctrl+G", tip="Write the edited GIF"
        )
        self.act_save_frame = self._action(
            "Save &frame as PNG\u2026", lambda: self.save_frame_dialog(False), "Ctrl+Shift+S"
        )
        self.act_save_frame_edited = self._action(
            "Save frame with crop/size\u2026", lambda: self.save_frame_dialog(True)
        )
        self.act_close = self._action("&Close", self.doc.close, "Ctrl+W")
        self.act_quit = self._action("&Quit", self.close, "Ctrl+Q")

        self.act_undo = self.doc.undo_stack.createUndoAction(self, "&Undo")
        self.act_undo.setShortcuts(sc.Undo)
        self.act_redo = self.doc.undo_stack.createRedoAction(self, "&Redo")
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.addActions([self.act_undo, self.act_redo])
        self.act_delete = self._action("&Delete frame(s)", insp.filmstrip.delete_selected, "Del")
        self.act_restore = self._action(
            "&Restore frame(s)", insp.filmstrip.restore_selected, "Ctrl+Shift+Del"
        )
        self.act_trim_in = self._action("Set trim &start at playhead", self.trim_in_here, "I")
        self.act_trim_out = self._action("Set trim &end at playhead", self.trim_out_here, "O")
        self.act_trim_reset = self._action("Reset trim", self.reset_trim)

        self.act_play = self._action("&Play / pause", self.player.toggle, "Space")
        self.act_prev = self._action("Previous frame", lambda: self.player.step(-1), "Left")
        self.act_next = self._action("Next frame", lambda: self.player.step(1), "Right")
        self.act_prev10 = self._action(
            "Back 10 frames", lambda: self.player.step(-10), "Shift+Left"
        )
        self.act_next10 = self._action(
            "Forward 10 frames", lambda: self.player.step(10), "Shift+Right"
        )
        self.act_first = self._action("First frame", self.player.go_first, "Home")
        self.act_last = self._action("Last frame", self.player.go_last, "End")
        self.act_preview = QAction("Preview &edits", self, checkable=True)
        self.act_preview.setShortcut(QKeySequence("P"))
        self.act_preview.setToolTip("Play the output timing and show the cropped/resized frame")
        self.act_preview.toggled.connect(self.player.set_preview_edits)
        # "Preview edits" previews the whole output: timing (player) AND geometry (canvas).
        self.player.previewEditsChanged.connect(self.preview.set_geometry_enabled)
        self.player.previewEditsChanged.connect(self.act_preview.setChecked)
        self.addAction(self.act_preview)

        ci = self.crop_item
        self.act_crop_tool = QAction("&Crop tool", self, checkable=True)
        self.act_crop_tool.setShortcut(QKeySequence("C"))
        self.act_crop_tool.setStatusTip("Show the crop rectangle on the frame (drag to crop)")
        self.act_crop_tool.toggled.connect(self._on_crop_tool_toggled)
        self.addAction(self.act_crop_tool)
        self.act_crop_reset = self._action("Remove crop", ci.reset)
        self.act_crop_nudge = [
            self._action(f"Move crop {name}", lambda _=False, d=d: ci.nudge(*d), key)
            for name, d, key in (
                ("left", (-1, 0), "Ctrl+Left"),
                ("right", (1, 0), "Ctrl+Right"),
                ("up", (0, -1), "Ctrl+Up"),
                ("down", (0, 1), "Ctrl+Down"),
            )
        ]
        self.act_crop_resize = [
            self._action(f"{name} crop", lambda _=False, d=d: ci.resize(*d), key)
            for name, d, key in (
                ("Narrow", (-1, 0), "Ctrl+Shift+Left"),
                ("Widen", (1, 0), "Ctrl+Shift+Right"),
                ("Shorten", (0, -1), "Ctrl+Shift+Up"),
                ("Lengthen", (0, 1), "Ctrl+Shift+Down"),
            )
        ]

        cv = insp.canvas
        self.act_fit = self._action("Zoom to &fit", cv.zoom_fit, "Ctrl+0")
        self.act_actual = self._action("Actual &size (100%)", cv.zoom_actual, "Ctrl+1")
        self.act_zoom_in = self._action("Zoom &in", cv.zoom_in, sc.ZoomIn)
        self.act_zoom_out = self._action("Zoom &out", cv.zoom_out, sc.ZoomOut)

        # Actions that need an open document (Quit/Open always work).
        self._doc_actions = [
            self.act_generate, self.act_save_frame, self.act_save_frame_edited, self.act_close,
            self.act_delete, self.act_restore, self.act_trim_in, self.act_trim_out,
            self.act_trim_reset, self.act_play, self.act_prev, self.act_next, self.act_prev10,
            self.act_next10, self.act_first, self.act_last, self.act_preview, self.act_fit,
            self.act_actual, self.act_zoom_in, self.act_zoom_out, self.act_crop_tool,
            self.act_crop_reset,
        ]  # fmt: skip
        # Nudge/resize act on the visible rectangle only; _update_crop_tool enables them.
        self._crop_edit_actions = [*self.act_crop_nudge, *self.act_crop_resize]

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addActions([self.act_open, self.act_generate])
        m.addSeparator()
        m.addActions([self.act_save_frame, self.act_save_frame_edited])
        m.addSeparator()
        m.addActions([self.act_close, self.act_quit])
        m = mb.addMenu("&Edit")
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_delete, self.act_restore])
        m.addSeparator()
        m.addActions([self.act_trim_in, self.act_trim_out, self.act_trim_reset])
        m = mb.addMenu("&Crop")
        m.addActions([self.act_crop_tool, self.act_crop_reset])
        m.addSeparator()
        m.addActions([*self.act_crop_nudge, *self.act_crop_resize])
        m = mb.addMenu("&Playback")
        m.addActions([self.act_play, self.act_preview])
        m.addSeparator()
        m.addActions(
            [self.act_first, self.act_prev10, self.act_prev, self.act_next, self.act_next10,
             self.act_last]
        )  # fmt: skip
        m = mb.addMenu("&View")
        m.addActions([self.act_fit, self.act_actual, self.act_zoom_in, self.act_zoom_out])

    def _connect(self) -> None:
        self.doc.sourceChanged.connect(self._refresh_title)
        self.doc.sourceChanged.connect(self._refresh_enabled)
        self.settings.generateRequested.connect(self.generate_dialog)
        self.inspector.transport.saveFrameRequested.connect(lambda: self.save_frame_dialog(False))
        self.inspector.filmstrip.errorOccurred.connect(self.show_error)
        self.inspector.canvas.set_preview(self.preview)
        self.crop_item.cropActiveChanged.connect(self._on_crop_active_changed)
        self.crop_item.previewChanged.connect(self._on_crop_dragged)
        self.preview.geometryChanged.connect(lambda _on: self._update_crop_tool())
        self.doc.sourceChanged.connect(self._sync_crop_tool)
        self.inspector.canvas.zoomChanged.connect(
            lambda z: self._zoom_label.setText(f"{z * 100:.0f}%")
        )

    # ------------------------------------------------------------- refresh
    def _refresh_title(self) -> None:
        path = self.doc.path
        self.setWindowTitle(f"{path.name} \u2014 {APP_NAME}" if path else APP_NAME)
        if not self.doc.is_open:
            self._zoom_label.clear()

    def _refresh_enabled(self) -> None:
        on = self.doc.is_open and not self._loading and not self._generating
        for act in self._doc_actions:
            act.setEnabled(on)
        if hasattr(self, "crop_item"):  # not yet created during __init__
            self._update_crop_tool()
        self.act_open.setEnabled(not self._loading and not self._generating)

    # ---------------------------------------------------------------- errors
    def show_error(self, message: str, title: str = "GIF Editor") -> None:
        """Show a non-blocking warning and remember it (``last_error``)."""
        self.last_error = message
        self.statusBar().showMessage(message, 8000)
        box = QMessageBox(QMessageBox.Icon.Warning, title, message, parent=self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    # ------------------------------------------------------------------ open
    def open_dialog(self) -> None:
        start = str(self.doc.path.parent) if self.doc.path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open GIF", start, GIF_FILTER)
        if path:
            self.open_file(path)

    def open_file(self, path: str | Path) -> None:
        """Decode ``path`` off the GUI thread, then hand it to the Document."""
        if self._loading or self._generating:
            return
        path = Path(path)
        self.player.pause()
        self._loading = True
        self._refresh_enabled()
        self.statusBar().showMessage(f"Opening {path.name}\u2026")
        self.setCursor(Qt.CursorShape.BusyCursor)

        def done(source: GifSource) -> None:
            self._loading = False
            self.unsetCursor()
            self.doc.set_source(source, path)
            self._refresh_enabled()
            meta = source.meta
            msg = f"Opened {path.name}: {meta.frame_count} frames, {meta.width}\u00d7{meta.height}"
            if source.warnings:
                msg += " \u2014 " + "; ".join(source.warnings)
            self.statusBar().showMessage(msg, 8000)

        def failed(message: str, _exc: BaseException) -> None:
            self._loading = False
            self.unsetCursor()
            self._refresh_enabled()
            self.show_error(f"Could not open {path.name}:\n{message}", "Open failed")

        run_async(lambda: GifSource.open(path), on_done=done, on_error=failed)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _local_gif(event.mimeData().urls()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _local_gif(event.mimeData().urls())
        if path is not None:
            event.acceptProposedAction()
            self.open_file(path)

    # ------------------------------------------------------------------ crop
    def _update_crop_tool(self) -> None:
        """Show the rectangle iff the tool is on and we're not previewing the output.

        In geometry preview the canvas shows the already-cropped output, whose pixels no
        longer correspond to source pixels, so a source-pixel rectangle would be wrong there.
        """
        shown = (
            self.doc.is_open
            and self.act_crop_tool.isChecked()
            and not self.preview.geometry_enabled
            and not self.is_busy
        )
        self.crop_item.set_tool_enabled(shown)
        # Ctrl+arrow nudge/resize only make sense on a rectangle you can see. Leaving them
        # enabled while hidden would make the menu items look usable while doing nothing.
        for act in self._crop_edit_actions:
            act.setEnabled(shown)

    def _on_crop_tool_toggled(self, on: bool) -> None:
        self._update_crop_tool()
        if on and self.doc.is_open and self.doc.state.crop is None:
            self.crop_item.activate()  # give the user a box to drag (one undo step)

    def _on_crop_active_changed(self, active: bool) -> None:
        # A crop created elsewhere (the panel) turns the tool on so it is visible. Removing
        # the crop leaves the tool as it was (the user may want to drag a new one).
        if active and not self.act_crop_tool.isChecked():
            self.act_crop_tool.setChecked(True)

    def _sync_crop_tool(self) -> None:
        """New file: the tool starts off (no handles on a fresh, uncropped image)."""
        self.act_crop_tool.blockSignals(True)
        self.act_crop_tool.setChecked(False)
        self.act_crop_tool.blockSignals(False)
        self._update_crop_tool()

    def _on_crop_dragged(self, rect) -> None:
        r = rect.toRect()
        self.statusBar().showMessage(f"Crop {r.width()}\u00d7{r.height()} at {r.x()},{r.y()}", 2000)

    # -------------------------------------------------------------- trimming
    def trim_in_here(self) -> None:
        """Start the trim window at the current frame, keeping the current end."""
        meta, st = self.doc.meta, self.doc.state
        if meta is None:
            return
        start = self.doc.frame_start_ms(self.doc.current_index)
        end = None if st.trim_duration_ms is None else st.trim_start_ms + st.trim_duration_ms
        duration = None if end is None or end <= start else end - start
        self.doc.set_trim(start, duration, merge_key=None)

    def trim_out_here(self) -> None:
        """End the trim window after the current frame (None = to the end)."""
        meta, st = self.doc.meta, self.doc.state
        if meta is None:
            return
        i = self.doc.current_index
        end = self.doc.frame_start_ms(i) + meta.delays_ms[i]
        if end <= st.trim_start_ms:
            self.show_error("The trim end must be after the trim start.")
            return
        duration = None if end >= meta.total_duration_ms else end - st.trim_start_ms
        self.doc.set_trim(st.trim_start_ms, duration, merge_key=None)

    def reset_trim(self) -> None:
        self.doc.set_trim(0, None, merge_key=None)

    # -------------------------------------------------------------- generate
    def generate_dialog(self) -> None:
        if not self.doc.is_open or self._generating:
            return
        try:
            empty = self.doc.plan().frame_count == 0
        except ValueError as exc:
            self.show_error(str(exc))
            return
        if empty:  # same guard as the Generate button, so Ctrl+G can't bypass it
            self.show_error("Nothing to generate: every frame is deleted or trimmed away.")
            return
        src = self.doc.path
        suggestion = str(src.with_name(f"{src.stem}-edited.gif")) if src else "output.gif"
        path, _ = QFileDialog.getSaveFileName(self, "Generate GIF", suggestion, GIF_FILTER)
        if path:
            if not path.lower().endswith(".gif"):
                path += ".gif"
            self.generate_to(path)

    def generate_to(self, path: str | Path) -> None:
        """Run Generate in the background with a cancellable progress dialog."""
        source, state = self.doc.source, self.doc.state  # state is immutable: safe snapshot
        if source is None or self._generating:
            return
        try:
            plan = self.doc.plan()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        total = plan.frame_count
        if total == 0:
            reason = "; ".join(plan.warnings) or "every frame is deleted or trimmed away"
            self.show_error(f"Nothing to generate: {reason}")
            return
        path = Path(path)
        self.player.pause()
        self._generating = True
        self._refresh_enabled()
        self._cancel = cancel = threading.Event()
        dlg = QProgressDialog("Generating\u2026", "Cancel", 0, max(total, 1), self)
        dlg.setWindowTitle("Generate")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        dlg.canceled.connect(cancel.set)
        self._progress = dlg

        def progress(done: int, _total: object) -> None:
            if self._progress is not None:
                self._progress.setValue(done)

        def finish() -> None:
            self._generating = False
            self._cancel = None
            if self._progress is not None:
                self._progress.reset()
                self._progress.deleteLater()
                self._progress = None
            self._refresh_enabled()

        def done(result: GenerateResult) -> None:
            finish()
            self.last_result = result
            kb = result.size_bytes / 1024
            msg = (
                f"Saved {result.path.name}: {result.frame_count} frames, "
                f"{result.duration_ms / 1000:.2f} s, {result.width}\u00d7{result.height}, "
                f"{kb:,.1f} KB"
            )
            if result.warnings:
                msg += " \u2014 " + "; ".join(result.warnings)
            self.statusBar().showMessage(msg, 15000)

        def failed(message: str, exc: BaseException) -> None:
            finish()
            if isinstance(exc, Cancelled):
                self.statusBar().showMessage("Generate cancelled; nothing was written.", 6000)
            else:
                self.show_error(f"Generate failed:\n{message}", "Generate failed")

        run_async(
            lambda report: generate(source, state, path, progress=report, cancel=cancel),
            on_done=done,
            on_error=failed,
            on_progress=progress,
        )

    def cancel_generate(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    @property
    def is_busy(self) -> bool:
        return self._loading or self._generating

    # ------------------------------------------------------------ save frame
    def save_frame_dialog(self, with_edits: bool) -> None:
        if not self.doc.is_open:
            return
        src = self.doc.path
        n = self.doc.current_index + 1
        suggestion = str(src.with_name(f"{src.stem}-frame{n:03d}.png")) if src else "frame.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save frame as PNG", suggestion, PNG_FILTER)
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            self.save_frame_to(path, with_edits)

    def save_frame_to(self, path: str | Path, with_edits: bool = False) -> Path | None:
        """Save the current source frame as PNG (optionally with crop + resize)."""
        source = self.doc.source
        if source is None:
            return None
        try:
            out = export_frame_png(
                source, self.doc.current_index, path, self.doc.state if with_edits else None
            )
        except (OSError, ValueError) as exc:
            self.show_error(f"Could not save the frame:\n{exc}", "Save failed")
            return None
        self.statusBar().showMessage(f"Saved frame {self.doc.current_index + 1} to {out}", 6000)
        return out

    # ----------------------------------------------------------------- close
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._generating:
            # Cancel cleanly; the encoder deletes its temp file. Close once it reports back.
            self.cancel_generate()
            event.ignore()
            self.statusBar().showMessage("Cancelling Generate\u2026 close again in a moment.")
            return
        self.player.pause()
        self.doc.close()
        event.accept()
