# `src/gif_editor/app.py`

> The application entry point: hand `--edit-spec` to the headless path before any Qt import; otherwise create the `QApplication`, set the window icon, run the Pillow self-test, show the main window, open a GIF given on the command line (and with `--smoke-gui` quit by itself), and wait for background work before exiting.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** `gif_editor/__main__.py` (`python -m gif_editor [file.gif]`, and the built `GifEditor.exe`, whose entry point is `__main__.py`); `tests/ui/test_main_window.py::test_app_main_runs_selftest_and_window`; `tests/ui/test_smoke.py::test_failed_selftest_explains_and_exits`; [`scripts/smoke_build.py`](../../scripts/smoke_build.md) (through a built binary: `--edit-spec`, `--smoke-gui`).
- **Uses:** `gif_editor/__init__.py` (`__version__`), [`headless.py`](headless.md) (`run_edit_spec`), [`resources/__init__.py`](resources/__init__.md) (`icon_path`), `core/selftest.py` (`run_selftest`, `SelfTestError`), `ui/main_window.py` (`MainWindow`, `APP_NAME`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `main(argv=None) -> int` | function | Start the app and return the process exit code: `1` if the self-test fails, otherwise whatever `app.exec()` returns when the last window closes. `argv` defaults to `sys.argv`; the first argument after `argv[0]` that does not start with `--` is opened. |
| `_arm_smoke_exit(app, win, expect_file, timeout_ms=30_000)` | helper | For `--smoke-gui`: poll every 50 ms; once the window is up (and the file loaded, or its open failed, or 30 s passed) print `GUI OK …` / `GUI FAIL …` and `app.exit(0/1)`. |

Command line:

| Arguments | Effect | Exit code |
|---|---|---|
| `[FILE]` | Normal GUI; `FILE` (first non-`--` argument) is opened. | from `app.exec()` |
| `--edit-spec IN.gif SPEC` | Headless edit + Generate, **no Qt imported**; prints `RESULT …` or `ERROR …` ([headless page](headless.md)). | 0 written, 1 error, 2 missing arguments |
| `--smoke-gui [FILE]` | Normal start, then quit by itself once the window (and `FILE`) is up; prints `GUI OK …` or `GUI FAIL …`. Packaging check. | 0 ok, 1 open failed / timed out |

## How it works
1. **`--edit-spec` first, before any Qt import** (M5, `3531ca0`). If `--edit-spec` is anywhere in the arguments, the next two arguments are the input GIF and the spec; `main` imports `gif_editor.headless` and returns `run_edit_spec(source, spec)`. If they are missing it prints `usage: GifEditor --edit-spec IN.gif SPEC` and returns 2. *Why first:* importing PySide6's GUI modules loads `libEGL` and needs a Qt platform plugin; the headless path must run on a machine with no display (a CI runner, a server) and must still work in a build whose Qt half is broken, so the smoke test can tell the two halves apart. Checked for this page: after `main([..., "--edit-spec", ...])` no `PySide6` module is loaded.
2. **Imports inside `main`.** PySide6 and the UI modules are imported in the function body, so importing `gif_editor.app` stays cheap and works without Qt libraries (core tests must not need Qt).
3. **`QApplication`.** `QApplication.instance() or QApplication(args)`: reuse an existing instance (pytest-qt creates one) instead of crashing on a second. Set the application name (`"GIF Editor"`), version (`__version__`) and the **Fusion** style, so widgets look the same on every Windows version and theme. Then `theme.install(app)`: Fusion's dark-mode buttons were hard to see, so the palette is tuned for button contrast and re-tuned when Windows switches between light and dark ([theme](ui/theme.md)).
   - **Window icon** (M5): `icon_path()` → `app.setWindowIcon(QIcon(path))` if an icon was found. This is the icon of the *running* window (title bar, Alt+Tab, taskbar). The icon of the `.exe` file in Explorer is embedded separately at build time (`--windows-icon-from-ico`). Until `a2e41d0` `icon_path()` always returned `None` (a path bug in `resources`), so the window had no icon; it is non-null since the fix.
4. **Self-test.** `run_selftest()` round-trips a tiny GIF through the undocumented Pillow internals the decoder and encoder rely on (Pillow is pinned, but a wrong wheel or a future bump could change them). On `SelfTestError` it shows a blocking `QMessageBox` and returns `1` **before** any window exists. Failing loudly at startup is better than writing subtly broken GIFs later. The check takes milliseconds.
   - **The dialog is written for a user, not a developer** (M4, `39e533b`). Only a broken build can fail here (Pillow is pinned and bundled), so the text says that plainly: headline *"GIF Editor can't start because one of its components is not working."*, informative text *"This is a problem with this copy of the program, not with your files. Download it again; if that doesn't help, report the details below."*, and the technical message (`"Startup self-test failed:\n<exc>"`) behind Qt's **Show Details…** button. Before M4 the dialog showed only "Startup self-test failed: <exc>", which tells a user nothing they can act on.
5. **Window.** `MainWindow()` then `show()`. The window sizes itself to fit the screen ([main window page](ui/main_window.md#window-size-and-the-pinned-generate-button)).
6. **Optional path.** `files = [a for a in args[1:] if not a.startswith("--")]`; if there is one, `win.open_file(files[0])`. (Before M5 it was simply `args[1]`; with `--smoke-gui` possible as an argument, the file is now the first non-flag argument.) This is the same asynchronous open as File → Open, so the window appears immediately and the GIF loads in the background. It is what "Open with…" / dragging a file onto the `.exe` uses on Windows. A bad path shows the usual plain-language "Can't open file" dialog in the window.
7. **`--smoke-gui`** (M5, `7bac56c`). If present, `_arm_smoke_exit(app, win, bool(files))` starts a 50 ms `QTimer`. Each tick checks: no file expected → `GUI OK window shown`, exit 0; the document is open and the window not busy → `GUI OK opened <n> frames <w>x<h>`, exit 0; `win.last_error` is set (the open failed) or 30 s passed → `GUI FAIL <reason>`, exit 1. *Why polling:* a failed open reports through a non-blocking dialog that has no "finished" signal, but both outcomes leave a plain flag (`doc.is_open`/`is_busy` or `last_error`), so a timer that reads them covers every case, including a hang (the timeout). This is the only way to check the Qt half of a built binary automatically ([smoke test](../../scripts/smoke_build.md)).
8. `code = app.exec()`: the Qt event loop runs until the window closes.
9. **Wait for background work** (M4, `9361dd6`). A pool task (opening a file, a preview render, the size estimate, a thumbnail batch) may still be running when the window closes. `QThreadPool.globalInstance().waitForDone(10_000)` lets it finish before `main` returns and Python tears the interpreter down; interpreter teardown under a running pool thread can crash on exit. Tasks are short; the 10 s timeout only guards against a hang. Then `return code`.

## Invariants & gotchas
- `main()` blocks in `app.exec()`. The tests replace `QApplication.exec` (or `QMessageBox.exec`) with a stub to run `main` without blocking.
- Only the first non-`--` argument is used; further files are ignored. There is no option parser: `--edit-spec` and `--smoke-gui` are recognised with plain `in` tests, and unknown `--flags` are ignored (Qt may also read its own options from `args`).
- **No Qt import may move above the `--edit-spec` branch** (AGENTS.md rule). Module-level imports in this file must stay Qt-free for the same reason.
- With `--smoke-gui` a failed self-test does **not** show the blocking dialog: it prints `GUI FAIL startup self-test: <reason>` and returns 1 at once, so a broken build fails the smoke test immediately instead of by its 120 s process timeout (`test_smoke_gui_fails_fast_on_a_broken_selftest`).
- The self-test error dialog uses a blocking `exec()` on purpose: there is no window yet and the app is about to exit. (In-window errors use the non-blocking `MainWindow.show_explanation`.)
- A Generate still running at close time is cancelled by the window itself (`closeEvent`), not here; this wait only covers whatever is left in the pool.

## Tests
- `tests/ui/test_main_window.py::test_app_main_runs_selftest_and_window`: with `exec` stubbed, `main(["gif-editor"])` returns 0 after the real self-test passes, and a visible `MainWindow` exists.
- `tests/ui/test_smoke.py::test_failed_selftest_explains_and_exits`: with `run_selftest` replaced by one that raises, `main` returns 1 and shows exactly one dialog whose text says "can't start", whose informative text says "Download it again", and whose details contain the original error.
- `tests/core/test_headless.py`: the `run_edit_spec` the `--edit-spec` branch calls.
- **Gaps:** the command-line path argument; the `--edit-spec` branch in `main` (argument extraction, exit code 2) and `--smoke-gui`/`_arm_smoke_exit`, which are only exercised through [`scripts/smoke_build.py`](../../scripts/smoke_build.md) on a built binary; the window icon; the exit wait (`waitForDone`).

## History
- `7a7b418`: scaffold placeholder (a `QMainWindow` with a label).
- `be70f38`: real entry point: self-test, `MainWindow`, optional path ([dev log, Milestone 2](../../../04-development-log.md#milestone-2-window-and-inspector)).
- `9361dd6` (M4): wait for the thread pool after `app.exec()`.
- `39e533b` (M4): plain self-test failure dialog with details ([dev log, Milestone 4](../../../04-development-log.md#milestone-4-hardening)).
- `3531ca0` (M5): `--edit-spec` handled before any Qt import; window icon from `resources.icon_path()`.
- `7bac56c` (M5): `--smoke-gui` and `_arm_smoke_exit`; the file argument is the first non-flag argument ([dev log, Milestone 5](../../../04-development-log.md#milestone-5-packaging)).
- 2026-10-14: `theme.install(app)` after `setStyle("Fusion")` ([dev log](../../../04-development-log.md#dark-mode-buttons)).
