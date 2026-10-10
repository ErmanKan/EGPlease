# `src/gif_editor/ui/inspector/__init__.py`

> Package marker for the right-hand frame inspector widgets. Its docstring is the only content: "Right-hand frame inspector widgets."

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** imports of `gif_editor.ui.inspector.*`.
- **Uses:** nothing.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| (none) | | Import from the submodules. |

## How it works
An empty package. Its modules (Milestone 2, all implemented):

| Module | Status | Role |
|---|---|---|
| [`canvas.py`](canvas.md) | implemented | `FrameCanvas`: zoomable frame view (Fit / 100 %) on a checkerboard, deleted overlay; the crop rectangle comes in M3 |
| [`timebar.py`](timebar.md) | implemented | `TimeBar`: playhead, frame ticks, green/red trim handles |
| [`filmstrip.py`](filmstrip.md) | implemented | `Filmstrip`: thumbnail strip, multi-selection, deleted frames struck through, trim menu |
| [`transport.py`](transport.md) | implemented | `TransportBar`: play/pause, step, first/last buttons, Preview edits, frame info, Save frame (shortcuts live in the main window) |
| [`player.py`](player.md) | implemented | `Player`: playback timer that advances `Document.current_index` |
| [`inspector.py`](inspector.md) | implemented | `Inspector`: composes the widgets above into the right panel |

See [`docs/03-architecture.md`](../../../../../03-architecture.md#9-m2-ui-structure) for how they connect to `Document`.

## Invariants & gotchas
- Widget rules (AGENTS.md): construct with `(doc, parent=None)`; talk only to `Document`; refresh on `sourceChanged`; show an empty or disabled state when nothing is open; never block the GUI thread for more than about 16 ms.

## Tests
- None directly.

## History
- `7a7b418`: scaffold.
