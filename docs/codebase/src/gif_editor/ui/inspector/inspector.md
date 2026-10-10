# `src/gif_editor/ui/inspector/inspector.py`

> The right-hand frame inspector panel: stacks the canvas, the transport row, the timebar and the filmstrip vertically. Pure composition, no logic.

## Where it sits
- **Layer:** ui (Qt: `QWidget`, `QVBoxLayout`)
- **Used by:** `ui/main_window.py` (right side of the splitter); indirectly `tests/ui/test_main_window.py`.
- **Uses:** `ui/document.py` (`Document`), `ui/inspector/canvas.py` (`FrameCanvas`), `ui/inspector/transport.py` (`TransportBar`), `ui/inspector/timebar.py` (`TimeBar`), `ui/inspector/filmstrip.py` (`Filmstrip`), `ui/inspector/player.py` (`Player`, type only).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `Inspector(doc, player, parent=None)` | class (`QWidget`) | Builds the four children, all bound to the same `doc`; the transport also gets the `player`. |
| `.canvas` | `FrameCanvas` | Zoomable view of the current frame. |
| `.transport` | `TransportBar` | Play/step buttons, "Preview edits", frame info, "Save frame…". |
| `.timebar` | `TimeBar` | Source timeline, playhead and trim handles. |
| `.filmstrip` | `Filmstrip` | Thumbnails, selection, delete/restore. |

Signals: none. The children's own signals (`zoomChanged`, `saveFrameRequested`, `errorOccurred`, `scrubbed`) are reached through the public attributes.

## How it works
```
Inspector (QVBoxLayout, margins 0, spacing 4)
├─ canvas      stretch 1  ← all spare height goes here
├─ transport   natural height
├─ timebar     fixed 56 px
└─ filmstrip   fixed 140 px
```
- The constructor takes `player` rather than creating one: the `Player` must be shared between the transport buttons and the main window's keyboard actions, so the window owns it (see [main_window](../main_window.md#layout)).
- The children are **public attributes** so the main window can connect its actions to them (`canvas.zoom_fit`, `filmstrip.delete_selected`, `transport.saveFrameRequested`, …). This is the one place where something other than `Document` reaches into widgets, and it is the window doing the wiring, not the widgets calling each other.
- Every child connects to `Document` itself in its constructor. The inspector forwards nothing: open, edits and the playhead reach each child through `Document` signals.

## Invariants & gotchas
- Keep it logic-free. New inspector behaviour belongs in a child widget (talking to `Document`) or in the main window (actions, dialogs).
- The order in the layout is the visual order; only the canvas stretches, so the timebar and filmstrip keep their fixed heights when the window is resized.

## Tests
- No dedicated test file: it has no behaviour of its own. `tests/ui/test_main_window.py` builds it through `MainWindow` and uses its children (`inspector.canvas`, `inspector.filmstrip`, `inspector.transport`).

## History
- `be70f38`: written by the orchestrator when integrating the M2 widgets ([dev log, Milestone 2](../../../../../04-development-log.md#milestone-2-window-and-inspector)).
