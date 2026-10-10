# `tests/ui/test_timebar.py`

> pytest-qt tests for the `TimeBar` timeline widget: coordinate mapping, seeking, trim-handle drags (snapping, Alt, undo merging, constraints), keyboard, painting and performance.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest.
- **Uses:** `src/gif_editor/ui/inspector/timebar.py`, `ui/document.py`, `core/decoder.py`, `tests/gifgen.py`, and the fixtures `doc` / `gif_path` from `tests/ui/conftest.py` (8 frames × 100 ms = 800 ms).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `bar` | fixture | A shown `TimeBar(doc)` resized to 800×56. With `MARGIN = 8`, 1 ms ≈ 0.98 px and x=400 is exactly t=400 ms. |
| `pt(bar, ms)` | helper | Integer `QPoint` on the track for a time in ms. |
| `drag(qtbot, bar, start, end)` | helper | Press, move, release with the left button. |
| `alt_move(bar, pos)` | helper | Sends a `MouseMove` `QMouseEvent` with `AltModifier`. Needed because `qtbot.mouseMove` has no modifier argument. |
| `test_*` | tests | See below. |

## How it works
Every test drives the real widget through Qt's event system (`qtbot.mousePress/mouseMove/mouseRelease/keyClick`) and then asserts on the **document**, not on pixels. The widget's contract is "it changes the Document correctly", so that is what gets checked:

- `test_mapping_round_trip`: `time_for_x(x_for_time(t)) == t`, plus clamping outside the track.
- `test_click_at_half_seeks_to_frame_4`: a click at x=400 (t=400 ms) selects frame 4, emits `scrubbed(4)` and leaves nothing on the undo stack.
- `test_drag_seeks_continuously`: dragging on the track keeps seeking.
- `test_handle_at`: hit-testing for the default and a custom trim.
- `test_in_handle_snaps_to_frame_boundary`: dragging the in handle to about 250 ms gives a multiple of 100 ms (200 or 300).
- `test_alt_drag_is_free`: the same drag with Alt gives a non-boundary value within 2 ms of 250.
- `test_one_drag_is_one_undo_step`: many moves in one drag make 1 undo step, and a second drag makes 2. Undo restores each step.
- `test_in_drag_keeps_out_fixed`: moving the in point keeps the out point's absolute time.
- `test_out_handle_back_to_end_is_none`: the out handle back at (or Alt-dragged past) the end gives `trim_duration_ms is None`.
- `test_in_less_than_out_enforced`: snapped and free drags both respect in < out and the 10 ms minimum window, from either side.
- `test_cursor_and_tooltip`: the hover cursors and the tooltip text.
- `test_keyboard`: Left/Right/Home/End and Shift ±10, with clamping.
- `test_paints_at_extreme_widths`: `grab()` at widths 50 and 3000 with deletions, trim and focus.
- `test_large_gif_paint_is_fast`: a 1000-frame GIF with 500 deleted runs paints in < 30 ms. The best of 3 grabs is used, after a warm-up grab, to reduce CI noise.
- `test_no_source_no_crash` / `test_source_changes_refresh`: the disabled state, then enabling and disabling on open/close.

## Invariants & gotchas
- Run via `scripts/test.sh` (offscreen platform plus the project-local libEGL).
- Pixel positions are rounded to ints, so snapped assertions use boundaries, and free ones use a ±2 ms tolerance.
- The timing test measures `QWidget.grab()`, which includes a little overhead beyond `paintEvent`, so the budget check is conservative.

## Tests
This file *is* the tests. Not covered: the actual tooltip popup and the focus-rect pixels.

## History
- Milestone 2: created together with `timebar.py`.
