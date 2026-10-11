# `tests/ui/test_canvas.py`

> pytest-qt tests for `FrameCanvas`: frame display, zoom API, overlays, empty state, coordinate mapping, and (M4) expensive frames decoded off the GUI thread.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest
- **Uses:** `src/gif_editor/ui/inspector/canvas.py`, `src/gif_editor/ui/document.py`, `tests/ui/conftest.py` (fixtures `doc`, `gif_path`: 8 solid-colour 40×30 frames), `tests/gifgen.py` (`PALETTE`, the frame colours)

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `canvas` | fixture | A shown 400×300 `FrameCanvas` on the `doc` fixture (waits until exposed so the viewport has a real size). |
| `_pixel(canvas, x, y)` | helper | RGB of a pixel in `image_item.pixmap()`. |
| `_close(a, b, tol)` | helper | Colour comparison with a small tolerance (GIF palette rounding). |
| `test_*` | tests | See below. |

## How it works
Each test builds a real widget offscreen (`QT_QPA_PLATFORM=offscreen`) and drives it either through its public API or with synthetic input events:
- **Frame display:** sample the pixmap after `doc.set_current_index(3)` and compare with `PALETTE[3]`.
- **Fit:** after `zoom_fit()`, the image's on-screen bounding rect (`mapFromScene(image_rect())`) must lie inside the viewport and fill it up to the margin in at least one dimension. A resize must re-fit only while in fit mode.
- **Zoom API:** clamping to `MIN_ZOOM`/`MAX_ZOOM`, the 1.25 step, the `zoomChanged` payload, `fit_mode` flipping, and `transformationMode` (Smooth below 1, Fast at 1 and above).
- **Deleted overlay:** `doc.delete_frames([0])` sets `deleted_overlay_visible`; `grab()` forces a paint so `drawForeground` runs; undo clears the overlay.
- **Empty/closed:** a fresh `Document()` shows the placeholder and survives painting and zoom calls; `doc.close()` clears the pixmap.
- **Mapping:** at zoom 1 and 2, a viewport offset of (20, 10) from the image origin maps to (20/z, 10/z). The tolerance is half a pixel because `mapFromScene` rounds to integers. A float round trip through `viewportTransform()` must be exact.
- **Async source frames (M4):** `test_expensive_source_frame_renders_off_thread` opens a 40-frame 32×32 GIF with `Limits(cache_budget_bytes=0)` (nothing cached), attaches a real `PreviewService`, and monkeypatches `SYNC_DECODE_PIXELS` to `32 × 32 × 3` (more than 3 frames of work is "expensive"). It wraps `doc.source.frame` to record the thread of each call. Jumping to frame 30 sets `_awaiting_source = 30`; once it clears, every decode happened on a pool thread and the pixmap has `PALETTE[30 % len]`. Stepping on to frame 31 (cost 1) is decoded synchronously on the GUI thread.
- **Input:** a hand-built `QWheelEvent` with/without Ctrl; Space key press/release and middle press/release toggle `ScrollHandDrag`; a real middle-drag at 16× moves the horizontal scrollbar.

## Invariants & gotchas
- Tests that depend on geometry need the widget shown and exposed (`qtbot.waitExposed`); before that the viewport size is meaningless and `zoom_fit()` defers.
- Colours are compared with a tolerance; Pillow's GIF palette may shift values slightly.

## Tests
- This file is the test (16 cases). It also runs at 150 % and 200 % via `scripts/test-hidpi.sh`. Space+drag *inside the main window* (where the window's Space shortcut competes) is tested in `test_main_window.py`.
- Gaps: pixel-exact checks of the painted overlay, badge and checkerboard; a failed background render (`frameFailed`) while awaiting a source frame.

## History
- M2: created together with `canvas.py`.
- `5c40830` (M4): `test_expensive_source_frame_renders_off_thread`.
