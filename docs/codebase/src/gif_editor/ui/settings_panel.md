# `src/gif_editor/ui/settings_panel.py`

> The left-hand panel: timing, output size and quality controls, a live summary card and the big Generate button, all mirroring and editing `Document.state`.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** `ui/main_window.py` (places it on the left, usually inside a `QScrollArea`, connects `generateRequested` and the Ctrl+G shortcut).
- **Uses:** `ui/document.py` (`Document`: state, `apply`, `set_trim`, `summary`, signals), `core/models.py` (`EditState`, `OutputSize`, `Quality`, `MIN_SPEED`/`MAX_SPEED`/`MAX_FPS`). Indirectly `core/pipeline.summarize` via `Document.summary()`.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `SettingsPanel(doc: Document, parent: QWidget \| None = None)` | class (`QWidget`) | The panel. Everything it shows comes from `doc`. |
| `SettingsPanel.generateRequested` | signal `()` | User clicked Generate. |
| `SettingsPanel.sizeHint() -> QSize` | method | ~280 logical px wide (`PANEL_WIDTH`), natural height. |
| `SettingsPanel.PANEL_WIDTH` | int | 280. |
| `WARNING_COLOR`, `ERROR_COLOR` | str constants | Amber for warnings, red for errors / empty output in the summary card. |
| `PRESETS` | tuple | Combo entries `(label, Quality preset key or None)`; `None` = "Custom". |
| `TIMES` | str | `"×"` (written as an escape so ruff's look-alike-character rule stays quiet). |

Child widgets are public attributes so tests (and the main window, if it ever needs focus handling) can reach them: `start_spin`, `duration_spin`, `to_end_check`, `speed_spin`, `speed_slider`, `fps_check`, `fps_spin`, `width_spin`, `height_spin`, `lock_check`, `scale_spin`, `reset_size_button`, `preset_combo`, `colors_spin`, `dither_check`, `summary_label`, `generate_button`, and the group boxes `timing_group`, `size_group`, `quality_group`, `summary_group`. Other widgets must **not** use them (widgets talk only to `Document`).

Signals (Qt files): `generateRequested()`: fires when the Generate button is clicked. The button is only enabled when a file is open and the output has at least one frame, so the receiver can assume there is something to write.

## How it works

### Layout
A `QVBoxLayout` stacks four `QGroupBox`es (Timing, Output size, Quality, Summary), a stretch, and the Generate button. Each group uses a `QFormLayout` (label column + field column), which is the Qt idiom for settings forms and keeps labels aligned automatically under any font/DPI. Nothing is sized in physical pixels, so HiDPI scaling is handled by Qt.

| Group | Controls | Maps to |
|---|---|---|
| Timing | Start time (s, 0.01 steps), Duration (s) + "to end", Speed spin (0.25–4.0×, step 0.05) + slider, "Limit FPS" + FPS spin (1–50) | `trim_start_ms`, `trim_duration_ms` (None = to end), `speed`, `fps` (None = unlimited) |
| Output size | Width, Height (1–8192), "Lock aspect", Scale % (1–400), Reset | `size` (None = base size) |
| Quality | Preset (High/Medium/Low/Custom), Colours (2–256), Dither | `quality` |
| Summary | rich-text `QLabel` | read-only, from `doc.meta` and `doc.summary()` |

### The two directions of data flow
```mermaid
flowchart LR
    C[control signal<br/>valueChanged / toggled] --> H[_on_*_edited]
    H -->|doc.apply(state.with_(...), text, merge_key)| D[Document]
    D -->|stateChanged| R[_refresh_controls<br/>signals blocked]
    D -->|stateChanged| S[_refresh_summary]
```

1. **Control → state.** Each control's change signal goes to a handler that builds a new `EditState` with `doc.state.with_(...)` and calls `doc.apply(new, text, merge_key)` (trim uses `doc.set_trim`, which calls `apply`). The merge key is a fixed string per kind of setting: `"trim"`, `"speed"`, `"fps"`, `"size"`, `"quality"`. `SetStateCommand` merges consecutive commands with the same key, so holding the spin arrow, scrolling the wheel over a spinbox or dragging the slider produces **one** undo step. The speed spinbox and slider share `"speed"`, so mixing them is still one step.
2. **State → controls.** `Document.stateChanged` (fired after our own edit, undo/redo, or another widget's edit) triggers `_refresh_controls`, which writes every control from `doc.state`. It runs inside `_blocked()`, a context manager that holds a `QSignalBlocker` on every input. **Why:** `setValue()` on a spinbox normally emits `valueChanged`; without blocking, an undo would re-enter the handlers and push a fresh command, destroying the redo history (a feedback loop). `_set()` additionally only calls `setValue` when the value really differs, so the caret in a spinbox being typed into isn't disturbed.

`_on_source_changed` runs on `sourceChanged` (file opened/closed): it enables/disables the three setting groups, sets the time ranges from the source duration (start: 0…duration−0.01 s, duration: 0.01 s…duration), picks a default for the FPS spin (the source's average frame rate, capped at 50), and refreshes everything.

### Timing details
- Seconds in the UI, integer milliseconds in the state (`round(value * 1000)`).
- **Clamping instead of errors:** a start is clamped so at least 10 ms remain; a duration longer than what remains after the start is clamped to the remainder (the spec says "too long" is not an error). After each edit the controls are refreshed so the user sees the clamped value even if the state did not change.
- With "to end" checked the duration is `None` and its spinbox is disabled but still shows the remaining length, so unchecking it starts from a sensible value.
- Speed slider works in hundredths (25–400) because `QSlider` is integer-only.
- FPS: unchecked = `fps=None`; changing the (disabled) spinbox while unchecked changes nothing.

### Output size details
- The **base size** is the crop size if a crop is set, otherwise the canvas size — exactly what `core.render.output_dimensions` uses when `size` is `None`.
- With "Lock aspect" on, editing width computes height from the base ratio (and vice versa); off, the other side is kept. "Lock aspect" is a UI-only preference, not part of `EditState`.
- Scale % sets both sides to `base × pct / 100`, and is displayed as `round(width / base_width × 100)`.
- If the requested size equals the base size, the panel stores `size=None` instead of an explicit `OutputSize`. **Why:** then a later crop change keeps "output = crop size" instead of silently resizing to stale numbers. Reset also sets `None`; it is disabled when `size` is already `None`.
- Values are clamped to 1…8192.

### Quality details
- Picking High/Medium/Low (`QComboBox.activated`, i.e. only real user picks) applies `Quality.preset(key)`. Picking "Custom" changes nothing; it just signals intent.
- Editing colours or dither applies `Quality(colors, dither)`. The combo is then re-derived from the state by `_preset_index`: it shows the preset whose values match, otherwise "Custom". So editing switches to Custom unless you land on a preset's values.

### Errors
All `doc.apply` calls run through `_try`. If `apply` raises `ValueError` (invalid combination, e.g. a size that can't be validated), the panel stores the message, reverts all controls to `doc.state` (nothing changed there, `apply` is atomic) and shows the message in red in the summary card. The next successful state change clears it.

### Summary card and Generate
`_refresh_summary` (on `stateChanged` and `sourceChanged`) builds rich text:
- **Source:** `N frames · X.XX s · W×H` from `doc.meta`.
- **Output:** the same from `doc.summary()` (which uses `plan_output`, the only place that decides output frames, so it matches Generate exactly).
- An "output is empty" message if the frame count is 0, warnings from `Summary.warnings` in amber (HTML-escaped), the last error in red. A `ValueError` from `summary()` itself is shown as its message.
- The Generate button is enabled iff a file is open and the output has ≥ 1 frame.

`doc.summary()` is pure arithmetic over the frame delays (no decoding), so it is cheap enough to run on the GUI thread on every change.

## Invariants & gotchas
- **Every** programmatic write to a control must happen inside `_blocked()`; otherwise undo/redo pushes new commands.
- When adding a new control, add it to the list in `_blocked()`, connect it in `_connect_controls`, mirror it in `_refresh_controls`, and give it a merge key.
- Handlers return early when `doc.is_open` is False, so even a programmatically forced value change on an empty document pushes nothing.
- Spinboxes use `setKeyboardTracking(False)`: typing "120" doesn't apply 1, 12, 120 as three states; the value applies on Enter/focus-out. Arrow keys and the wheel still apply immediately (merged by key).
- Merging only happens with the *top* undo command: speed → fps → speed gives three steps. That's intended (they are different gestures).
- The panel does not implement "trim from playhead" shortcuts; the main window owns those.
- Colours are inline hex (`#c77700`, `#c0392b`) chosen to read on both the light and dark Fusion palettes.

## Tests
- `tests/ui/test_settings_panel.py`: initial values; speed spin merging into one undo step; slider ↔ spin sync; undo restoring controls without pushing commands; "to end" ↔ `None`; start/duration clamping; FPS checkbox ↔ `None`/value; aspect lock (canvas and crop base), unlocked editing; scale and Reset; presets and switching to Custom; summary text and update after `delete_frames`; empty output disabling Generate; `ValueError` revert + message; `generateRequested` on click; disabled state after `close()` and for a Document with no source.
- Gaps: visual layout/width inside a real `QScrollArea` is not asserted beyond `sizeHint()`; warning colour rendering is not checked.

## History
- Milestone 2: created (settings panel worker). Size equal to the base is stored as `None` so crop changes keep driving the output size.
