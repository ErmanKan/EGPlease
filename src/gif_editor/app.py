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
                print("GUI OK window shown", flush=True)
                app.exit(0)
            elif loaded:
                meta = win.doc.meta
                print(
                    f"GUI OK opened {meta.frame_count} frames {meta.width}x{meta.height}",
                    flush=True,
                )
                app.exit(0)
            else:
                reason = win.last_error or "timed out"
                print("GUI FAIL " + reason.replace("\n", " "), flush=True)
                app.exit(1)

    timer.timeout.connect(poll)
    timer.start(50)


def _stage(smoke: bool, name: str) -> None:
    """In smoke mode, print a start-up stage marker and flush it at once.

    A hard crash (Windows access violation) discards buffered stdout, so without the flush a
    crash after "GUI OK" looks the same as a crash before the window exists.
    """
    if smoke:
        print(f"GUI STAGE {name}", flush=True)


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

    smoke = "--smoke-gui" in args
    if smoke:
        # On a native crash, dump the Python stack of every thread to stderr.
        import contextlib
        import faulthandler

        # stderr may not be a real file (no console, or a test harness replaced it; then
        # io.UnsupportedOperation, an OSError). The stage markers still locate a crash.
        with contextlib.suppress(AttributeError, ValueError, OSError):
            faulthandler.enable(all_threads=True)
    _stage(smoke, "importing Qt")
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from gif_editor import __version__
    from gif_editor.core.selftest import SelfTestError, run_selftest
    from gif_editor.nuitka_compat import skip_pyside_connect_probe
    from gif_editor.resources import icon_path
    from gif_editor.ui import theme
    from gif_editor.ui.main_window import APP_NAME, MainWindow

    # Packaged build only: keep Nuitka's PySide6 connect probe from corrupting memory (it
    # crashed about half of all starts). Must run before the first Signal.connect.
    _stage(smoke, skip_pyside_connect_probe())
    _stage(smoke, "creating QApplication")
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    theme.install(app)  # button contrast in dark mode; follows Windows' light/dark switch
    # Window/taskbar icon. Inside a onefile build the icon is also embedded in the
    # executable's Windows resource, but that only covers Explorer, not the running window.
    icon = icon_path()
    if icon is not None:
        _stage(smoke, "loading window icon")
        app.setWindowIcon(QIcon(str(icon)))
    _stage(smoke, "self-test")

    # We rely on undocumented Pillow internals (pinned version). Fail loudly, not subtly.
    try:
        run_selftest()
    except SelfTestError as exc:
        if "--smoke-gui" in args:
            # Packaging check: a modal dialog would block until the smoke test's timeout.
            # Fail at once with one line instead; the self-test failing IS the finding.
            print(f"GUI FAIL startup self-test: {exc}")
            return 1
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

    _stage(smoke, "creating main window")
    win = MainWindow()
    _stage(smoke, "showing main window")
    win.show()
    files = [a for a in args[1:] if not a.startswith("--")]
    if files:
        win.open_file(files[0])
    if smoke:
        # Packaging check (scripts/smoke_build.py): the real window, Qt platform plugin,
        # decoder and canvas all run, then the app quits by itself with a status code. The
        # --edit-spec path proves the core; this one proves the Qt half of the bundle.
        _arm_smoke_exit(app, win, bool(files))
    _stage(smoke, "event loop")
    code = app.exec()
    _stage(smoke, f"event loop ended ({code}), waiting for background tasks")
    # A background task (opening a file, a preview render, the size estimate) may still be
    # running when the window closes. Let it finish before Python shuts down: interpreter
    # teardown under a running pool thread can crash on exit. Tasks are short; the timeout
    # only guards against a hang.
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)
    _stage(smoke, "exiting")
    return code
