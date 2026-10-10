"""Application entry point. The UI arrives in Milestone 2; for now it shows a placeholder window."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("GIF Editor")
    app.setStyle("Fusion")
    win = QMainWindow()
    win.setWindowTitle("GIF Editor")
    win.setCentralWidget(QLabel("GIF Editor — UI coming in Milestone 2"))
    win.resize(1100, 700)
    win.show()
    return app.exec()
