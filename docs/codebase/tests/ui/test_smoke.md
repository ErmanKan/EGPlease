# `tests/ui/test_smoke.py`

> Proves that Qt loads and renders headlessly in this environment, and that a failed startup self-test stops the app with a plain message.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** pytest.
- **Uses:** PySide6; `gif_editor.app` and `core/selftest.py` (second test).

## Public API
| Test | Verifies |
|---|---|
| `test_qt_renders_offscreen` | A `QLabel` can be shown, exposed and grabbed into a non-empty image on the `offscreen` platform. |
| `test_failed_selftest_explains_and_exits` (M4) | With `selftest.run_selftest` replaced by a function that raises `SelfTestError("gif decoder args changed")` and `QMessageBox.exec` stubbed, `app.main(["gif-editor"])` returns **1** and shows exactly one dialog: its text contains "can't start", its informative text "Download it again", and its detailed text the original error. |
| `test_edit_spec_without_arguments_is_a_usage_error` (M5) | `app.main(["gif-editor", "--edit-spec"])` returns **2** and prints usage; the branch runs before any Qt import. |
| `test_edit_spec_branch_runs_headless` (M5) | `app.main` with `--edit-spec IN SPEC` writes the output and prints a `RESULT` line (exit 0): the path the packaged binary is checked with. |
| `test_smoke_gui_opens_the_file_and_quits` (M5) | `--smoke-gui FILE` shows the real window, loads a 5-frame 20x10 GIF, prints `GUI OK opened 5 frames 20x10` and returns 0 by itself. |
| `test_smoke_gui_reports_a_failed_open` (M5) | `--smoke-gui` on a missing file returns 1 with a `GUI FAIL` line. |
| `test_smoke_gui_fails_fast_on_a_broken_selftest` (M5) | Under `--smoke-gui` a failing self-test prints `GUI FAIL startup self-test: ...` and returns 1 without showing a dialog (`QMessageBox.exec` is patched to fail the test if called). |

## How it works
`qtbot.addWidget` registers the widget for cleanup, and `qtbot.waitExposed` waits until Qt considers it visible. `grab()` renders it to a pixmap.

The self-test test patches `selftest.run_selftest` (the module attribute): `app.main` imports `run_selftest` **inside** the function, so the patched attribute is what it picks up. `fake_exec` records `(text, informativeText, detailedText)` instead of blocking.

## Invariants & gotchas
- If `test_qt_renders_offscreen` fails, every other UI test will fail too. The usual cause is a missing `libEGL.so.1` (run through `scripts/test.sh`) or a missing `QT_QPA_PLATFORM=offscreen`.
- The self-test case lives here (not in `test_main_window.py`) because it tests the start-up path before any window exists.

## Tests
- **Gaps:** n/a.

## History
- M5 (orchestrator, after the M5 docs pass): five tests for `app.main`'s `--edit-spec` and `--smoke-gui` branches.
- `cc9f0fa`: added with the project-local libEGL.
- `39e533b` (M4): `test_failed_selftest_explains_and_exits`.
