# `src/gif_editor/ui/crop_panel.py`

> The left-panel **Crop** group: an aspect preset plus X/Y/W/H spinboxes, Full image / Center / Reset buttons and a status line, kept in two-way sync with the crop rectangle on the canvas — all mirroring and editing `doc.state.crop`.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** `ui/settings_panel.py` — the orchestrator inserts it into the settings panel's root `QVBoxLayout` directly **below the existing "Output size" group** (`size_group`) and connects its `errorOccurred` signal into the summary card. Nothing else may host it.
- **Uses:** `ui/document.py` (`Document`: `state`, `apply`, `is_open`, `meta`, `sourceChanged`, `stateChanged`), `core/models.py` (`CropRect`, `EditState`), `core/render.output_dimensions` (the "size follows the crop/base" rule). The other end of the two-way sync is `ui/inspector/crop_item.py` (the draggable rectangle), which also writes `doc.state.crop`, but with its own per-drag merge key `"crop-drag-N"`; this panel never imports it.

> **Integration (done in `3adb5bd`):** `SettingsPanel` creates it as `self.crop_panel` between "Output size" and "Quality" and forwards `errorOccurred` into its summary card. The canvas `CropItem` is created by the main window, not by this widget.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `CropPanel(doc: Document, parent: QWidget \| None = None)` | class (`QWidget`) | The crop controls. Everything it shows comes from `doc`. |
| `CropPanel.errorOccurred` | signal `(str)` | A crop edit was rejected by `Document.apply` (`ValueError`). Carries the message; the host connects it into the summary card (mirrors `Filmstrip.errorOccurred` → `MainWindow.show_error`). |
| `CropPanel.last_error` | attribute `str \| None` | The last rejected crop message, or `None`. Cleared on the next successful `stateChanged` / `sourceChanged` / accepted edit. |
| `ASPECTS` | module `tuple[tuple[str, float \| None], ...]` | The combo entries in order (see below). |
| `TIMES` | module `str` | `"\u00d7"`, the multiplication sign (escaped so ruff's look-alike-character rule stays quiet). Reused in every status string and importable by tests. |

Child widgets are **public attributes** so tests can reach them:
`crop_group` (`QGroupBox`, checkable), `aspect_combo` (`QComboBox`), `x_spin`, `y_spin`, `w_spin`, `h_spin` (all `QSpinBox`), `full_button`, `center_button`, `reset_button` (`QPushButton`), `status_label` (`QLabel`).

There are **no public methods** beyond those inherited from `QWidget`: the widget is driven entirely by Qt signals (its own controls and `doc.stateChanged` / `doc.sourceChanged`). Other widgets must not read or write the child attributes; they talk to `Document` only.

Signals (Qt files): `errorOccurred(str)`: fires on every rejected crop edit, with the `ValueError` message verbatim. It does not fire for accepted edits. (The panel keeps the same message in `last_error` for tests that prefer polling.)

## How it works

### Layout
The widget is one checkable `QGroupBox` titled **"Crop"**, holding a `QFormLayout`:

| Row | Control | Notes |
|---|---|---|
| Aspect | `aspect_combo` | `QComboBox`, 7 entries (below) |
| X | `x_spin` | `QSpinBox`, suffix `" px"` |
| Y | `y_spin` | `QSpinBox`, suffix `" px"` |
| Width | `w_spin` | `QSpinBox`, suffix `" px"` |
| Height | `h_spin` | `QSpinBox`, suffix `" px"` |
| (spanning) | `full_button` \| `center_button` \| `reset_button` | one `QHBoxLayout` added as a form row |
| (spanning) | `status_label` | last form row (`form.addRow(widget)`), plain text |

All four spinboxes set `setKeyboardTracking(False)` (typing "20" applies on Enter/focus-out, not as "2" then "20"). Every control gets a `setAccessibleName` ("Crop aspect", "Crop x", "Crop y", "Crop width", "Crop height", "Crop: full image", "Crop: centre", "Crop: reset"). The panel itself is named **"Crop settings"** (M4, `d3f0297`): an accessibility audit found it, the inspector and the settings scroll area to be the only unnamed containers, so a screen reader had nothing to announce when entering the group. The widget sets no fixed width — it inherits the settings panel / scroll-area width (`setSizePolicy(Preferred, Preferred)`); it does **not** override `sizeHint`.

### The Aspect combo
`ASPECTS` is the exact and complete entry list, in this order:

| # | Label | `itemData` (float ratio `w/h`, or `None`) |
|---|---|---|
| 0 | `Free` | `None` — no constraint |
| 1 | `Original` | the **source canvas** ratio, `canvas_w / canvas_h` |
| 2 | `1:1` | `1.0` |
| 3 | `4:3` | `4 / 3` |
| 4 | `16:9` | `16 / 9` |
| 5 | `3:2` | `1.5` |
| 6 | `9:16` | `9 / 16` |

"Original" means the ratio of the loaded GIF's canvas (the full frame, **not** the current crop). Its `itemData` is written on every `sourceChanged` with `canvas_w / canvas_h` (via `setItemData`), because it depends on the open file; with no source open it stays `None` and the control is disabled. Concretely: `ASPECTS = (("Free", None), ("Original", None), ("1:1", 1.0), ("4:3", 4 / 3), ("16:9", 16 / 9), ("3:2", 1.5), ("9:16", 9 / 16))`, with index 1 patched at `sourceChanged`. `None` (Free) means "no constraint"; a float means "hold this ratio".

### The two directions of data flow
```mermaid
flowchart LR
    C[control signal<br/>valueChanged / clicked / toggled / activated] --> H[_on_*_edited]
    H -->|doc.apply(state.with_(crop=...), "Crop", merge_key)| D[Document]
    X[CropItem drag<br/>ui/inspector/crop_item.py] -->|"doc.apply(..., merge_key=crop-drag-N) on release"| D
    D -->|stateChanged| R[_refresh<br/>signals blocked]
    D -->|sourceChanged| F[_on_source_changed]
```

1. **Control → state.** Every edit builds `doc.state.with_(crop=<CropRect or None>)` and calls `doc.apply(new, "Crop", merge_key=...)`. Spinbox edits pass `merge_key="crop"` so holding an arrow or scrolling the wheel over a spinbox is **one** undo step. (A canvas drag is also one step, but through its own key `"crop-drag-N"`, so it never merges with a spinbox scrub.) The three buttons and the group checkbox pass `merge_key=None` (each click is its own step and can never merge into a preceding scrub).
2. **State → controls.** `doc.stateChanged` (our own edit, undo/redo, or a canvas drag) calls `_refresh()`, which rewrites every control from `doc.state` inside `_blocked()` — a context manager holding a `QSignalBlocker` on `aspect_combo`, all four spinboxes, `crop_group`, and the three buttons. Blocking is what stops a refresh (e.g. after undo) from re-entering the handlers and pushing a fresh command that would destroy the redo history.

### Refresh details (and the in-progress-text rule)
- `_set(spin, value)` sets a spinbox value **only when it differs** (the settings-panel helper of the same name). Because `setKeyboardTracking(False)` is on, digits the user has typed but not committed do *not* change `value()`, so a normal refresh cannot clobber them.
- As a second guard, `_refresh()` **skips any spinbox whose `lineEdit().isModified()` is `True`** (the user is mid-typing and has not pressed Enter). This makes an undo/redo that arrives while a spinbox has focus safe: the focused, dirty spinbox is left alone; every other control updates.
- `crop_group.setChecked(st.crop is not None)` is written **inside** the blocker, so mirroring the state cannot re-trigger the toggle handler.

### Edit rules (numbered, individually testable)
1. **Spinbox X edit** → keep W, Y, H; clamp `x` to `0 … canvas_w − w`; apply `CropRect(x, y, w, h)`.
2. **Spinbox Y edit** → keep X, W, H; clamp `y` to `0 … canvas_h − h`; apply `CropRect(x, y, w, h)`.
3. **Spinbox W edit** → keep Y, H and the **typed** W; if `x + w > canvas_w` then shift the origin: `x = canvas_w − w`; apply `CropRect(x, y, w, h)`. W is **never** reduced. (Justification: honouring the width the user typed stops the spinbox silently snapping back to a smaller number, and X always has room because `w ≤ canvas_w` by the spinbox range.)
4. **Spinbox H edit** → mirror of rule 3 on the vertical axis: keep X, W and the **typed** H; if `y + h > canvas_h` then shift the origin: `y = canvas_h − h`; apply `CropRect(x, y, w, h)`. H is **never** reduced.
5. **Invariant:** after every edit `x ≥ 0`, `y ≥ 0`, `w ≥ 1`, `h ≥ 1`, `x + w ≤ canvas_w` and `y + h ≤ canvas_h` hold. The handlers enforce this themselves; they do not rely on `CropRect.validate` to raise.
6. **Full-frame normalisation:** if the resulting rectangle equals `CropRect(0, 0, canvas_w, canvas_h)` it is stored as `crop=None` (see the full-frame rule below). Every handler applies this before calling `apply`.
7. **Aspect lock — W edit:** with a ratio `r` locked (`r` is the `itemData` of the current combo entry, not `None`), a W edit also sets `h = max(1, round(w / r))`, then rule 4's clamp runs. **H edit:** `w = max(1, round(h * r))`, then rule 3's clamp. Rounding is Python's `round` (nearest int, banker's rounding on exact `.5`), never below `1`.
8. **The aspect lock constrains manual edits only.** It is applied inside rules 7 only. It is **never** re-applied on `_refresh()` and never to a rectangle that arrives from a canvas drag. A drag may therefore leave a crop whose ratio differs from the locked entry; the panel shows the raw `doc.state.crop` values and leaves them. *Why acceptable:* the lock is a convenience for numeric entry; re-asserting it on every refresh would fight the pointer mid-drag and could make the rectangle jump. The user re-asserts the ratio by nudging a spinbox. The combo's selection is UI-only: it is **not** stored in `EditState`, is never changed by the state arriving from elsewhere, and stays where the user left it.
9. **Full image button** → set the rectangle to cover everything (`x=y=0`, `w=canvas_w`, `h=canvas_h`) and, per rule 6, store `crop=None`. `merge_key=None`. It leaves the Aspect combo as it was.
10. **Center button** → pick the size to centre: if `state.crop is not None` use `(crop.w, crop.h)`; else use the **current output size** `output_dimensions(canvas_w, canvas_h, None, state.size)` (i.e. `state.size` if set, else the canvas). Then `w=min(w, canvas_w)`, `h=min(h, canvas_h)`, `x=(canvas_w − w)//2`, `y=(canvas_h − h)//2`; store the result (rule 6 applies, so a full-size result stores `None`). `merge_key=None`.
11. **Reset button** → `crop=None`, set the Aspect combo back to `Free`, `merge_key=None`. (The only difference from "Full image": Reset also returns the combo to `Free`; both end with `crop=None` and an unchecked group.)
12. **Group checkbox** → checked ⇔ `state.crop is not None` (mirrored on `_refresh`). **Unchecking** clears the crop (`crop=None`, `merge_key=None`). **Checking** applies the *Center* rule (rule 10) as a default, so the box never sits "checked with no crop"; from an unchecked state that means the current output size, centred. If that centred default is the whole frame (no explicit size set), it would normalise to `None` and the tick would do nothing, so the panel instead creates a centred crop at **80% of the canvas** on each side. `merge_key=None` for both directions.

### The full-frame ("size follows crop/base") rule
`core.render.output_dimensions(canvas_w, canvas_h, crop, size)` returns the explicit `size` if set, else the crop's `W×H` if a crop is set, else the canvas `W×H`. So **`EditState.size is None` means "follow the crop (or the canvas when there is no crop)"**. A crop that covers the whole frame is therefore stored as `crop=None`, not as `CropRect(0, 0, W, H)`: the two are geometrically identical (`output_dimensions` gives the canvas either way), but `None` is the canonical "no crop" value that the status line, the checkbox and the settings panel's base-size logic all key on. Keeping it canonical is what stops a redundant full-frame crop from being confused with a real one.

### Interaction with the "Output size" group
- With `size is None` and a crop set, the output follows the crop: the summary card and `render.output_dimensions` both report the crop's `W×H`. This is automatic — the crop panel never touches `size`.
- Setting or changing a crop **never** modifies an explicit `size`. If the user has typed a size, the crop change leaves `state.size` exactly as it was, and the output keeps that explicit size. *Why:* an explicit size is a deliberate user decision; a crop change silently resizing the output would override it. Consequence to expect (not a bug): the "Output size" group's `scale_spin` display is `round(width / base_width × 100)` with the *new* crop as base, so its percentage can change even though the stored size did not.
- A crop that normalises to `None` (rule 6) likewise leaves `size` untouched.

### Status line
`status_label` (plain text) shows exactly one of:
- **Crop set:** `Crop {w}×{h} at {x},{y} · {p}% of the frame`, where `×` is `TIMES` and `p = round(100 * w * h / (canvas_w * canvas_h))` (the crop's area as a percentage of the canvas). Worked example on the test fixture (40×30, crop 20×15 at 10,7): `"Crop 20×15 at 10,7 · 25% of the frame"`.
- **No crop, source open:** `No crop (full frame {canvas_w}×{canvas_h})`.
- **No source open:** `No crop` (no dimensions are available).

### Enabled state
- **No source open:** `crop_group` is unchecked and disabled, `aspect_combo` / the four spinboxes / the three buttons are disabled, ranges collapse to X,Y `0…0` and W,H `1…1`, status is `No crop`. Every handler returns early when `doc.is_open` is `False`, so even a programmatically forced value change pushes nothing.
- **Source open, crop ticked:** all controls enabled; ranges are X `0…canvas_w−1`, Y `0…canvas_h−1`, W `1…canvas_w`, H `1…canvas_h` (set in `_on_source_changed`).
- **Source open, crop unticked:** the group box itself is enabled (you can tick it), but its children are greyed out. This is not code in this file: a *checkable* `QGroupBox` force-disables its children while unchecked, and that overrides an explicit `setEnabled(True)`. The result is the standard "tick to crop" behaviour: with no crop the numbers are read-only and show the full frame, and ticking the box creates a centred crop (rule 12).

### Errors
Every `doc.apply` goes through a `_try` wrapper (the settings-panel pattern). On `ValueError` (an invalid `CropRect` — e.g. a negative origin or a rectangle past the canvas, which the clamping normally prevents) the panel stores `last_error`, reverts every control to `doc.state` (nothing changed there — `apply` is atomic), and emits `errorOccurred(message)`. The host (settings panel) shows it in the summary card. The next successful `stateChanged` or `sourceChanged` clears `last_error`.

## Invariants & gotchas
- **Every** programmatic write to a control happens inside `_blocked()`; otherwise an undo/redo would push new commands and corrupt the redo history.
- When adding a control, add it to the `_blocked()` list, connect it in `_connect_controls`, mirror it in `_refresh`, and give it a merge key (spinboxes `"crop"`, discrete actions `None`).
- The panel mirrors `crop_group.checked` from `state.crop`; the two can never disagree after a refresh. Checking the box is the only way the panel fabricates a default crop (rule 12).
- Merge keys: spinboxes use `"crop"`; `ui/inspector/crop_item.py` uses a per-drag key `"crop-drag-N"`. `commands.py` merges *any* consecutive commands with the same key, so sharing one key would have merged a canvas drag with the spinbox nudge that follows it. Separate keys keep them as separate undo steps.
- "Full image" and "Reset" both end at `crop=None`; they differ only in the Aspect combo (Reset returns it to `Free`) and in the undo `text`. They are deliberately near-aliases.
- The aspect lock is UI-only, exactly like "Lock aspect" in the Output size group: it is not part of `EditState`, is not undoable, and is never inferred from the state.
- The status percentage uses the canvas area as the denominator; it is a fraction of the full frame, not of the current crop.
- The panel never decodes pixels and never runs off the GUI thread; it is pure arithmetic over `EditState`, so it is cheap on every `stateChanged`.

## Tests
- `tests/ui/test_crop_panel.py`: initial values; each spinbox → `CropRect`; clamping (X/Y shift, W/H never shrink); aspect lock W↔H with rounding and Original; the lock not re-applied on refresh/drag; undo merging of a spinbox scrub vs a discrete button; undo/redo refreshing controls without pushing commands; canvas → panel sync; Full image / Center / Reset; the checkbox semantics; the disabled no-source state; the status strings; and `ValueError` surfacing via `last_error` / `errorOccurred`. Full checklist: [`tests/ui/test_crop_panel.md`](../../../tests/ui/test_crop_panel.md).
- Gaps: no pixel/visual check of the layout, the disabled-grey look or the group's collapse rendering; no real HiDPI check (M4).

## History
- Written as the **Milestone 3 specification by a docs worker** before any code existed.
- Implemented by the orchestrator from this page, with two decisions the spec left open:
  1. **Merge keys.** Spinboxes use `"crop"`; the canvas `CropItem` uses a per-drag key `"crop-drag-N"` (like the timebar's `"trim-drag-N"`), so a spinbox nudge right after a drag stays a separate undo step. This resolves the warning in *Invariants & gotchas*.
  2. **Ticking with a full-frame default** creates an 80% centred crop instead of doing nothing (rule 12).
- Documented deviation from the spec: inputs are greyed out while the group is unticked (Qt behaviour, see *Enabled state*).
- `d3f0297` (M4): `setAccessibleName("Crop settings")` on the panel ([dev log, Milestone 4](../../../../04-development-log.md#milestone-4-hardening)). Its tooltips are its own; the settings panel's `_explain` texts (M4) do not cover the crop inputs.
