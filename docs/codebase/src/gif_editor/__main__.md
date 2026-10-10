# `src/gif_editor/__main__.py`

> Makes `python -m gif_editor` start the app.

## Where it sits
- **Layer:** tooling / entry point
- **Used by:** `PYTHONPATH=src python -m gif_editor`. Planned: Nuitka's onefile build (M5).
- **Uses:** `gif_editor/app.py` (`main`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| (module) | script | `raise SystemExit(main())`: runs the Qt event loop and exits with its return code. |

## How it works
The file imports `main` and exits with its return value. Using `SystemExit` instead of `sys.exit` avoids importing `sys` here; the effect is the same.

## Invariants & gotchas
- Importing this module **runs the app**. Never import it from tests.

## Tests
- None (the module would start an event loop).

## History
- `7a7b418`: scaffold.
