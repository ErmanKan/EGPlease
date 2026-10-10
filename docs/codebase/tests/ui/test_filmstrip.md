# `tests/ui/test_filmstrip.py`

> pytest-qt tests for the filmstrip: the model's roles, lazy thumbnails, selection/current syncing, Delete/Restore keys, the context menu and the empty state.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest.
- **Uses:** `ui/inspector/filmstrip.py` (`Filmstrip`, `FrameListModel`), `ui/document.py`, `core/decoder.py` (`GifSource`), `tests/gifgen.py` (`PALETTE`), fixtures `doc` and `gif_path` from `tests/ui/conftest.py` (8 solid-colour frames, 40×30, 100 ms each; frame *i* has colour `PALETTE[i]`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `strip` | fixture | A shown 600×140 `Filmstrip` on the `doc` fixture. Teardown waits for the thread pool so no thumbnail job is still decoding when `doc` closes the source. |
| `_select(strip, rows)` | helper | Replace the view selection with `rows` through the selection model (like Ctrl-clicks). |
| `_actions(strip, row=None)` | helper | `build_context_menu(row)` → `{text: QAction}`. |

| Test | Checks |
|---|---|
| `test_row_count_and_roles` | 8 rows; `'#3\n100 ms'`; tooltip text; default roles; accessible name. |
| `test_thumbnails_load` | `waitUntil` the real thumbnail is cached and its pixel colour is `PALETTE[1]`; size 40×30. |
| `test_placeholder_has_aspect_ratio` | Placeholder is 40×30 (same aspect as the GIF). |
| `test_selection_syncs_to_doc` | View selection → `doc.selection`, and back. |
| `test_current_index_syncs_both_ways` | `doc.set_current_index` → current row, and back. |
| `test_delete_key_one_undo_step` | Delete key on 2 rows → `deleted == {1, 2}`, exactly 1 undo command, `DeletedRole` + tooltip, undo restores. |
| `test_backspace_and_restore_keys` | Backspace deletes; Ctrl+Shift+Delete and Insert restore. |
| `test_delete_all_emits_error` | Select all + Delete → `errorOccurred('…every frame')`, state and undo stack unchanged. |
| `test_context_menu_delete_restore_select_all` | Enabled states follow the selection's deleted flags; triggering works; Select all selects all 8. |
| `test_context_menu_trim` | Trim start/end values (200 ms / 400 ms), two separate undo steps, `InTrimRole` per row, "outside trim" tooltip, start keeps the end, end on last frame → `None`. |
| `test_trim_end_before_start_emits_error` | End before start → `errorOccurred`, state unchanged. |
| `test_in_trim_role_false_outside_trim` | Window `[250, 550)` → rows 2–5 in trim (partially visible frames count). |
| `test_stale_thumbnail_result_ignored` | After `set_source` (new generation) a result with the old generation is dropped; the current generation is accepted. |
| `test_empty_doc` | Empty `Document`: 0 rows, disabled, menu actions disabled, Delete/restore/paint do not crash. |
| `test_close_resets_rows` | `doc.close()` → 0 rows, disabled. |
| `test_paints_all_states` | `grab()` with deleted, out-of-trim and current frames paints without errors. |

## How it works
- Keys are sent with `qtbot.keyClick(strip, ...)`, which goes through the real `keyPressEvent`.
- The context menu is never shown (`exec` would block an offscreen test); the tests trigger the `QAction`s returned by `build_context_menu()`.
- Thumbnails load on a real worker thread, so `test_thumbnails_load` first asks for the decoration (as a paint would) and then uses `qtbot.waitUntil`.
- The stale-result test calls `FrameListModel.on_thumbnails_loaded(old_generation, ...)` directly instead of racing a real worker, which makes it deterministic.

## Invariants & gotchas
- **pytest-qt deletes widgets before fixture teardown.** Its `pytest_runtest_teardown` hook calls `close()` + `deleteLater()` on every `qtbot.addWidget` widget *before* our fixture's code after `yield` runs. An earlier version polled `w.frame_model.is_loading` there; the event loop then processed the `DeferredDelete`, the model died, its last batch was never delivered, and the test flaked with a timeout. The fixture now only calls `QThreadPool.globalInstance().waitForDone()`.
- Colours are compared with exact `QColor` equality: the fixture frames are solid, and the thumbnail is not resized (40×30 < 96), so no resampling blur.

## Tests
- This file is the test. Gaps: scroll-driven batch priority and the right-click popup.

## History
- Milestone 2 (filmstrip worker): created with the widget.
