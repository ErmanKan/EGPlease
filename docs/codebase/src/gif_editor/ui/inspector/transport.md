# `src/gif_editor/ui/inspector/transport.py`

> The playback controls row: first / previous / play-pause / next / last buttons, a "Preview edits" check box, a frame-info label and a "Save frame…" button.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** the inspector panel / main window, which places it under the canvas, connects `saveFrameRequested` to its save dialog and owns the keyboard shortcuts.
- **Uses:** `ui/document.py` (`Document`), `ui/inspector/player.py` (`Player`), `ui/theme.py` (`media_icon`), `core/timeline.py` (`start_times_ms`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `TransportBar(doc, player, parent=None)` | class (`QWidget`) | The controls row. Unlike other widgets it also takes the `Player`, because driving playback is its whole job. |
| `.first_button`, `.prev_button`, `.play_button`, `.next_button`, `.last_button` | `QToolButton` attributes | Exposed for tests and for the main window (e.g. to reuse in a menu). `play_button` is checkable; checked = playing. |
| `.preview_check` | `QCheckBox` | "Preview edits", two-way bound to `player.preview_edits`. |
| `.info_label` | `QLabel` | e.g. `Frame 37 / 120 · 1.48 s · 40 ms` (+ ` · deleted`). |
| `.save_button` | `QPushButton` | "Save frame…"; emits `saveFrameRequested`. |
| `format_frame_info(index, count, start_ms, delay_ms, deleted)` | function → `str` | Builds the label text (`index` is 0-based; shown 1-based). |
| `EMPTY_TEXT` | constant | Label text when no GIF is open (`"No GIF open"`). |

Signals: `saveFrameRequested()`: the user clicked "Save frame…". The main window shows the file dialog and calls `export_frame_png`.

## How it works
1. **Buttons.** Framed `QToolButton`s (not auto-raise, so they read as buttons in every theme). The icons are vector shapes from `theme.media_icon` (first, prev, play/pause, next, last), drawn in the palette's `ButtonText` colour and rebuilt by `_update_icons` on every `PaletteChange` (`changeEvent`), so they are dark in light mode and light in dark mode, and follow a live light/dark switch. Until 2026-10-14 they were `QStyle.standardIcon` media icons, which Fusion draws as dark grey glyphs: 1.17 : 1 against the dark-mode window, practically invisible ([theme](../theme.md)). We still ship no image files. Each tooltip names the shortcut, e.g. "Next frame (Right)". The shortcuts themselves live in the main window: a `QShortcut` on this bar would only work while the bar has focus.
2. **Wiring to the player.** First → `player.go_first()`, Prev → `player.step(-1)`, Play → `player.toggle()`, Next → `player.step(1)`, Last → `player.go_last()`. They act on the *current sequence*, so with "Preview edits" on, Next skips deleted/trimmed frames.
3. **Play button state comes from the player, not from the click.** A checkable `QToolButton` flips its own checked state when clicked, but the truth is `playingChanged(bool)`: the slot sets the checked state, stores it in `_playing` (so a palette change redraws the right icon), swaps the icon (play ↔ pause) and the tooltip. This matters when `play()` refuses (empty plan): the click checked the button, then `playingChanged(False)` un-checks it. We use `clicked` (user only), not `toggled`, so setting the checked state from code never re-triggers `toggle()`.
4. **Preview check box.** `toggled` → `player.set_preview_edits`; `previewEditsChanged` → `setChecked` (only if different, so there is no loop).
5. **Frame label.** Updated on `currentIndexChanged`, `stateChanged` (the "deleted" suffix depends on `EditState.deleted`) and `sourceChanged`. The time is the frame's *source* start time; the start times are computed once per file with `start_times_ms` and cached, so the label update is O(1) during playback instead of summing all delays every frame. The delay shown is the effective delay.
6. **Empty state.** On `sourceChanged`, `setEnabled(doc.is_open)` on the whole bar. In Qt, disabling a parent disables all its children, so one call covers every control. The label shows `EMPTY_TEXT`.

## Invariants & gotchas
- The bar talks to `Document` and the `Player` it was given, never to other widgets.
- Don't add `QShortcut`s here; the main window owns them (otherwise keys would conflict or depend on focus).
- `play_button.isChecked()` mirrors `player.is_playing` after every `playingChanged`; don't set it elsewhere.
- The label text uses `·` (U+00B7) separators and two decimals for seconds.

## Tests
- `tests/ui/test_transport.py`: label formatting, label after `set_current_index` and after delete/undo, play button checked state (clicks and programmatic play/pause), button un-checks on an empty plan, first/prev/next/last move frames (including wrap), check box ↔ player binding, `saveFrameRequested`, tooltips name the shortcuts, disabled with an empty `Document` and after `close()`.
- `tests/ui/test_theme.py`: buttons framed, icon colour follows light ↔ dark (also across the play/pause swap), and rendered contrast under a dark palette.
- Gap: icon shapes aren't compared pixel by pixel (their colour and presence are).

## History
- Milestone 2: created. Shortcuts deliberately left to the main window; save dialog left to the main window via `saveFrameRequested` so the bar stays dialog-free and testable.
- 2026-10-14: framed buttons and palette-coloured vector icons for dark mode ([dev log](../../../../../04-development-log.md#dark-mode-buttons)).
