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
An empty package. Its modules (all implemented as of Milestone 2):

| Module | Status | Role |
|---|---|---|
| [`document`](document.md) | implemented | `Document` hub: source, state, undo, current frame, selection |
| [`commands`](commands.md) | implemented | `SetStateCommand` with gesture merging |
| [`workers`](workers.md) | implemented | `run_async` thread-pool helper |
| [`qt_image`](qt_image.md) | implemented | PIL → QImage, checkerboard brush |
| [`settings_panel`](settings_panel.md) | implemented | left panel: timing, size, quality, live summary, Generate button |
| [`inspector/`](inspector/__init__.md) | implemented | right panel: canvas, transport, timebar, filmstrip; the `Player` |
| [`main_window`](main_window.md) | implemented | window, menus, shortcuts, file open, Generate, Save frame |

## Invariants & gotchas
- UI code may import `core`; `core` must never import `ui`.

## Tests
- None directly.

## History
- `7a7b418`: scaffold.
