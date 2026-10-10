# `tests/ui/test_canvas.py`

> pytest-qt tests for `FrameCanvas`: frame display, zoom API, overlays, empty state and coordinate mapping.

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
- **Input:** a hand-built `QWheelEvent` with/without Ctrl; Space key press/release and middle press/release toggle `ScrollHandDrag`; a real middle-drag at 16× moves the horizontal scrollbar.

## Invariants & gotchas
- Tests that depend on geometry need the widget shown and exposed (`qtbot.waitExposed`); before that the viewport size is meaningless and `zoom_fit()` defers.
- Colours are compared with a tolerance; Pillow's GIF palette may shift values slightly.

## Tests
- This file is the test. Gaps: pixel-exact checks of the painted overlay, badge and checkerboard; HiDPI device-pixel ratios.

## History
- M2: created together with `canvas.py`.
