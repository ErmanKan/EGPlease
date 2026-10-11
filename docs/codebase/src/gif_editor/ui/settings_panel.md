# `src/gif_editor/ui/settings_panel.py`

> The left-hand panel: timing, output size, crop and quality controls, a live summary card (with the estimated file size) and the big Generate button, all mirroring and editing `Document.state`. Every input explains its range and why in a tooltip (and the same text as its accessible description).

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** `ui/main_window.py` (creates it with `preview=self.preview`, places it on the left inside a `QScrollArea`, **moves `generate_button` out of the panel's layout into a pinned footer under the scroll area** (M4), connects `generateRequested` and the Ctrl+G shortcut).
- **Uses:** `ui/document.py` (`Document`: state, `apply`, `set_trim`, `summary`, signals), `core/models.py` (`EditState`, `OutputSize`, `Quality`, `MIN_SPEED`/`MAX_SPEED`/`MAX_FPS`). Indirectly `core/pipeline.summarize` via `Document.summary()`. `ui/crop_panel.py` (`CropPanel`, embedded). Optionally a `PreviewService` (`ui/inspector/preview.py`), duck-typed: only `estimated_bytes`, `estimate_pending`, `estimateChanged` and `estimateReady` are used, and the module is not imported.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `SettingsPanel(doc: Document, parent: QWidget \| None = None, *, preview=None)` | class (`QWidget`) | The panel. Everything it shows comes from `doc`. `preview` is an optional `PreviewService`; with it the summary card shows the size estimate. Keyword-only, so M2 callers (`SettingsPanel(doc)`) keep working. |
| `SettingsPanel.crop_panel` | attribute | The embedded [`CropPanel`](crop_panel.md) (the Crop group). |
| `SettingsPanel.generateRequested` | signal `()` | User clicked Generate. |
| `SettingsPanel.sizeHint() -> QSize` | method | ~280 logical px wide (`PANEL_WIDTH`), natural height. |
| `SettingsPanel.PANEL_WIDTH` | int | 280. |
| `WARNING_COLOR`, `ERROR_COLOR` | str constants | Amber for warnings, red for errors / empty output in the summary card. |
| `PRESETS` | tuple | Combo entries `(label, Quality preset key or None)`; `None` = "Custom". |
| `TIMES` | str | `"×"` (written as an escape so ruff's look-alike-character rule stays quiet). |
| `format_bytes(n) -> str` | function | Human-readable size with 1 KB = 1024 B: `850 → "850 B"`, `12 700 → "12.4 KB"`, `3 365 000 → "3.21 MB"`. |

Child widgets are public attributes so tests (and the main window, if it ever needs focus handling) can reach them: `start_spin`, `duration_spin`, `to_end_check`, `speed_spin`, `speed_slider`, `fps_check`, `fps_spin`, `width_spin`, `height_spin`, `lock_check`, `scale_spin`, `reset_size_button`, `preset_combo`, `colors_spin`, `dither_check`, `summary_label`, `generate_button`, and the group boxes `timing_group`, `size_group`, `quality_group`, `summary_group`. Other widgets must **not** use them (widgets talk only to `Document`).

Signals (Qt files): `generateRequested()`: fires when the Generate button is clicked. The button is only enabled when a file is open and the output has at least one frame, so the receiver can assume there is something to write.

## How it works

### Layout
A `QVBoxLayout` stacks Timing, Output size, the **Crop** group (`CropPanel`, M3), Quality, Summary, a stretch, and the Generate button. (Inside the main window the Generate button is removed from this layout and pinned below the scroll area, so it never scrolls out of view; the panel still owns it and emits `generateRequested` from it. See [main_window](main_window.md#layout).) Each group uses a `QFormLayout` (label column + field column), which is the Qt idiom for settings forms and keeps labels aligned automatically under any font/DPI. Nothing is sized in physical pixels, so HiDPI scaling is handled by Qt.

| Group | Controls | Maps to |
|---|---|---|
| Timing | Start time (s, 0.01 steps), Duration (s) + "to end", Speed spin (0.25–4.0×, step 0.05) + slider, "Limit FPS" + FPS spin (1–50) | `trim_start_ms`, `trim_duration_ms` (None = to end), `speed`, `fps` (None = unlimited) |
| Output size | Width, Height (1–8192), "Lock aspect", Scale % (1–400), Reset | `size` (None = base size) |
| Crop (`crop_panel`) | checkable group: Aspect, X/Y/W/H, Full image / Center / Reset, status line | `crop` (None = no crop). Owned by `CropPanel`; see [its page](crop_panel.md) |
| Quality | Preset (High/Medium/Low/Custom), Colours (2–256), Dither | `quality` |
| Summary | rich-text `QLabel` | read-only, from `doc.meta` and `doc.summary()` |

### Tooltips: every input says its range and why (M4)
`_explain(widget, text)` (a static method) sets the **same text** as the widget's tooltip and its `accessibleDescription`. *Why:* spin boxes silently clamp what you type to their range, which looks like the app ignoring you. Saying the limit and its reason, where the mouse (tooltip) and screen readers (accessible description) both find it, turns that into an expected rule. The texts, verified against the code:

| Control | Text (abridged) | The *why* behind the limit |
|---|---|---|
| Start time | where the output starts, in seconds; also set by the left timeline handle or I | — |
| Duration | length from the start, in the original GIF's time (before speed); can't go past the end | trim is in source time (Gate 1 decision) |
| to end | run from the start time to the end | — |
| Speed spin + slider | "Playback speed, 0.25× to 4×. Faster speeds shorten every frame's delay. GIF viewers slow down frames shorter than 20 ms, so such frames are merged with their neighbours (the summary shows how many)." | output delays must be ≥ 20 ms (`timeline._enforce_min_delay`) |
| Limit FPS | drop frames so the output plays at most this many FPS (smaller file, choppier motion) | speed/FPS only drop frames |
| FPS spin | "1 to 50 frames per second. GIF stores delays in hundredths of a second and viewers treat anything faster than 50 FPS (20 ms) as slow, so 50 is the highest rate that plays reliably." | `models.MAX_FPS` |
| Width / Height | "Output width/height, 1 to 8,192 pixels (the largest image the editor handles safely). Applied after the crop." | `MAX_SIDE = 8192` in this module, the same value as the decoder's `Limits.max_canvas_side` |
| Lock aspect | changing one side changes the other to match | — |
| Scale % | % of the cropped frame, 1–400 %; enlarging adds no detail and makes the file much bigger | — |
| Reset (size) | use the crop size (or the original size) | — |
| Preset | sets colours and dithering together; fewer colours = smaller file | — |
| Colours | "Colours in the shared palette, 2 to 256. A GIF can hold at most 256 colours; fewer colours make a smaller file but show banding." | GIF palette limit |
| Dither | mixes palette colours in fine patterns to hide banding; smoother but larger | — |

The numbers for speed, FPS and size come from the constants (`MIN_SPEED`, `MAX_SPEED`, `MAX_FPS`, `MAX_SIDE`) via f-strings (the 2–256 colours and 1–400 % are literal text), so the text cannot drift from the range. The crop panel has its own tooltips; the Generate button is not covered.

**A wrong claim caught in review.** An earlier draft of the speed tooltip claimed that very high speeds make the GIF play *slower* (true for a naive GIF writer, because viewers slow down delays under 20 ms). That is not what this editor does: it never writes a delay under 20 ms, it **folds** the too-short frames into their neighbours instead (`timeline._enforce_min_delay`), and the summary reports how many frames were dropped. The text was corrected before commit; the test now pins the numbers but not the wording, so tooltip claims must be checked against `core/timeline.py` by hand.

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

### The embedded crop panel (M3)
`self.crop_panel = CropPanel(doc)` sits between Output size and Quality. The settings panel does **not** wire it to its own controls: the crop panel talks to `Document` directly (it is a widget like any other), and the Output size group sees a crop change through `stateChanged` like any other edit. That is why "size follows the crop" works without code here: the base size is re-read from `doc.state.crop` on every refresh.

Its rejected edits are **forwarded** into this panel's summary card: `crop_panel.errorOccurred → _on_crop_error(message)`, which stores the message in `self._error` and redraws the summary. The crop panel itself has no place to show an error, and one red line in the summary card is where every rejected edit in the left panel appears. The next state change clears it, as for the panel's own errors.

### Summary card and Generate
`_refresh_summary` (on `stateChanged` and `sourceChanged`, and on the preview service's `estimateChanged` / `estimateReady`) builds rich text:
- **Source:** `N frames · X.XX s · W×H` from `doc.meta`.
- **Output:** the same from `doc.summary()` (which uses `plan_output`, the only place that decides output frames, so it matches Generate exactly).
- **Size** (M3, only with a `preview` service), from `_estimate_line(frame_count)`:

  | Condition | Line |
  |---|---|
  | no service, or 0 output frames | none |
  | `estimated_bytes` known and `estimate_pending` False | **Size:** ≈ `format_bytes(n)` *(estimate)* |
  | `estimate_pending` True (debouncing or computing) | **Size:** *estimating…* |
  | otherwise (`estimated_bytes is None`: the estimate failed) | none |

  The service debounces (250 ms) and computes off the GUI thread, so dragging a slider shows "estimating…" and the number appears once the user stops. A failed estimate shows nothing rather than an error: the estimate is a hint, not a result.
- An "output is empty" message if the frame count is 0, warnings from `Summary.warnings` in amber (HTML-escaped), the last error in red. A `ValueError` from `summary()` itself is shown as its message.
- The Generate button is enabled iff a file is open and the output has ≥ 1 frame.

`doc.summary()` is pure arithmetic over the frame delays (no decoding), so it is cheap enough to run on the GUI thread on every change. The size estimate is **not** (it renders and encodes frames), which is why it lives in `PreviewService` and the panel only reads its last value.

## Invariants & gotchas
- **Every** programmatic write to a control must happen inside `_blocked()`; otherwise undo/redo pushes new commands.
- When adding a new control, add it to the list in `_blocked()`, connect it in `_connect_controls`, mirror it in `_refresh_controls`, and give it a merge key.
- Handlers return early when `doc.is_open` is False, so even a programmatically forced value change on an empty document pushes nothing.
- Spinboxes use `setKeyboardTracking(False)`: typing "120" doesn't apply 1, 12, 120 as three states; the value applies on Enter/focus-out. Arrow keys and the wheel still apply immediately (merged by key).
- Merging only happens with the *top* undo command: speed → fps → speed gives three steps. That's intended (they are different gestures).
- The panel does not implement "trim from playhead" shortcuts; the main window owns those.
- The panel only **reads** the preview service; it never calls `refresh_estimate`. The service follows `Document` itself.
- The crop controls are not in this panel's `_blocked()` list; `CropPanel` blocks its own controls in its refresh.
- When adding a control, also call `_explain(widget, text)` with its range and the reason for it; `test_every_input_explains_its_limits` fails otherwise.
- Colours are inline hex (`#c77700`, `#c0392b`) chosen to read on both the light and dark Fusion palettes.

## Tests
- `tests/ui/test_settings_panel.py`: initial values; speed spin merging into one undo step; slider ↔ spin sync; undo restoring controls without pushing commands; "to end" ↔ `None`; start/duration clamping; FPS checkbox ↔ `None`/value; aspect lock (canvas and crop base), unlocked editing; scale and Reset; presets and switching to Custom; summary text and update after `delete_frames`; empty output disabling Generate; `ValueError` revert + message; `generateRequested` on click; disabled state after `close()` and for a Document with no source; (M4) `test_every_input_explains_its_limits`: every spin box, combo box, slider and button in the panel (except the crop panel's own and Generate) has a tooltip equal to its accessible description, and the FPS, colours and width tooltips name 50 / 20 ms, 256 and 8,192.
- `tests/ui/test_m3_integration.py` ([page](../../../tests/ui/test_m3_integration.md)): `format_bytes`; the Size line with and without a service; the crop panel is part of the panel and the summary shows the crop size; a crop error appears in the summary card.
- `tests/ui/test_main_window.py::test_window_fits_small_screen_and_generate_stays_visible`: in the window, Generate is outside the scroll area and fully visible on a 1280×680 screen.
- Gaps: visual layout/width inside a real `QScrollArea` is not asserted beyond `sizeHint()` (checked by hand at 1300×820 in M3); the wording of the tooltips (only their presence and key numbers); warning colour rendering is not checked; the "estimating…" line is not asserted.

## History
- Milestone 2: created (settings panel worker). Size equal to the base is stored as `None` so crop changes keep driving the output size.
- `3adb5bd` (M3): `preview=` keyword, `crop_panel` embedded below Output size, crop errors forwarded to the summary card, `format_bytes` and the Size line. See [dev log, Milestone 3](../../../../04-development-log.md#milestone-3-crop-and-live-preview).
- `39e533b` (M4): `_explain` tooltips + accessible descriptions on every input. `9361dd6` (M4): the main window pins `generate_button` outside the scroll area. See [dev log, Milestone 4](../../../../04-development-log.md#milestone-4-hardening).
