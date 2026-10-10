# `src/gif_editor/app.py`

> The application entry point: create the `QApplication`, run the Pillow self-test, show the main window, and open a GIF given on the command line.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** `gif_editor/__main__.py` (`python -m gif_editor [file.gif]`); `tests/ui/test_main_window.py::test_app_main_runs_selftest_and_window`.
- **Uses:** `gif_editor/__init__.py` (`__version__`), `core/selftest.py` (`run_selftest`, `SelfTestError`), `ui/main_window.py` (`MainWindow`, `APP_NAME`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `main(argv=None) -> int` | function | Start the app and return the process exit code: `1` if the self-test fails, otherwise whatever `app.exec()` returns when the last window closes. `argv` defaults to `sys.argv`; `argv[1]`, if present, is opened. |

## How it works
1. **Imports inside `main`.** PySide6 and the UI modules are imported in the function body, so importing `gif_editor.app` stays cheap and works without Qt libraries (core tests must not need Qt).
2. **`QApplication`.** `QApplication.instance() or QApplication(args)`: reuse an existing instance (pytest-qt creates one) instead of crashing on a second. Set the application name (`"GIF Editor"`), version (`__version__`) and the **Fusion** style, so widgets look the same on every Windows version and theme.
3. **Self-test.** `run_selftest()` round-trips a tiny GIF through the undocumented Pillow internals the decoder and encoder rely on (Pillow is pinned, but a wrong wheel or a future bump could change them). On `SelfTestError` it shows a blocking `QMessageBox.critical` ("Startup self-test failed: …") and returns `1` **before** any window exists. Failing loudly at startup is better than writing subtly broken GIFs later. The check takes milliseconds.
4. **Window.** `MainWindow()` then `show()`.
5. **Optional path.** If `len(args) > 1`, `win.open_file(args[1])`. This is the same asynchronous open as File → Open, so the window appears immediately and the GIF loads in the background. It is what "Open with…" / dragging a file onto the `.exe` uses on Windows. A bad path shows the usual "Open failed" message in the window.
6. `return app.exec()`: the Qt event loop runs until the window closes.

## Invariants & gotchas
- `main()` blocks in `app.exec()`. The test replaces `QApplication.exec` with a stub to run `main` without blocking.
- Only `args[1]` is used; further arguments are ignored. No option parsing.
- The self-test error dialog uses blocking `critical()` on purpose: there is no window yet and the app is about to exit. (In-window errors use the non-blocking `show_error`.)

## Tests
- `tests/ui/test_main_window.py::test_app_main_runs_selftest_and_window`: with `exec` stubbed, `main(["gif-editor"])` returns 0 after the real self-test passes, and a visible `MainWindow` exists.
- **Gaps:** the self-test failure branch (exit code 1); the command-line path argument.

## History
- `7a7b418`: scaffold placeholder (a `QMainWindow` with a label).
- `be70f38`: real entry point: self-test, `MainWindow`, optional path ([dev log, Milestone 2](../../../04-development-log.md#milestone-2-window-and-inspector)).
