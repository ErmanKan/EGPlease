# `tests/ui/test_player.py`

> Tests for the playback engine `Player`: what it plays, in which order, and that its timing logic stays on the ideal timeline.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest.
- **Uses:** `ui/inspector/player.py`, `ui/document.py`, fixtures `doc` and `gif_path` from `tests/ui/conftest.py` (8 solid frames, 40×30, 100 ms each).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `record(doc)` | helper | Connects a list to `currentIndexChanged` and returns it (the visited frames). |
| `assert_forward(seen, order)` | helper | Asserts every visit moves 1–3 positions forward in `order`, cyclically. |
| `test_*` | tests | See below. |

## How it works
Two kinds of tests:

1. **Real-timer tests** (`time_scale=0.2`, so each 100 ms frame lasts 20 ms). They start playback, then `qtbot.waitUntil(...)` runs the Qt event loop until enough frames were visited. Order is checked with `assert_forward`: normally each step is +1, but a slow CI machine can make the player *skip* a frame (that is the intended catch-up behaviour), so small forward jumps are allowed; going backwards or repeating is not. These cover looping, preview-mode order (`plan.src_indices`) and that deleted frames are never visited, and that `pause()` stops advancing.
2. **Fake-clock tests.** `Player(doc, clock=lambda: t[0])` reads time from a list we control, and the tests call the timeout slot `_on_timeout()` directly. This makes drift behaviour deterministic: being 2.5 frames late lands on frame 3, the next on-time tick is frame 4 (no accumulated lag), an early wake-up does nothing, and a 100-second stall rebases instead of fast-forwarding through loops. The real `QTimer` is still armed in these tests, but the event loop never runs, so it never fires.

Other tests are plain method calls: `toggle()` signals, empty plan (trim start beyond the end) refusing to play and emitting `playingChanged(False)`, `doc.close()` stopping playback, `step()` wrapping and skipping deleted frames, starting from a deleted frame, resync when the current frame is deleted while previewing, continuing after an external `set_current_index`, `stop()`, `go_first/go_last`, `previewEditsChanged` firing once per change, and preview durations reflecting speed.

## Invariants & gotchas
- Do not compare exact visit lists from real-timer tests; scheduling jitter makes them flaky. Use `assert_forward` and set membership.
- Testing `_on_timeout` directly is intentional white-box testing of the drift logic.

## Tests
- 22 tests; run with `scripts/test.sh tests/ui/test_player.py`.

## History
- Milestone 2: created together with `player.py`.
