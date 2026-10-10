# `src/gif_editor/ui/__init__.py`

> Package marker for the PySide6 user interface. Its docstring is the only content: "PySide6 user interface."

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** every `gif_editor.ui.*` import.
- **Uses:** nothing (it imports no Qt itself).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| (none) | | Import from the submodules. |

## How it works
An empty package. The current and planned modules:

| Module | Status | Role |
|---|---|---|
| [`document`](document.md) | implemented | `Document` hub: source, state, undo, current frame, selection |
| [`commands`](commands.md) | implemented | `SetStateCommand` with gesture merging |
| [`workers`](workers.md) | implemented | `run_async` thread-pool helper |
| [`qt_image`](qt_image.md) | implemented | PIL → QImage, checkerboard brush |
| `settings_panel` | in progress (M2 worker) | left panel: output settings + summary |
| [`inspector/`](inspector/__init__.md) | in progress (M2 workers) | canvas, timebar, filmstrip, transport, player |
| `main_window` | planned (orchestrator) | window, menus, file open, Generate |

## Invariants & gotchas
- UI code may import `core`; `core` must never import `ui`.

## Tests
- None directly.

## History
- `7a7b418`: scaffold.
