# `src/gif_editor/core/models.py`

> The immutable edit model. `EditState` holds every user edit and is the single source of truth for them.

## Where it sits
- **Layer:** core (pure Python, stdlib only)
- **Used by:** `core/timeline.py`, `core/render.py` (`CropRect`, `OutputSize`, `Quality`), `core/pipeline.py`, `ui/document.py`, `ui/commands.py`, every M2/M3 widget that edits settings.
- **Uses:** nothing in the project.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `MAX_FPS = 50.0`, `MIN_SPEED = 0.25`, `MAX_SPEED = 4.0` | constants | Field ranges. 50 fps is the real GIF maximum (2 cs delays; see the [primer](../../../../05-gif-primer.md#delays-centiseconds-and-browser-clamping)). |
| `CropRect(x, y, w, h)` | frozen dataclass | Crop rectangle in **source-canvas pixels**. `.validate(canvas_w, canvas_h)`: positive size, origin ≥ 0, inside the canvas. |
| `OutputSize(width, height)` | frozen dataclass | Final output size after the crop. `.validate()`: each side 1..8192. |
| `Quality(colors=256, dither=True)` | frozen dataclass | Palette size 2..256 and Floyd–Steinberg on/off. `Quality.preset("high"\|"medium"\|"low")` → (256, on) / (128, on) / (64, off). |
| `EditState(trim_start_ms=0, trim_duration_ms=None, deleted=frozenset(), crop=None, speed=1.0, fps=None, size=None, quality=Quality())` | frozen dataclass | The whole edit. Defaults mean "no change". |
| `EditState.with_(**changes)` | method | Copy with changes applied. Rejects unknown fields (`TypeError`), coerces `deleted` to `frozenset`, validates field ranges (`ValueError`). |
| `EditState.validate(canvas_w, canvas_h, frame_count)` | method | Full validation against a loaded source: field ranges, crop inside the canvas, deleted indices < `frame_count`. |

Field meanings:
| Field | Meaning |
|---|---|
| `trim_start_ms` | Start of the kept window in **source** time (≥ 0). |
| `trim_duration_ms` | Length of the window from the start (> 0) or `None` = to the end. Gate 1 decision: *Duration* is the trim length, not a target output length. |
| `deleted` | Source frame indices to drop (their time is dropped too). |
| `crop` | One rectangle for all frames, or `None`. |
| `speed` | 0.25..4.0, divides every delay. |
| `fps` | `None` = keep source timing, else an FPS cap in (0, 50]. |
| `size` | `None` = crop size (or canvas size), else the explicit output size. |
| `quality` | Colours + dither. |

## How it works
- All classes are `@dataclass(frozen=True, slots=True)`, so instances are hashable and compare by value. `Document.apply` uses that to skip no-op edits (`new == self._state`). Undo commands store whole states instead of diffs. This is why **one** generic `SetStateCommand` can cover every kind of edit.
- Validation has two layers on purpose:
  - `with_` → `_validate_fields` checks what can be checked without a source, so a bad value fails at the widget that produced it;
  - `validate(w, h, n)` adds the source-dependent checks. `pipeline.plan` and `Document.apply` call it.

## Invariants & gotchas
- Never mutate: always `state.with_(...)`. `dataclasses.replace` would skip validation and the `frozenset` coercion.
- A crop is in source pixels, not widget or screen pixels. The canvas widget must map coordinates (HiDPI risk in the plan).
- `EditState()` constructed directly is **not** validated. `with_` is.
- `OutputSize` has no `keep_aspect` field, although the plan's T1 mentions one. Aspect locking is a UI concern.
- `Quality.PRESETS` is a `ClassVar`, so it is not a dataclass field.

## Tests
- `tests/core/test_models.py`: defaults are the identity; `with_` returns a new object and coerces `deleted`; 9 invalid field values; unknown fields; `validate` against the source; presets.
- **Gaps:** `CropRect.validate` messages; `OutputSize` upper bound (8193); `fps=50` boundary accepted.

## History
- `7a7b418`: written by the orchestrator in the scaffold, so parallel M1 workers had a fixed contract ([dev log, Phase 3](../../../../04-development-log.md#phase-3-scaffold-7a7b418)).
