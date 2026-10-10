# `src/gif_editor/ui/commands.py`

> One generic undoable command, `SetStateCommand` (old state → new state), with gesture merging.

## Where it sits
- **Layer:** ui (Qt: `QUndoCommand`)
- **Used by:** `ui/document.py` (`Document.apply` pushes it).
- **Uses:** `core/models.py` (`EditState`); `ui/document.py` for typing only (`TYPE_CHECKING` import, which avoids an import cycle).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `SetStateCommand(doc, old, new, text, merge_key=None)` | `QUndoCommand` | `redo()` sets `new` and `undo()` sets `old`, both via `doc._set_state_raw`. `text` is shown in Undo/Redo menus ("Undo Speed"). |
| `.old`, `.new` | attributes | The two states. `new` is updated by merges. |
| `.id()` | method | Merge id: `-1` (never merge) when `merge_key is None`, else `crc32(key) & 0x7FFFFFFF`. |
| `.mergeWith(other)` | method | Absorb a following command with the same id. |

## How it works
- **Why one command class:** `EditState` is immutable and compares by value, so the old and new states *are* the undo record. A separate command per edit type (CropCommand, SpeedCommand, …), as the plan originally sketched, would just duplicate this logic.
- **Merging continuous gestures:** dragging a trim handle produces dozens of `apply` calls. With the same `merge_key` (e.g. `"trim"`), Qt's `QUndoStack.push` calls `mergeWith` on the top command. That command keeps its **original `old`** and takes the newest `new`, so the whole drag is one undo step.
- **Obsolete gestures:** if the merged `new == old` (the user dragged back to where they started), `setObsolete(True)` makes Qt drop the command, so no empty undo step remains (`test_gesture_back_to_start_is_dropped`).
- `_merge_id` hashes the string key to a non-negative 31-bit int, because Qt ids are ints and `-1` means "no merge".

## Invariants & gotchas
- Merging happens for **any** two consecutive commands with the same key, even if minutes apart. If separate drags must be separate undo steps, use a per-gesture key such as `"trim-<press-id>"`. Qt also skips merging when the top command is at the stack's clean index (`setClean()`), but that changes the stack's "clean" (saved) state too, so prefer per-gesture keys. Note that `set_trim` defaults to `merge_key="trim"`, so two separate trim drags in a row currently merge into one step.
- CRC32 collisions between two different keys would merge unrelated edits. This is unlikely with a handful of fixed key strings.
- `redo()` is called by Qt immediately on `push`. Do not set the state before pushing.

## Tests
- Through `tests/ui/test_document.py` (`test_apply_undo_redo`, `test_merge_key_collapses_gesture`, `test_gesture_back_to_start_is_dropped`).
- **Gaps:** no direct unit test of `_merge_id` or of merging between different keys.

## History
- `0137178`: orchestrator M2 foundation.
