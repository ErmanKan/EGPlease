# `src/gif_editor/app.py`

> The application entry point: create the `QApplication`, run the Pillow self-test, show the main window, open a GIF given on the command line, and wait for background work before exiting.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** `gif_editor/__main__.py` (`python -m gif_editor [file.gif]`); `tests/ui/test_main_window.py::test_app_main_runs_selftest_and_window`; `tests/ui/test_smoke.py::test_failed_selftest_explains_and_exits`.
- **Uses:** `gif_editor/__init__.py` (`__version__`), `core/selftest.py` (`run_selftest`, `SelfTestError`), `ui/main_window.py` (`MainWindow`, `APP_NAME`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `main(argv=None) -> int` | function | Start the app and return the process exit code: `1` if the self-test fails, otherwise whatever `app.exec()` returns when the last window closes. `argv` defaults to `sys.argv`; `argv[1]`, if present, is opened. |

## How it works
1. **Imports inside `main`.** PySide6 and the UI modules are imported in the function body, so importing `gif_editor.app` stays cheap and works without Qt libraries (core tests must not need Qt).
2. **`QApplication`.** `QApplication.instance() or QApplication(args)`: reuse an existing instance (pytest-qt creates one) instead of crashing on a second. Set the application name (`"GIF Editor"`), version (`__version__`) and the **Fusion** style, so widgets look the same on every Windows version and theme.
3. **Self-test.** `run_selftest()` round-trips a tiny GIF through the undocumented Pillow internals the decoder and encoder rely on (Pillow is pinned, but a wrong wheel or a future bump could change them). On `SelfTestError` it shows a blocking `QMessageBox` and returns `1` **before** any window exists. Failing loudly at startup is better than writing subtly broken GIFs later. The check takes milliseconds.
   - **The dialog is written for a user, not a developer** (M4, `39e533b`). Only a broken build can fail here (Pillow is pinned and bundled), so the text says that plainly: headline *"GIF Editor can't start because one of its components is not working."*, informative text *"This is a problem with this copy of the program, not with your files. Download it again; if that doesn't help, report the details below."*, and the technical message (`"Startup self-test failed:\n<exc>"`) behind Qt's **Show Details…** button. Before M4 the dialog showed only "Startup self-test failed: <exc>", which tells a user nothing they can act on.
4. **Window.** `MainWindow()` then `show()`. The window sizes itself to fit the screen ([main window page](ui/main_window.md#window-size-and-the-pinned-generate-button)).
5. **Optional path.** If `len(args) > 1`, `win.open_file(args[1])`. This is the same asynchronous open as File → Open, so the window appears immediately and the GIF loads in the background. It is what "Open with…" / dragging a file onto the `.exe` uses on Windows. A bad path shows the usual plain-language "Can't open file" dialog in the window.
6. `code = app.exec()`: the Qt event loop runs until the window closes.
7. **Wait for background work** (M4, `9361dd6`). A pool task (opening a file, a preview render, the size estimate, a thumbnail batch) may still be running when the window closes. `QThreadPool.globalInstance().waitForDone(10_000)` lets it finish before `main` returns and Python tears the interpreter down; interpreter teardown under a running pool thread can crash on exit. Tasks are short; the 10 s timeout only guards against a hang. Then `return code`.

## Invariants & gotchas
- `main()` blocks in `app.exec()`. The tests replace `QApplication.exec` (or `QMessageBox.exec`) with a stub to run `main` without blocking.
- Only `args[1]` is used; further arguments are ignored. No option parsing.
- The self-test error dialog uses a blocking `exec()` on purpose: there is no window yet and the app is about to exit. (In-window errors use the non-blocking `MainWindow.show_explanation`.)
- A Generate still running at close time is cancelled by the window itself (`closeEvent`), not here; this wait only covers whatever is left in the pool.

## Tests
- `tests/ui/test_main_window.py::test_app_main_runs_selftest_and_window`: with `exec` stubbed, `main(["gif-editor"])` returns 0 after the real self-test passes, and a visible `MainWindow` exists.
- `tests/ui/test_smoke.py::test_failed_selftest_explains_and_exits`: with `run_selftest` replaced by one that raises, `main` returns 1 and shows exactly one dialog whose text says "can't start", whose informative text says "Download it again", and whose details contain the original error.
- **Gaps:** the command-line path argument; the exit wait (`waitForDone`).

## History
- `7a7b418`: scaffold placeholder (a `QMainWindow` with a label).
- `be70f38`: real entry point: self-test, `MainWindow`, optional path ([dev log, Milestone 2](../../../04-development-log.md#milestone-2-window-and-inspector)).
- `9361dd6` (M4): wait for the thread pool after `app.exec()`.
- `39e533b` (M4): plain self-test failure dialog with details ([dev log, Milestone 4](../../../04-development-log.md#milestone-4-hardening)).
