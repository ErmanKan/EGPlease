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

## How it works
`qtbot.addWidget` registers the widget for cleanup, and `qtbot.waitExposed` waits until Qt considers it visible. `grab()` renders it to a pixmap.

The self-test test patches `selftest.run_selftest` (the module attribute): `app.main` imports `run_selftest` **inside** the function, so the patched attribute is what it picks up. `fake_exec` records `(text, informativeText, detailedText)` instead of blocking.

## Invariants & gotchas
- If `test_qt_renders_offscreen` fails, every other UI test will fail too. The usual cause is a missing `libEGL.so.1` (run through `scripts/test.sh`) or a missing `QT_QPA_PLATFORM=offscreen`.
- The self-test case lives here (not in `test_main_window.py`) because it tests the start-up path before any window exists.

## Tests
- **Gaps:** n/a.

## History
- `cc9f0fa`: added with the project-local libEGL.
- `39e533b` (M4): `test_failed_selftest_explains_and_exits`.
