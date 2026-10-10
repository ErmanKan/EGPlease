# `tests/ui/test_transport.py`

> Tests for `TransportBar`: label text, play button state, button wiring, preview check box binding, the save signal and the disabled empty state.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest.
- **Uses:** `ui/inspector/transport.py`, `ui/inspector/player.py`, `ui/document.py`, fixture `doc` (8 frames × 100 ms).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `make(doc, qtbot)` | helper | Builds a `Player` (`time_scale=0.2`) and a `TransportBar`, registers the bar with `qtbot` so it is cleaned up. |
| `test_*` | tests | See below. |

## How it works
- `test_format_frame_info`: the pure text formatter, including the spec example `Frame 37 / 120 · 1.48 s · 40 ms` and the ` · deleted` suffix.
- `test_label_follows_current_index_and_deletion`: label after `set_current_index(3)` shows frame 4 at 0.30 s; deleting adds the suffix, undo removes it (via `stateChanged`).
- `test_play_button_reflects_playing` / `test_play_button_unchecks_on_empty_plan`: the checked state follows `player.is_playing`, both for clicks (`qtbot.mouseClick`) and programmatic play/pause, and a refused play leaves the button unchecked.
- `test_buttons_move_frames`: next, prev (wrapping to the last frame), first, last.
- `test_preview_checkbox_bound_both_ways`, `test_save_frame_requested` (`qtbot.waitSignal`), `test_tooltips_name_shortcuts`.
- `test_disabled_without_source`, `test_close_disables_and_resets`: an empty `Document` disables the bar and all children; closing while playing stops playback and un-checks the button.

## Invariants & gotchas
- `qtbot.mouseClick` works on hidden widgets in the offscreen platform, so the bar is never shown.
- Icons aren't compared (style-dependent); the checked state is the observable.

## Tests
- 10 tests; run with `scripts/test.sh tests/ui/test_transport.py`.

## History
- Milestone 2: created together with `transport.py`.
