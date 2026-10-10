# `src/gif_editor/ui/inspector/timebar.py`

> A custom-painted horizontal timeline showing the source GIF's frames, the trim window with draggable green/red handles, deleted frames and the playhead. You seek and trim with it.

## Where it sits
- **Layer:** ui (Qt)
- **Used by:** the inspector panel (`ui/inspector/inspector.py`), which places it under the canvas.
- **Uses:** `ui/document.py` (`Document`: the only object it talks to), `core/timeline.py` (`start_times_ms`, `frame_at_time`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `TimeBar(doc, parent=None)` | class (`QWidget`) | The timeline widget. Fixed height 56 logical px, expanding width, `Qt.StrongFocus`, accessible name `"Timeline"`. |
| `TimeBar.x_for_time(ms) -> float` | method | Widget x (logical px) for a source time in ms. |
| `TimeBar.time_for_x(x) -> float` | method | Source time (ms) for a widget x, clamped to `[0, total]`. Inverse of `x_for_time`. |
| `TimeBar.handle_at(pos) -> 'in' \| 'out' \| None` | method | Which trim handle (if any) is under a point (8 px wide hit area). |
| `TimeBar.tooltip_text(x) -> str` | method | Hover text, e.g. `"0.45 s · frame 5 of 8"` (empty when nothing is open). |
| `TimeBar.sizeHint()` / `minimumSizeHint()` | method | 400×56 / 50×56. |
| `format_seconds(ms) -> str` | function | `1500 -> "1.5 s"`, `0 -> "0 s"`. Used for labels, tooltip and accessible description. |
| constants | module | `HEIGHT`, `MARGIN`, `HANDLE_HIT`, `MIN_TICK_GAP`, `MIN_LABEL_GAP`, `MIN_WINDOW_MS`, `NICE_STEPS_MS`, colours. |

Signals: `scrubbed(int)`: emitted with the source frame index on every seek caused by pressing/dragging on the track. Optional; the main path for other widgets is `doc.currentIndexChanged`.

Listens to: `doc.sourceChanged` (re-read delays, enable/disable), `doc.stateChanged` and `doc.currentIndexChanged` (repaint + accessible description).

## How it works

### Coordinate system
The x axis is **source time**, not frame index: a 500 ms frame is five times wider than a 100 ms frame. That matches how trimming works (`EditState.trim_start_ms` / `trim_duration_ms` are in source ms, see `core/timeline.py`).

```
x_for_time(t) = MARGIN + t / total * (width - 2*MARGIN)
```

`MARGIN` (8 px) is left on both sides so a handle sitting at t=0 or t=total still has its whole 8 px hit area inside the widget. The delays come from `doc.meta.delays_ms` (the *effective* delays, so 0/10 ms frames count as 100 ms). Frame start times (`start_times_ms`) and the list of boundaries (starts + total) are computed once on `sourceChanged` and cached, because `paintEvent` and snapping use them constantly.

### Painting (`paintEvent`)
All colours come from the widget's `QPalette` (Base = track, Mid = ticks/borders, WindowText = labels, Highlight = playhead), so it follows the Fusion light/dark theme. When the widget is disabled the Disabled colour group is used. All pens are **cosmetic** (`_pen()`), meaning their width is in device-independent pixels and is not scaled by transforms. At 150%/200% Windows scaling Qt scales the logical coordinates for us, and lines stay crisp.

Layers, bottom to top:
1. **Track**: a Base rectangle with a Mid border. If no GIF is open, the text "No GIF loaded" is drawn and painting stops.
2. **Frame segments**: when frames are on average ≥ 6 px wide, every other frame gets a faint fill so the segments are visible. Then a short tick goes at each frame boundary. Ticks closer than 3 px to the previously drawn one are skipped ("thinning"). Without that, a 1000-frame GIF would become a solid grey smear and cost time.
3. **Deleted frames**: consecutive deleted indices are merged into runs (`_runs`). Each run is filled with a light red tint plus a red `Qt.BDiagPattern` hatch. Merging keeps painting fast when hundreds of frames are deleted.
4. **Time labels**: the interval is the first of `NICE_STEPS_MS` (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 300 s) that puts labels at least 60 px apart. Labels that would be clipped by the right edge are skipped.
5. **Trim shading**: the areas left of the in point and right of the out point are covered with semi-transparent black.
6. **Playhead**: a 2 px Highlight line plus a small downward triangle at the *start time* of the current frame.
7. **Handles**: a 3 px vertical bar plus a 7×10 px grip "flag" that points into the trim window. In = green, out = red.
8. **Focus rect**: when the widget has keyboard focus, the style draws its standard focus frame (`PE_FrameFocusRect`).

### Mouse
- `mousePressEvent` (left button only) increments `_drag_counter` and builds a merge key `trim-drag-N`. If the press is on a handle (`handle_at`), a trim drag starts. Otherwise it is a **seek**: `doc.set_current_index(frame_at_time(delays, t))` is called and `scrubbed` is emitted.
- `mouseMoveEvent` continues the drag. With no drag active it only updates the hover cursor: `SizeHorCursor` over a handle, `PointingHandCursor` elsewhere. `setMouseTracking(True)` is what makes Qt deliver moves without a button held.
- `mouseReleaseEvent` just ends the drag. It does **not** re-apply the release position, because users often let go of Alt a moment before the mouse button, and that would re-snap a free drag.

**Why the merge key?** Every move during a handle drag calls `doc.set_trim(..., merge_key="trim-drag-N")`. `SetStateCommand` merges consecutive commands with the same key (Qt's `QUndoCommand.mergeWith`), so the whole drag becomes **one undo step**. A new press gets a new N, so two separate drags stay two steps. If a drag ends where it started, the merged command becomes obsolete and disappears from the stack.

**Trim rules** (`_drag_handle`, `_snap`):
- The in handle moves within `[0, out - 10 ms]` and the out point stays fixed in absolute time. If the duration was `None` ("to the end"), it stays `None`.
- The out handle moves within `[in + 10 ms, total]`. Reaching `total` sets the duration to `None`, so the trim keeps meaning "to the end" (see the Gate 1 decision on Duration).
- **Snapping**: by default the value snaps to the nearest frame boundary *inside the allowed range*. On an exact tie the earlier boundary wins. If no boundary fits (e.g. a window narrower than one frame), the clamped free value is used. Holding **Alt** (checked on each move event's modifiers) skips snapping, and the value is rounded to whole ms.

### Tooltip
`event()` handles `QEvent.ToolTip` (Qt sends it after the mouse rests) and shows `tooltip_text(x)`, which reports the time and 1-based frame number under the mouse. Computing it on demand avoids rebuilding a tooltip string on every mouse move.

### Keyboard
With focus (click or Tab, since `StrongFocus` is set): Left/Right steps one frame, Shift+Left/Right steps 10 frames, Home/End jump to the first/last frame. `Document.set_current_index` clamps the result. Any other key goes to the base class, so shortcuts still bubble up.

Inside the main window these keys are normally handled by the window's actions instead: `TimeBar` does not accept `ShortcutOverride`, so the window's Left/Right/Shift+Left/Right/Home/End shortcuts fire first (they call `Player.step`, which wraps at the ends, instead of clamping). The result is the same except at the first/last frame and with "Preview edits" on (then steps and Home/End stay within the kept frames). See [main_window](../main_window.md#invariants--gotchas).

### Accessibility
The accessible name is always `"Timeline"`. The accessible description is rebuilt on every state/frame change, e.g. `"Frame 3 of 8 at 0.2 s; trim 0.1 s to 0.6 s"`, with ` (end)` added when the duration is `None`. Screen readers can therefore announce the position and trim without needing to see the painting.

## Invariants & gotchas
- The widget never builds an `EditState` itself. It only calls `doc.set_trim` / `doc.set_current_index`, so undo and every other view stay consistent.
- The trim window is always at least `MIN_WINDOW_MS` (10 ms) wide, and in < out.
- `handle_at` returns `None` when nothing is open, so a disabled bar never starts a drag.
- Seeking is not an edit and is never on the undo stack.
- Performance: a 1000-frame GIF with 500 deleted runs paints in well under 30 ms. The work is O(frames) with cheap per-frame operations, and ticks are thinned. If GIFs with tens of thousands of frames ever show up, start the tick loop with a bisect at the left edge of the visible area.
- `qtbot.mouseMove` cannot pass keyboard modifiers. The tests send a hand-built `QMouseEvent` with `AltModifier` instead.
- If the state's trim start lies beyond the source end (possible for states made elsewhere), drawing clamps it to `total`.

## Tests
- `tests/ui/test_timebar.py`: mapping round-trip, seeking by click and drag, `handle_at`, snapping, Alt free drag, one-drag-one-undo-step, the out handle at the end giving `None`, in<out and the 10 ms minimum, cursor and tooltip text, keyboard, painting at widths 50/3000, a 1000-frame paint under 30 ms, no-source safety and refresh on source changes.
- Gap: the tooltip popup itself and the focus-rect pixels are not asserted (only that painting succeeds).

## History
- Milestone 2: first version. Snapping is the default because GIF frames are discrete, and Alt gives free ms precision for fine trims. One merge key per press makes drags undoable as one step.
