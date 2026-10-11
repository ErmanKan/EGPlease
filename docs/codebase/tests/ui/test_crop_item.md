# `tests/ui/test_crop_item.py`

> pytest-qt tests for `CropItem`: mouse drags on a real `FrameCanvas`, the Document write contract, hit testing, discrete operations and painting.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest
- **Uses:** `src/gif_editor/ui/inspector/crop_item.py`, `src/gif_editor/ui/inspector/canvas.py`, `src/gif_editor/ui/document.py`, `src/gif_editor/core/models.py` (`CropRect`), `tests/ui/conftest.py` (fixture `doc`: 8 solid-colour 40×30 frames, frame 0 red)

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `canvas` | fixture | A shown, exposed 400×300 `FrameCanvas` at zoom 4 (the image is 160×120 on screen, so handles are well apart). |
| `item` | fixture | A `CropItem(doc)` added to `canvas.scene()`. |
| `press/move/release/drag(view, pt, mods)` | helpers | Send `QMouseEvent`s to the **viewport** at a float *scene* point (mapped with `viewportTransform()`), with optional keyboard modifiers (Shift). |
| `rect_tuple(item)`, `set_crop(doc, x, y, w, h)` | helpers | Read the shown rectangle; set a crop as one undo step. |
| `_brightness(canvas, scene_pt)` | helper | R+G+B of the grabbed canvas at a scene point. |
| `test_*` | tests | See below. |

## How it works
- **Why hand-built `QMouseEvent`s instead of `qtbot.mouseMove`?** `QTest` cannot attach keyboard modifiers to a move or pass sub-pixel positions. Shift-resize needs the modifier on every move, and float positions make the expected pixel offsets exact at any zoom. Events go to `canvas.viewport()`, as real input would, so the whole path view → scene → item (or handle child) → parent is exercised.
- **Drag contract:** mid-drag the test asserts `doc.state.crop` and `undo_stack.count()` are unchanged and `previewChanged` fired; after release, exactly one more command. Two drags give two commands; a drag followed by a `merge_key="crop"` edit gives two (no merge with the panel's spinbox key).
- **Geometry:** move, corner resize (opposite corner fixed), edge resize (one dimension), Shift aspect (within 1 px, also when clamped by the image), clamping far outside, the 8×8 minimum, full image → `crop=None`, and dragging the bottom-right handle by its part outside the image.
- **Hit testing:** `handle_at` for all 8 handles, `'move'` and `None`, at zoom 1 and 4. The same 5-image-px offset counts as an edge at zoom 1 and as the interior at zoom 4, proving the tolerance is in screen pixels. With no view, zoom 1 is assumed. Hover cursors are read from the viewport, which shows the cursor of the item (or handle child) under the pointer.
- **Document sync:** undo/redo moves the rectangle; `stateChanged` during a drag does not snap it back, and release re-reads the Document; `activate()`/`reset()` and `cropActiveChanged` (only on change); `nudge`/`resize` one step each and clamped; `set_tool_enabled(False)` hides it, blocks presses and edits, and abandons a running drag.
- **Paint:** `canvas.grab()` at 0.5, 1 and 4× with no crop, a crop and a running drag must not raise. After `activate()` a pixel outside the crop is clearly darker (< 70 % of the original sum), and a pixel inside is unchanged.

## Invariants & gotchas
- The canvas must be shown and exposed before mapping points: the viewport transform is meaningless until laid out.
- Sample points are chosen away from handles, border lines and the label (e.g. (38.5, 28.5) for the dimming check).
- The 40×30 fixture means `activate()` gives exactly `CropRect(4, 3, 32, 24)`.

## Tests
- This file is the test (35 cases incl. parametrisations). Gaps: no visual check of handle size or label legibility; no HiDPI device-pixel-ratio run.

## History
- M3: created together with `crop_item.py`.
