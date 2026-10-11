# `tests/ui/test_m3_integration.py`

> Integration tests for the Milestone 3 wiring: geometry preview on the canvas, the size estimate and the crop panel inside the settings panel, and the main window's crop tool, Crop menu actions and "Preview edits".

## Where it sits
- **Layer:** tests (Qt, pytest-qt)
- **Used by:** pytest (via `scripts/test.sh`, or with `QT_QPA_PLATFORM=offscreen` on Windows/CI).
- **Uses:** `ui/inspector/canvas.py` (`FrameCanvas`), `ui/inspector/preview.py` (`PreviewService`), `ui/settings_panel.py` (`SettingsPanel`, `format_bytes`), `ui/main_window.py` (`MainWindow`), `core/models.py` (`CropRect`, `OutputSize`), `tests/gifgen.py` (`PALETTE`, `make_gif`, `solid_frames`); fixtures `doc` and `gif_path` from [`tests/ui/conftest.py`](conftest.md) (8 solid-colour frames, 40×30, 100 ms; frame *i* is `PALETTE[i]`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `preview` | fixture | `PreviewService(doc, debounce_ms=10)`; `dispose()`d in teardown. The short debounce keeps the estimate tests fast. |
| `win` | fixture | A shown `MainWindow()` (1100×700), exposed, with `gif_path` opened and idle. Teardown calls `w.preview.dispose()`. |
| `_px(canvas)` | helper | `((width, height), (r, g, b) of pixel 0,0)` of the pixmap the canvas currently shows. Size tells "source frame vs output frame"; colour tells which source frame it is. |

| Test | Verifies |
|---|---|
| **Canvas** | |
| `test_canvas_geometry_preview_shows_output_frame` | With crop (5,5,20,10) + size 10×5: geometry off shows the 40×30 source frame; on shows a 10×5 frame, `geometry_preview` is True, `image_rect()` is the **output** width (10), colour `PALETTE[3]`; moving to frame 5 follows the playhead; turning it off shows the 40×30 source frame again **immediately** (no wait). |
| `test_canvas_geometry_follows_crop_edits` | In geometry mode, a crop to 12×8 re-renders the shown frame; undo returns to 40×30. |
| **Settings panel** | |
| `test_format_bytes` | `850 → "850 B"`, `12 700 → "12.4 KB"`, `3 365 000 → "3.21 MB"` (1 KB = 1024 B). |
| `test_summary_shows_size_estimate` | With a service, the summary card gets a `Size: ≈ …` line once the estimate arrives. |
| `test_summary_without_preview_has_no_size_line` | Without `preview=`, there is no Size line at all. |
| `test_crop_panel_is_part_of_settings` | Ticking `panel.crop_panel.crop_group` creates a crop, and the summary shows the crop size as the output size (size follows the crop). |
| `test_crop_error_surfaces_in_summary` | `crop_panel.errorOccurred("…")` appears in the summary card. |
| **Main window** | |
| `test_crop_tool_starts_off_and_activates_a_box` | After open the tool is off and the rectangle hidden. Triggering **C** shows it and creates the 10% inset box `CropRect(4, 3, 32, 24)` as exactly one undo step. |
| `test_crop_from_panel_turns_the_tool_on` | Ticking the panel's Crop group checks the crop tool action and shows the rectangle. |
| `test_drag_on_canvas_crops_in_one_undo_step` | A **real mouse drag** on the canvas viewport at zoom 8: three moves of 8 view px leave `doc.state.crop` untouched mid-drag; release after 24 view px moves the crop by 3 image px; the undo stack grows by exactly one; the panel's X spin shows 7; undo restores. |
| `test_nudge_and_resize_shortcuts` | `act_crop_nudge[1]` (Ctrl+Right) and `act_crop_resize[1]` (Ctrl+Shift+Right) give x 5, w 33, as two separate undo steps. |
| `test_crop_tool_hidden_during_output_preview` | The rectangle hides while **P** is on and comes back when it is off. |
| `test_crop_edit_actions_follow_visibility` | Ctrl+arrow nudge/resize actions are enabled only while the rectangle is shown (off before the tool, on with it, off during "Preview edits"). |
| `test_remove_crop_works_with_tool_off` | A crop set from the panel can be removed with "Remove crop" after hiding the rectangle. |
| `test_remove_crop_works_during_preview` | "Remove crop" works while "Preview edits" hides the rectangle. |
| `test_remove_crop_and_new_file_resets_tool` | "Remove crop" clears the crop; opening another file turns the tool off and hides the rectangle. |
| `test_generate_applies_canvas_crop` | Generate after **C** writes a 32×24 GIF: the canvas crop reaches the output. |
| `test_preview_edits_toggles_geometry` | P turns on both `player.preview_edits` and `preview.geometry_enabled`; the canvas shows the 16×12 cropped frame; P again turns geometry off and the 40×30 frame is back at once; an estimate is available. |

15 collected cases.

## How it works
- **Pixels prove what is shown.** The fixture GIF has a solid colour per frame, so `_px` can tell from one pixel which source frame is on screen and from the pixmap size whether it is the source or the cropped/resized output.
- **Asynchronous results are awaited** with `qtbot.waitUntil(...)`: preview frames are rendered on the thread pool and the estimate is debounced, then computed on the pool. Turning geometry **off** is synchronous (the canvas re-reads the source frame itself), which is why those assertions do not wait.
- **The drag test uses real input events** (`qtbot.mousePress/mouseMove/mouseRelease` on the canvas viewport), so it covers the whole chain: view → scene → `CropItem` hit test → live rectangle → one `Document.apply` on release → `stateChanged` → `CropPanel` refresh. The zoom is set to 8 and the view centred on the image so a whole number of view pixels maps to whole image pixels.
- **The undo-stack count** is used to check the merge-key rules: activate = 1 step, one drag = 1 step, each nudge/resize = 1 step.

## Invariants & gotchas
- Every `PreviewService` created here is `dispose()`d, so no debounce timer or worker callback outlives the test (see the [deleteLater trap](../../../06-testing.md#the-deletelater-teardown-trap)). `test_preview_edits_toggles_geometry` builds its own window and disposes its service itself.
- `CropRect(4, 3, 32, 24)` depends on the fixture size: 10% of 40×30 is 4×3 on each side.
- The nudge/resize test turns the tool on first. `test_crop_edit_actions_follow_visibility` checks that the nudge/resize actions are disabled whenever the rectangle is hidden, and the two `test_remove_crop_works_*` tests check that "Remove crop" works with the tool off and during "Preview edits" (both were bugs found by the M3 docs pass).

## Tests
- This file is the test. During M3 verification it was run 3× in a row with no flakes.
- **Gaps:** the status-bar text while dragging; the "Remove crop" / nudge actions with the tool off; the real **P** and **C** key presses (actions are triggered directly); pixel-exact comparison of the preview frame with the Generate output frame.

## History
- `3adb5bd` (M3): canvas, settings-panel and "Preview edits" tests, written with the wiring.
- `484382d` (M3): crop tool, Crop menu, drag, hide-during-preview and Generate tests, written with the crop tool.
