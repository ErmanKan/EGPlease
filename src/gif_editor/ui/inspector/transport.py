"""Transport bar: the playback controls row under the canvas.

A horizontal strip of first / prev / play-pause / next / last tool buttons, a
"Preview edits" check box, a frame-info label and a "Save frame…" button.

The tool buttons are framed (not auto-raise) and their icons are drawn by
``theme.media_icon`` in the palette's text colour, redrawn whenever the palette
changes: Qt's built-in media icons are dark grey and vanish in dark mode.

The bar drives the ``Player`` (play, step, jump) and reads the ``Document`` for the
label. Keyboard shortcuts (Home, Left, Space, Right, End) are owned by the main
window; the tooltips only name them. "Save frame…" just emits
``saveFrameRequested``: the main window shows the file dialog.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from gif_editor.core.timeline import start_times_ms
from gif_editor.ui import theme
from gif_editor.ui.document import Document
from gif_editor.ui.inspector.player import Player

EMPTY_TEXT = "No GIF open"


def format_frame_info(index: int, count: int, start_ms: int, delay_ms: int, deleted: bool) -> str:
    """Label text, e.g. ``'Frame 37 / 120 · 1.48 s · 40 ms'`` (``index`` is 0-based)."""
    text = f"Frame {index + 1} / {count} · {start_ms / 1000:.2f} s · {delay_ms} ms"
    return text + " · deleted" if deleted else text


class TransportBar(QWidget):
    """Playback controls bound to a ``Document`` and its ``Player``."""

    saveFrameRequested = Signal()

    def __init__(self, doc: Document, player: Player, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._player = player
        self._starts: list[int] = []  # source start time of each frame (ms), cached

        self.setAccessibleName("Playback controls")

        def tool(name: str, key: str) -> QToolButton:
            b = QToolButton(self)
            b.setToolTip(f"{name} ({key})")
            b.setAccessibleName(name)
            return b

        self.first_button = tool("First frame", "Home")
        self.prev_button = tool("Previous frame", "Left")
        self.play_button = tool("Play/Pause", "Space")
        self.play_button.setCheckable(True)
        self.next_button = tool("Next frame", "Right")
        self.last_button = tool("Last frame", "End")
        self._playing = False
        self._update_icons()

        self.preview_check = QCheckBox("Preview edits", self)
        self.preview_check.setToolTip(
            "Play the edited timeline (trim, deleted frames, speed, FPS)\n"
            "instead of every source frame"
        )
        self.preview_check.setChecked(player.preview_edits)

        self.info_label = QLabel(EMPTY_TEXT, self)
        self.info_label.setAccessibleName("Frame info")

        self.save_button = QPushButton("Save frame…", self)
        self.save_button.setToolTip("Save the current frame as a PNG image")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        for w in (
            self.first_button,
            self.prev_button,
            self.play_button,
            self.next_button,
            self.last_button,
        ):
            lay.addWidget(w)
        lay.addSpacing(8)
        lay.addWidget(self.preview_check)
        lay.addSpacing(8)
        lay.addWidget(self.info_label)
        lay.addStretch(1)
        lay.addWidget(self.save_button)

        # Widget -> player / document
        self.first_button.clicked.connect(player.go_first)
        self.prev_button.clicked.connect(lambda: player.step(-1))
        self.play_button.clicked.connect(player.toggle)
        self.next_button.clicked.connect(lambda: player.step(1))
        self.last_button.clicked.connect(player.go_last)
        self.preview_check.toggled.connect(player.set_preview_edits)
        self.save_button.clicked.connect(self.saveFrameRequested)

        # Player / document -> widget
        player.playingChanged.connect(self._on_playing_changed)
        player.previewEditsChanged.connect(self._on_preview_changed)
        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._update_label)
        doc.currentIndexChanged.connect(self._update_label)

        self._on_source_changed()
        self._on_playing_changed(player.is_playing)

    # ------------------------------------------------------------------ icons
    def _update_icons(self) -> None:
        """(Re)draw the tool-button icons in the current palette's text colour."""
        pal = self.palette()
        for button, kind in (
            (self.first_button, "first"),
            (self.prev_button, "prev"),
            (self.next_button, "next"),
            (self.last_button, "last"),
        ):
            button.setIcon(theme.media_icon(kind, pal))
        self.play_button.setIcon(theme.media_icon("pause" if self._playing else "play", pal))

    def changeEvent(self, event: QEvent) -> None:
        # Light/dark switch (or any palette change): the icon colour must follow.
        # (PaletteChange, not ApplicationPaletteChange: see ui/theme.py.)
        if event.type() == QEvent.Type.PaletteChange:
            self._update_icons()
        super().changeEvent(event)

    # ------------------------------------------------------------------ slots
    def _on_source_changed(self) -> None:
        meta = self._doc.meta
        self._starts = start_times_ms(meta.delays_ms) if meta is not None else []
        # Disabling the bar disables every child: the "empty" state.
        self.setEnabled(self._doc.is_open)
        self._update_label()

    def _on_playing_changed(self, playing: bool) -> None:
        self.play_button.setChecked(playing)
        self._playing = playing
        self._update_icons()
        self.play_button.setToolTip("Pause (Space)" if playing else "Play (Space)")

    def _on_preview_changed(self, value: bool) -> None:
        if self.preview_check.isChecked() != value:
            self.preview_check.setChecked(value)

    def _update_label(self, *_args: object) -> None:
        meta = self._doc.meta
        if meta is None:
            self.info_label.setText(EMPTY_TEXT)
            return
        i = self._doc.current_index
        start = self._starts[i] if i < len(self._starts) else self._doc.frame_start_ms(i)
        self.info_label.setText(
            format_frame_info(
                i, meta.frame_count, start, meta.delays_ms[i], i in self._doc.state.deleted
            )
        )
