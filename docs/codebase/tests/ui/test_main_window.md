# `tests/ui/test_main_window.py`

> Integration tests for the whole window: driven the way a user would (actions, a real key press, drag-and-drop), with real decoding and a real Generate on background threads.

## Where it sits
- **Layer:** tests (Qt, pytest-qt)
- **Used by:** pytest (via `scripts/test.sh`, or with `QT_QPA_PLATFORM=offscreen` on Windows/CI).
- **Uses:** `ui/main_window.py` (`MainWindow`), `app.py` (`main`), `core/encoder.py` (`read_back`), `core/models.py` (`CropRect`), `tests/gifgen.py` (`make_gif`, `solid_frames`, `PALETTE`), fixtures `gif_path` (8 frames, 40×30, 100 ms; `tests/ui/conftest.py`), `qtbot`, `tmp_path`, `monkeypatch`.

## Public API
Fixture `win`: a shown, exposed `MainWindow()` registered with `qtbot.addWidget`. Teardown waits until `not w.is_busy`, so no open or Generate job is still running when the next test starts. Helper `_open(qtbot, w, path)`: `open_file` + wait until open and idle.

| Test | Verifies |
|---|---|
| `test_starts_empty_with_doc_actions_disabled` | No document, title "GIF Editor"; Open enabled; Generate action and the panel's Generate button disabled. |
| `test_open_file_async` | Async open: 8 frames, title starts with `in.gif`, Generate/Play enabled, status says "8 frames". |
| `test_open_bad_file_reports_error` | A non-GIF → `last_error` names the file, nothing open, Open re-enabled (no blocking dialog). |
| `test_drop_gif_opens_it` | A synthetic `QDropEvent` with a local `.gif` URL opens it. |
| `test_navigation_and_delete_via_actions` | Next/Last/First/Forward-10 (wraps: `10 % 8`), Delete on a selection, Undo, Redo. |
| `test_keyboard_shortcut_reaches_action` | Real key clicks on the focused canvas: Right → frame 1, End → frame 7 (window shortcuts work from a child). |
| `test_trim_in_out_at_playhead` | I at frame 2 → `(200, None)`; O at frame 5 → `(200, 400)` and 4 output frames; O before the start → error, unchanged; Reset → `(0, None)`; 3 undo steps (no merging). |
| `test_generate_writes_edited_gif` | Delete {0, 7} + speed 2 → busy and Generate disabled while running; output reads back as 6 frames of 50 ms; `last_result` and status message; re-enabled after. |
| `test_generate_cancel_leaves_nothing` | 200-frame 300×200 GIF, cancel right after starting → if it was cancelled in time, no output and a "cancelled" status; never a leftover `.tmp`. |
| `test_save_frame_png` | Frame 3 as PNG is 40×30 with `PALETTE[3]`; with a 10×10 crop and `with_edits=True` it is 10×10. |
| `test_preview_action_bound_to_player` | The P action sets `player.preview_edits` and checks the transport box; unchecking the box unchecks the action. |
| `test_play_pause_and_close` | Play advances the frame on a real timer; pause; Close → no document, Generate disabled, title reset. |
| `test_reopen_replaces_document` | Opening a second file resets state and undo, and the filmstrip shows 3 rows. |
| `test_app_main_runs_selftest_and_window` | `app.main(["gif-editor"])` with `QApplication.exec` monkeypatched: the real self-test passes and a visible `MainWindow` exists; the windows are closed afterwards. |

## How it works
- **No dialogs.** The tests call the non-dialog entry points (`open_file`, `generate_to`, `save_frame_to`) instead of `*_dialog`, and errors are read from `win.last_error`. This works because `show_error` uses the non-blocking `QMessageBox.open()`.
- **Background work is awaited with `qtbot.waitUntil`**, which spins the event loop so the queued `run_async` callbacks can arrive. Never `time.sleep`.
- **Actions are triggered directly** (`act.trigger()`) to test the wiring, and one test sends real key events to prove shortcut routing from a focused child widget.
- **The cancel test is timing-tolerant.** A fast machine may finish before the cancel is seen, so the "no output" assertions run only if `last_result is None`; the "no temp file" assertion always runs.
- **`app.main` without blocking.** `QApplication.exec` is replaced by a function that records the visible `MainWindow`s and returns 0. `QApplication.instance()` already exists (pytest-qt), so `main` reuses it.

## Invariants & gotchas
- 14 cases, about 1–2 s in total (the Generate tests dominate).
- Each test must leave the window idle (the fixture waits for `not is_busy`). A job still running at teardown would call back into a window that pytest-qt has already closed and scheduled for deletion (see the [deleteLater trap](../../../06-testing.md#the-deletelater-teardown-trap)).
- `test_app_main_runs_selftest_and_window` creates a second, unregistered `MainWindow`; it closes it explicitly.

## Tests
- **Gaps:** the `*_dialog` methods (file dialogs); `closeEvent` while generating; the progress dialog's own Cancel button; a non-cancel Generate failure; a Save-frame failure; `app.main` with a path argument and the self-test failure branch; Space with the canvas focused (the known Space+drag limitation).

## History
- `be70f38`: added with the main window ([dev log, Milestone 2](../../../04-development-log.md#milestone-2-window-and-inspector)).
