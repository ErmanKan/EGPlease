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
An empty package. Its modules are being written in Milestone 2 by parallel workers; each one documents its own page:

| Module | Status | Planned role |
|---|---|---|
| `canvas.py` | in progress | zoomable frame view (Fit / 100 %) on a checkerboard; later the crop rectangle |
| `timebar.py` | in progress | playhead, frame ticks, green/red trim handles |
| `filmstrip.py` | in progress | thumbnail strip, multi-selection, deleted frames greyed out |
| `transport.py` | in progress | play/pause, step, first/last buttons + shortcuts |
| `player.py` | in progress | playback timer that advances `Document.current_index` |
| `inspector.py` | planned (orchestrator) | composes the widgets above into the right panel |

See [`docs/03-architecture.md`](../../../../../03-architecture.md#9-m2-widgets-in-progress) for how they connect to `Document`.

## Invariants & gotchas
- Widget rules (AGENTS.md): construct with `(doc, parent=None)`; talk only to `Document`; refresh on `sourceChanged`; show an empty or disabled state when nothing is open; never block the GUI thread for more than about 16 ms.

## Tests
- None directly.

## History
- `7a7b418`: scaffold.
