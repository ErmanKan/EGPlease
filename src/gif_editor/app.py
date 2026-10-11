"""Application entry point: create the QApplication, run the Pillow self-test, show the
main window, and optionally open a GIF passed on the command line.

    python -m gif_editor [path/to/file.gif]
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from gif_editor import __version__
    from gif_editor.core.selftest import SelfTestError, run_selftest
    from gif_editor.ui.main_window import APP_NAME, MainWindow

    args = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")

    # We rely on undocumented Pillow internals (pinned version). Fail loudly, not subtly.
    try:
        run_selftest()
    except SelfTestError as exc:
        QMessageBox.critical(None, APP_NAME, f"Startup self-test failed:\n\n{exc}")
        return 1

    win = MainWindow()
    win.show()
    if len(args) > 1:
        win.open_file(args[1])
    code = app.exec()
    # A background task (opening a file, a preview render, the size estimate) may still be
    # running when the window closes. Let it finish before Python shuts down: interpreter
    # teardown under a running pool thread can crash on exit. Tasks are short; the timeout
    # only guards against a hang.
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)
    return code
