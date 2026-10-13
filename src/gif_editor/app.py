"""Application entry point: create the QApplication, run the Pillow self-test, show the
main window, and optionally open a GIF passed on the command line.

    python -m gif_editor [path/to/file.gif]
"""

from __future__ import annotations

import sys


def _arm_smoke_exit(app, win, expect_file: bool, timeout_ms: int = 30_000) -> None:
    """Quit once the window is up (and the file, if any, has loaded); print one status line.

    Exit 0 = window shown and file opened; 1 = the open failed or timed out. Polls with a
    timer instead of waiting on signals, because a failed open reports through a dialog that
    has no completion signal; ``last_error`` is set in both cases.
    """
    from PySide6.QtCore import QElapsedTimer, QTimer

    clock = QElapsedTimer()
    clock.start()
    timer = QTimer(app)

    def poll() -> None:
        loaded = win.doc.is_open and not win.is_busy
        failed = win.last_error is not None
        if not expect_file or loaded or failed or clock.elapsed() > timeout_ms:
            timer.stop()
            if not expect_file:
                print("GUI OK window shown")
                app.exit(0)
            elif loaded:
                meta = win.doc.meta
                print(f"GUI OK opened {meta.frame_count} frames {meta.width}x{meta.height}")
                app.exit(0)
            else:
                reason = win.last_error or "timed out"
                print("GUI FAIL " + reason.replace("\n", " "))
                app.exit(1)

    timer.timeout.connect(poll)
    timer.start(50)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    # Headless one-shot edit (packaging smoke test, scripting): no window, and no Qt at all.
    # Importing Qt loads a platform plugin (needs a display or an offscreen setup), and this
    # path must work on a bare server, so it is handled before anything imports Qt.
    if "--edit-spec" in args:
        i = args.index("--edit-spec")
        try:
            source, spec = args[i + 1], args[i + 2]
        except IndexError:
            print("usage: GifEditor --edit-spec IN.gif SPEC")
            return 2
        from gif_editor.headless import run_edit_spec

        return run_edit_spec(source, spec)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from gif_editor import __version__
    from gif_editor.core.selftest import SelfTestError, run_selftest
    from gif_editor.resources import icon_path
    from gif_editor.ui.main_window import APP_NAME, MainWindow

    app = QApplication.instance() or QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    # Window/taskbar icon. Inside a onefile build the icon is also embedded in the
    # executable's Windows resource, but that only covers Explorer, not the running window.
    icon = icon_path()
    if icon is not None:
        app.setWindowIcon(QIcon(str(icon)))

    # We rely on undocumented Pillow internals (pinned version). Fail loudly, not subtly.
    try:
        run_selftest()
    except SelfTestError as exc:
        # Only a broken build can get here (the Pillow version is pinned and bundled), so
        # the message says so plainly and keeps the technical text for a bug report.
        box = QMessageBox(
            QMessageBox.Icon.Critical,
            APP_NAME,
            f"{APP_NAME} can't start because one of its components is not working.",
        )
        box.setInformativeText(
            "This is a problem with this copy of the program, not with your files. "
            "Download it again; if that doesn't help, report the details below."
        )
        box.setDetailedText(f"Startup self-test failed:\n{exc}")
        box.exec()
        return 1

    win = MainWindow()
    win.show()
    smoke = "--smoke-gui" in args
    files = [a for a in args[1:] if not a.startswith("--")]
    if files:
        win.open_file(files[0])
    if smoke:
        # Packaging check (scripts/smoke_build.py): the real window, Qt platform plugin,
        # decoder and canvas all run, then the app quits by itself with a status code. The
        # --edit-spec path proves the core; this one proves the Qt half of the bundle.
        _arm_smoke_exit(app, win, bool(files))
    code = app.exec()
    # A background task (opening a file, a preview render, the size estimate) may still be
    # running when the window closes. Let it finish before Python shuts down: interpreter
    # teardown under a running pool thread can crash on exit. Tasks are short; the timeout
    # only guards against a hang.
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)
    return code
