# `src/gif_editor/app.py`

> The application entry point. It creates the `QApplication` and, for now, shows a placeholder main window.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** `gif_editor/__main__.py`.
- **Uses:** PySide6 only. It does **not** use `ui/main_window.py` yet, because that file is planned and owned by the orchestrator.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `main(argv=None) -> int` | function | Create the `QApplication` (name "GIF Editor", Fusion style), show a 1100×700 `QMainWindow` with a placeholder label, and return `app.exec()`. |

## How it works
PySide6 is imported **inside** `main`. Importing `gif_editor.app` is therefore cheap and works without Qt libraries, which matters because the core tests must not need Qt.

The Fusion style is chosen so the widgets look the same on every Windows version and theme.

## Invariants & gotchas
- **Status: placeholder.** The module docstring says "The UI arrives in Milestone 2". The orchestrator will replace the label with the real `MainWindow`, and will probably add the planned `core.selftest.run_selftest()` startup check (its docstring says "the app calls it at startup", which is not true yet).
- `main()` blocks until the window closes. Do not call it from tests.

## Tests
- None directly. `tests/ui/test_smoke.py` proves Qt can render headlessly but does not call `main`.

## History
- `7a7b418`: scaffold placeholder.
