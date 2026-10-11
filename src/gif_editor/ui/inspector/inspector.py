"""The right-hand frame inspector: canvas, transport row, timebar and filmstrip stacked
vertically. Pure composition; every child talks to the shared ``Document`` itself."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from gif_editor.ui.document import Document
from gif_editor.ui.inspector.canvas import FrameCanvas
from gif_editor.ui.inspector.filmstrip import Filmstrip
from gif_editor.ui.inspector.player import Player
from gif_editor.ui.inspector.timebar import TimeBar
from gif_editor.ui.inspector.transport import TransportBar


class Inspector(QWidget):
    """Frame inspector panel. Children are public so the main window can wire actions."""

    def __init__(self, doc: Document, player: Player, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Frame inspector")
        self.canvas = FrameCanvas(doc, self)
        self.transport = TransportBar(doc, player, self)
        self.timebar = TimeBar(doc, self)
        self.filmstrip = Filmstrip(doc, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.canvas, 1)  # the canvas takes all spare height
        layout.addWidget(self.transport)
        layout.addWidget(self.timebar)
        layout.addWidget(self.filmstrip)
