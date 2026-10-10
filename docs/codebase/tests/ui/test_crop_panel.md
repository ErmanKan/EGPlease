# `tests/ui/test_crop_panel.py`

> pytest-qt tests for `CropPanel`: spinbox ↔ `CropRect` mapping and clamping, the aspect lock, the Full image / Center / Reset buttons, the checkbox, two-way sync with the canvas rectangle, undo merging and the disabled empty state.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest.
- **Uses:** `src/gif_editor/ui/crop_panel.py`, `ui/document.py`, `core/models.py` (`CropRect`, `EditState`), `core/render.output_dimensions`; fixtures `doc` and `gif_path` from `tests/ui/conftest.py` (**8 solid frames, 40×30, 100 ms each → 0.80 s**). The canvas-crossing test doubles the same way `tests/ui/test_crop_item.py` would, by applying `CropRect` directly through `doc.apply`.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `panel` | fixture | A `CropPanel(doc)` shown and registered with `qtbot` for cleanup. |
| `test_*` | tests | See below. |

## How it works
Tests drive the real child widgets (`setValue`, `click`, `setChecked`, `activated.emit`) exactly as user input would — `setValue` emits `valueChanged` just like typing + Enter — then assert on `doc.state.crop`, `doc.undo_stack` and the widgets. Canvas drags are simulated by calling `doc.apply(doc.state.with_(crop=...), "Crop", merge_key="crop")` on the shared `Document`, which is exactly what `CropItem` does; this is the two-way-sync seam. The fixture canvas is 40×30 (so X,Y range `0…39` / `0…29`, W `1…40`, H `1…30`).

### Behaviour checklist (≥ 12, each individually testable)
1. `test_initial_values_no_crop` — fresh `doc`: `crop_group` unchecked, `state.crop is None`, spinboxes show the full canvas (X=0, Y=0, W=40, H=30), combo on `Free`, status `"No crop (full frame 40×30)"`.
2. `test_ranges_follow_canvas` — X `0…39`, Y `0…29`, W `1…40`, H `1…30`; X/Y/W/H suffixes and accessible names set.
3. `test_aspect_entries_and_original` — `ASPECTS` labels and `itemData` exactly as specified; entry 1 `Original` has `itemData == 40 / 30` after `sourceChanged` (and `None` with no source).
4. `test_x_y_edits_write_crop` — set X=10, Y=7 with W=20/H=15 → `state.crop == CropRect(10, 7, 20, 15)`; each edit is one `apply` with merge key `"crop"`.
5. `test_w_edit_clamps_keeping_width` — X=10, W=40 → `state.crop.x == 0` (shifted) and `w == 40` (W not shrunk); `x + w == 40`.
6. `test_h_edit_clamps_keeping_height` — Y=10, H=30 → `state.crop.y == 0` and `h == 30`; `y + h == 30`.
7. `test_y_edit_clamped_to_bottom` — with H=30, set Y=5 → `y == 0`.
8. `test_spinbox_scrub_is_one_undo_step` — four W edits in a row (merge key `"crop"`) → one `SetStateCommand`.
9. `test_button_is_its_own_undo_step` — a scrub then `full_button.click()` → two commands (button passes `None`).
10. `test_undo_redo_refresh_without_new_commands` — set a crop, undo → controls back to full frame and the stack still has its command at index 0 (no feedback loop); redo restores the crop.
11. `test_canvas_drag_syncs_panel` — `doc.apply(...crop=CropRect(...)...)` → spinboxes and status update; blocked signals so no extra command is pushed.
12. `test_aspect_w_edit_updates_h` / `test_aspect_h_edit_updates_w` — with `4:3` locked, W=20 → H=`round(20 / (4/3)) == 15`; and H=12 → W=16. With `1:1`, W=25 → H=25. `9:16` locked, W=9 → H=16.
13. `test_aspect_rounds_to_nearest_and_min_1` — a ratio that does not divide evenly rounds to the nearest int (e.g. `16:9`, W=16 → H=`round(9) == 9`; W=7 → H=`round(7*9/16) == 4`); a value that would round to 0 is clamped to `1`.
14. `test_aspect_not_reapplied_on_drag` — lock `1:1`, then apply a non-square `CropRect` via `doc.apply` (as a drag would) → the panel shows the raw W/H and does **not** square it; the combo stays on `1:1` (UI-only selection).
15. `test_full_image_button_stores_none` — set a crop, click `full_button` → `state.crop is None`, checkbox unchecked, combo unchanged, status `"No crop (full frame 40×30)"`.
16. `test_center_uses_current_crop_size` — set `CropRect(5, 5, 20, 15)`, click `center_button` → `CropRect(10, 7, 20, 15)` (centred 20×15).
17. `test_center_without_crop_uses_output_size` — no crop, `size=OutputSize(20, 20)` → `CropRect(10, 5, 20, 20)`.
18. `test_reset_clears_crop_and_combo` — set a crop and a non-Free aspect, click `reset_button` → `crop is None`, combo back to `Free`, status `"No crop"`.
19. `test_checkbox_uncheck_clears` — set a crop, `crop_group.setChecked(False)` → `crop is None`.
20. `test_checkbox_check_applies_centered_default` — no crop, `crop_group.setChecked(True)` → a centred crop sized from the output size (canvas 40×30 with `size=None` → `CropRect(0, 0, 40, 30)`… which normalises to `None`; use `size=OutputSize(20, 20)` to see `CropRect(10, 5, 20, 20)`).
21. `test_status_line_formats` — `CropRect(10, 7, 20, 15)` → `"Crop 20×15 at 10,7 · 25% of the frame"` (uses `crop_panel.TIMES`); no crop → `"No crop (full frame 40×30)"`; closed doc → `"No crop"`.
22. `test_disabled_without_source` — a `Document()` with no source: group unchecked + disabled, every control disabled, and a forced `x_spin.setValue(5)` pushes nothing.
23. `test_closed_document_disables` — after `doc.close()` the group is disabled, unchecked and the status is `"No crop"`.
24. `test_invalid_crop_reports_error` — a `ValueError` from `apply` (build one by applying a stray `CropRect` past the canvas through a fault-injected `Document`, or a valid-but-invalid `EditState`) is caught: `last_error` holds the message, `errorOccurred` fired once with it, controls reverted to `doc.state`, and the next accepted edit clears `last_error`.
25. `test_edit_does_not_change_explicit_size` — with `size=OutputSize(100, 100)` set, changing the crop leaves `state.size` unchanged.

## Invariants & gotchas
- Must run with `QT_QPA_PLATFORM=offscreen` and the project-local libEGL (`scripts/test.sh`).
- Expected strings contain `×` via `crop_panel.TIMES` to keep ruff's ambiguous-character rule quiet.
- The `doc` fixture canvas is 40×30; every range/`CropRect` above assumes it. A full-canvas result normalises to `crop=None`, so tests that want to observe a value must pick a crop smaller than 40×30.
- `setKeyboardTracking(False)` means a test that sets a spinbox value sees the edit immediately via `setValue` (which emits `valueChanged`), but a test for the *in-progress text* guard must use `lineEdit().setText(...)` + `lineEdit().setModified(True)` and then trigger a refresh, asserting the value was not clobbered.

## Tests
- This file is the test. Gaps: no pixel/visual check of the layout, the collapse/expand rendering or the disabled-grey look; no test of the combo dropdown styling; HiDPI is deferred to M4 (its own pass).

## History
- Written as the **Milestone 3 specification by a docs worker** (docs only). The orchestrator creates `tests/ui/test_crop_panel.py` and the `CropPanel` widget from this checklist.