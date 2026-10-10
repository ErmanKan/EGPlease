# `tests/ui/test_document.py`

> pytest-qt tests for `Document`: open/reset, apply/undo/redo, gesture merging, delete/restore, current index, selection.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** pytest (via `scripts/test.sh` or with `QT_QPA_PLATFORM=offscreen`).
- **Uses:** `ui/document.py`, `core/models.py`, fixtures `doc`/`qtbot` (`tests/ui/conftest.py`, pytest-qt).

## Public API
| Test | Verifies |
|---|---|
| `test_open_resets_everything` | After `set_source`: open, 8 frames, default state, index 0, summary of 8 frames. |
| `test_apply_undo_redo` | `apply` emits `stateChanged` with the new state; undo/redo switch states. |
| `test_noop_apply_pushes_nothing` | Applying the current state adds no undo step. |
| `test_invalid_state_rejected` | An oversized crop → `ValueError` and no undo step. |
| `test_merge_key_collapses_gesture` | Three `set_trim` calls → one undo step, and undo returns to the original. |
| `test_gesture_back_to_start_is_dropped` | `set_trim(100)` then `set_trim(0)` → no undo step (obsolete command). |
| `test_delete_restore` | Delete {1,2} → summary 6 frames; restore {2}; undo; deleting all 8 → `ValueError`. |
| `test_current_index_clamped_and_signalled` | 99 → 7 with signal args `[7]`; -5 → 0. |
| `test_selection` | `selectionChanged` fires; the selection is stored. |
| `test_frame_start_ms` | Frame 3 starts at 300 ms. |
| `test_closed_document` | No source: `plan()`/`summary()` are `None`, index changes are ignored. |

## How it works
`qtbot.waitSignal(signal)` is used as a context manager: it fails if the signal does not fire, and `blocker.args` holds the emitted arguments.

## Invariants & gotchas
- 11 cases.

## Tests
- **Gaps:** `close()` signals; replacing an open source (old source closed); `stateChanged` on undo.

## History
- `0137178`.
