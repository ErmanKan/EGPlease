# `tests/ui/test_main_window.py`

> Integration tests for the whole window: driven the way a user would (actions, real key presses and mouse drags, drag-and-drop), with real decoding and a real Generate on background threads; since M4 also the plain-language error dialogs, the window fitting small screens, closing during Generate, and Space on the canvas.

## Where it sits
- **Layer:** tests (Qt, pytest-qt)
- **Used by:** pytest (via `scripts/test.sh`, or with `QT_QPA_PLATFORM=offscreen` on Windows/CI).
- **Uses:** `ui/main_window.py` (`MainWindow`), `app.py` (`main`), `core/encoder.py` (`read_back`), `core/models.py` (`CropRect`), `tests/gifgen.py` (`make_gif`, `solid_frames`, `PALETTE`), `tests/corpus.py` (`build_all`, for the truncated file), `ui/main_window.py`'s module-level `generate` (monkeypatched), fixtures `gif_path` (8 frames, 40×30, 100 ms; `tests/ui/conftest.py`), `qtbot`, `tmp_path`, `monkeypatch`.

## Public API
Fixture `win`: a shown, exposed `MainWindow()` registered with `qtbot.addWidget`. Teardown waits until `not w.is_busy`, so no open or Generate job is still running when the next test starts. Helper `_open(qtbot, w, path)`: `open_file` + wait until open and idle.

| Test | Verifies |
|---|---|
| `test_starts_empty_with_doc_actions_disabled` | No document, title "GIF Editor"; Open enabled; Generate action and the panel's Generate button disabled. |
| `test_open_file_async` | Async open: 8 frames, title starts with `in.gif`, Generate/Play enabled, status says "8 frames". |
| `test_open_bad_file_reports_error` | A non-GIF → `last_error` names the file and says "is not a GIF" (plain words), the technical "Not a GIF file" is in `last_dialog.detailedText()`; nothing open, Open re-enabled (no blocking dialog). |
| `test_open_truncated_file_explains_partial_load` (M4) | The corpus `truncated` file opens; `last_error` says "is damaged" and "could be loaded"; `last_dialog` has the **Information** icon and its details equal the decoder's warnings. |
| `test_drop_gif_opens_it` | A synthetic `QDropEvent` with a local `.gif` URL opens it. |
| `test_navigation_and_delete_via_actions` | Next/Last/First/Forward-10 (wraps: `10 % 8`), Delete on a selection, Undo, Redo. |
| `test_keyboard_shortcut_reaches_action` | Real key clicks on the focused canvas: Right → frame 1, End → frame 7 (window shortcuts work from a child). |
| `test_trim_in_out_at_playhead` | I at frame 2 → `(200, None)`; O at frame 5 → `(200, 400)` and 4 output frames; O before the start → error, unchanged; Reset → `(0, None)`; 3 undo steps (no merging). |
| `test_generate_writes_edited_gif` | Delete {0, 7} + speed 2 → busy and Generate disabled while running; output reads back as 6 frames of 50 ms; `last_result` and status message; re-enabled after. |
| `test_generate_cancel_leaves_nothing` | 200-frame 300×200 GIF, cancel right after starting → if it was cancelled in time, no output and a "cancelled" status; never a leftover `.tmp`. |
| `test_shortcuts_cover_platform_bindings` | Redo has both Ctrl+Y and Ctrl+Shift+Z; Close is Ctrl+W; Quit is Ctrl+Q. |
| `test_ctrl_g_refuses_empty_output` | With every frame trimmed/deleted, `generate_dialog()` shows "Nothing to generate" without opening a file dialog, and `generate_to` writes nothing; not busy afterwards. |
| `test_generate_reports_warnings` | Speed 4× (100 ms → 25 ms, a rounding warning): if the result has warnings, the first one is in the status message. |
| `test_save_frame_png` | Frame 3 as PNG is 40×30 with `PALETTE[3]`; with a 10×10 crop and `with_edits=True` it is 10×10. |
| `test_preview_action_bound_to_player` | The P action sets `player.preview_edits` and checks the transport box; unchecking the box unchecks the action. |
| `test_play_pause_and_close` | Play advances the frame on a real timer; pause; Close → no document, Generate disabled, title reset. |
| `test_reopen_replaces_document` | Opening a second file resets state and undo, and the filmstrip shows 3 rows. |
| `test_generate_write_error_is_explained` (M4) | `generate` replaced by one raising `PermissionError(EACCES)` → `last_error` contains "No permission to save" and "Nothing was written"; details contain "Permission denied"; no output file. |
| `test_close_during_generate_cancels_then_closes` (M4) | A `generate` that waits for the cancel event: `win.close()` returns False (deferred, not refused), the window stays visible with "…then closing" in the status bar, then closes **by itself**; not busy, no output written. |
| `test_window_fits_small_screen_and_generate_stays_visible` (M4) | With `availableGeometry` patched to 1280×680 (1080p at 150 % minus a taskbar), a new window is ≤ 1280×680 at a non-negative position, Generate is **not** inside the `QScrollArea`, and its rectangle lies fully inside the window. |
| `test_space_tap_on_canvas_plays` (M4) | Canvas focused: a Space click starts playback, a second one pauses (via `spaceTapped`). |
| `test_space_drag_on_canvas_pans_without_playing` (M4) | Canvas focused at zoom 8 on a 400×300 GIF: Space down, left press, five moves to the right, release, Space up → the horizontal scroll bar moved left and playback did **not** start. Fails with the `ShortcutOverride` fix disabled (checked when the fix was made). |
| `test_space_elsewhere_still_plays` (M4) | Filmstrip focused: Space still toggles playback through the window action. |
| `test_app_main_runs_selftest_and_window` | `app.main(["gif-editor"])` with `QApplication.exec` monkeypatched: the real self-test passes and a visible `MainWindow` exists; the windows are closed afterwards. |

## How it works
- **No dialogs.** The tests call the non-dialog entry points (`open_file`, `generate_to`, `save_frame_to`) instead of `*_dialog`, and errors are read from `win.last_error` (headline + body) and `win.last_dialog` (icon, `detailedText()`). This works because `show_explanation` uses the non-blocking `QMessageBox.open()`.
- **Failures are injected** by monkeypatching `main_window.generate` (the name the window calls), not by making the disk fail.
- **The Space tests** use their own window with a 400×300 GIF (`_space_window`), so that zoom 8 gives scroll bars in both directions.
- **Background work is awaited with `qtbot.waitUntil`**, which spins the event loop so the queued `run_async` callbacks can arrive. Never `time.sleep`.
- **Actions are triggered directly** (`act.trigger()`) to test the wiring, and one test sends real key events to prove shortcut routing from a focused child widget.
- **The cancel test is timing-tolerant.** A fast machine may finish before the cancel is seen, so the "no output" assertions run only if `last_result is None`; the "no temp file" assertion always runs.
- **`app.main` without blocking.** `QApplication.exec` is replaced by a function that records the visible `MainWindow`s and returns 0. `QApplication.instance()` already exists (pytest-qt), so `main` reuses it.

## Invariants & gotchas
- 24 cases, a few seconds in total (the Generate tests dominate).
- Each test must leave the window idle (the fixture waits for `not is_busy`). A job still running at teardown would call back into a window that pytest-qt has already closed and scheduled for deletion (see the [deleteLater trap](../../../06-testing.md#the-deletelater-teardown-trap)).
- `test_app_main_runs_selftest_and_window` creates a second, unregistered `MainWindow`; it closes it explicitly.

## Tests
- The self-test failure branch of `app.main` is tested in [`test_smoke.py`](test_smoke.md).
- **Gaps:** the `*_dialog` methods (file dialogs); the progress dialog's own Cancel button; a Save-frame failure; `app.main` with a path argument.

## History
- `be70f38`: added with the main window ([dev log, Milestone 2](../../../04-development-log.md#milestone-2-window-and-inspector)).
- `76cd65c`: three tests for the post-M2 fixes (shortcut bindings, Ctrl+G empty-output guard, Generate warnings). M3 window tests live in [`test_m3_integration.py`](test_m3_integration.md).
- `95b4f03` (M4): plain-language error assertions, truncated-file notice, Generate write error. `9361dd6`: close during Generate, window fits a small screen. `0b07218`: the three Space tests ([dev log, Milestone 4](../../../04-development-log.md#milestone-4-hardening)).
