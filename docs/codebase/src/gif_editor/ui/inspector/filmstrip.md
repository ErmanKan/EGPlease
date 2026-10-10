# `src/gif_editor/ui/inspector/filmstrip.py`

> The horizontal thumbnail strip under the canvas: one cell per **source** frame, with lazily loaded thumbnails, multi-select, Delete/Restore, and a context menu for trimming.

## Where it sits
- **Layer:** ui (Qt: `QAbstractListModel`, `QStyledItemDelegate`, `QListView`)
- **Used by:** the inspector panel / `MainWindow` (orchestrator), which places the `Filmstrip` and connects `errorOccurred` to a message box or status bar. `tests/ui/test_filmstrip.py`.
- **Uses:** `ui/document.py` (`Document`: the only object it talks to), `ui/workers.py` (`run_async`), `ui/qt_image.py` (`pil_to_qimage`), `core/timeline.py` (`start_times_ms`), `core/decoder.py` indirectly (`GifSource.thumbnail` through `doc.source`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `THUMB_MAX_SIDE = 96` | constant | Longest side (px) requested from `GifSource.thumbnail`. Larger than the 80 px paint box, so it stays sharp at 120 % scaling. |
| `BATCH_SIZE = 32` | constant | Thumbnails decoded per worker job. |
| `PREFETCH_MARGIN = 16` | constant | Rows beyond the visible range that are loaded as well. |
| `FrameListModel(doc, parent=None)` | class | List model, one row per source frame. |
| `FrameListModel.DeletedRole` | role (`UserRole+1`) | `bool`: the frame is in `state.deleted`. |
| `FrameListModel.InTrimRole` | role (`UserRole+2`) | `bool`: the frame is visible somewhere inside the trim window. |
| `rowCount(parent=QModelIndex())` | method | `meta.frame_count`, or 0 when nothing is open. |
| `data(index, role)` | method | `DisplayRole` → `'#3\n100 ms'`; `DecorationRole` → thumbnail `QPixmap` or grey placeholder; `ToolTipRole` → `'Frame 3 · starts 0.20 s · delay 100 ms'` + `' · deleted'` / `' · outside trim'`; plus the two custom roles. |
| `generation` | property | Counter bumped on each `sourceChanged`. Worker jobs carry it; results with an old value are dropped. |
| `is_loading` | property | A thumbnail batch is running on a worker. |
| `has_thumbnail(row)` | method | The real thumbnail of `row` is cached (not the placeholder). |
| `in_trim(row)` | method | Same as `InTrimRole`. |
| `frame_start_ms(row)` | method | Source start time of the frame (ms). |
| `placeholder()` | method | Grey pixmap with the thumbnail's size/aspect ratio. |
| `set_visible_rows(first, last)` | method | Called by the view: these rows are on screen; load them (and the margin) first. |
| `on_thumbnails_loaded(generation, results)` | method | GUI-thread callback for a finished batch: `results = [(row, QImage | None)]`. Public so tests can simulate a stale result. |
| `FrameDelegate(parent=None)` | class | Paints one cell (see "Painting"). |
| `Filmstrip(doc, parent=None)` | class | The `QListView`. Accessible name `'Frame strip'`. |
| `Filmstrip.frame_model` | property | Its `FrameListModel`. |
| `selected_rows()` | method | Selected source indices, or `{doc.current_index}` if nothing is selected. |
| `delete_selected()` | method | `doc.delete_frames(selected_rows())`; a `ValueError` becomes `errorOccurred`. |
| `restore_selected()` | method | `doc.restore_frames(selected_rows())`. |
| `set_trim_start_at(row)` | method | Trim start = the frame's start time; the trim **end** stays where it was. |
| `set_trim_end_at(row)` | method | Trim duration = frame end − trim start; `None` for the last frame. |
| `build_context_menu(row=None) -> QMenu` | method | Builds (does not show) the menu for `row` (default: the current frame). |

Signals: `Filmstrip.errorOccurred(str)`: an edit was refused (deleting every frame, or a trim end before the trim start). The main window shows the message; the strip never opens dialogs itself.

## How it works

### Qt model/view in two sentences
A `QListView` does not store data. It asks a *model* (`FrameListModel`) "how many rows?" and "what is the value of role R in row N?", and asks a *delegate* (`FrameDelegate`) to paint each cell. The model tells the view when something changed with `dataChanged` (some rows) or `beginResetModel`/`endResetModel` (everything).

### The model
1. **Rows** come from `doc.meta.frame_count`. Start times are pre-computed once per file with `timeline.start_times_ms(meta.delays_ms)`, so tooltips and `InTrimRole` are O(1).
2. **Delays shown** are `effective_delay_ms` (0/10 ms → 100 ms), the same numbers `plan_output` uses.
3. **`InTrimRole`** uses the exact overlap rule of `timeline._trim`: the window is `[trim_start, min(trim_start + duration, total))` (or to the end when `duration is None`) and a frame `[start, start + delay)` is in it if `max(starts) < min(ends)`. So a frame that is only partly inside the window counts as in trim, exactly like in the output.
4. **`sourceChanged`** → full model reset: bump `generation`, clear the pixmap cache, the failed/requested/loading sets and the placeholder, reload rows.
5. **`stateChanged`** → one `dataChanged(first, last)` for all rows. Cheap: deleted/trim flags are computed on demand, no thumbnail is touched.

### Lazy thumbnails
```mermaid
sequenceDiagram
    participant V as Filmstrip (view)
    participant M as FrameListModel
    participant W as worker thread (run_async)
    V->>M: set_visible_rows(first, last)   (scroll / resize / reset)
    V->>M: data(row, DecorationRole)        (while painting)
    M-->>V: placeholder pixmap; row added to _requested; _kick timer (0 ms)
    M->>M: _schedule(): ≤32 rows, nearest the visible centre first
    M->>W: run_async(work)  [carries generation g]
    W->>W: source.thumbnail(i, 96) → pil_to_qimage   (no QPixmap!)
    W-->>M: on_thumbnails_loaded(g, [(row, QImage)])  (GUI thread)
    M->>M: g == generation? else drop. QPixmap.fromImage → _cache
    M-->>V: dataChanged(row, row, [DecorationRole]) → repaint
    M->>M: _kick again → next batch if rows are still wanted
```
- **Why batches of ~32?** One job per frame would flood the thread pool and the event queue on a 10 000-frame GIF; one job for everything would make the first visible thumbnails wait for the whole file.
- **Why one batch at a time?** The visible range changes while the user scrolls. By picking the next batch only when the previous one is done, the *current* visible range always gets priority.
- **Which rows?** The visible range plus `PREFETCH_MARGIN` on each side, plus rows that `data()` was asked for. Requests more than `4 × PREFETCH_MARGIN` rows away from the visible range are forgotten, so a fast scroll does not decode everything it flew past.
- **QImage vs QPixmap.** `QImage` is plain memory and may be built on any thread; `QPixmap` lives in the GUI system and must be created on the GUI thread. So the worker returns `QImage`s and the callback converts them.
- **Generation counter.** A batch for file A can finish after file B was opened. Each job remembers the `generation` it was started with; `on_thumbnails_loaded` drops results whose generation is old, so A's pictures never appear in B's rows.
- **Plain dict cache**, not `QPixmapCache`: `QPixmapCache` is global and size-limited, so entries could vanish silently and other widgets could evict ours. A dict tied to the model is predictable and is cleared on `sourceChanged`. Memory: 96×72 RGBA ≈ 27 KB per frame.
- **Failures.** A frame that cannot be decoded (or a source closed mid-job) is recorded in `_failed` and keeps the placeholder; it is not retried in a loop.
- **The model may be deleted while a job runs** (window closed). The callbacks check `shiboken6.isValid(self)` before touching it.

### The view (`Filmstrip`)
- **Layout:** `IconMode` + `LeftToRight` flow + `setWrapping(False)` (IconMode wraps by default) = a single horizontal row. `Movement.Static` and `NoDragDrop` stop IconMode's default "drag items around". `setUniformItemSizes(True)` lets Qt lay out thousands of items without asking each one for its size. `ScrollPerPixel` gives smooth scrolling. Fixed height 140 px: cells are 120 px tall, which leaves room for the horizontal scroll bar.
- **Selection → doc:** `selectionModel().selectionChanged` → `doc.set_selection(rows)`. **doc → selection:** `doc.selectionChanged` → select those rows. A `_syncing` flag stops the ping-pong.
- **Current item ↔ doc:** `selectionModel().currentChanged` → `doc.set_current_index(row)`; `doc.currentIndexChanged` → `setCurrentIndex(..., NoUpdate)` + `scrollTo(EnsureVisible)`. `NoUpdate` is deliberate: when the player or the timebar moves the playhead, the selection must not change (otherwise playback would keep replacing what the user selected).
- **Delete with an empty selection** falls back to the current frame (`selected_rows()`), so "delete the current frame" works without clicking first.
- **Keys:** Delete/Backspace → `delete_selected()`; Ctrl+Shift+Delete or Insert → `restore_selected()`; everything else (Left/Right, Home/End, Shift+arrows) is native `QListView` behaviour, and the resulting current-item change syncs to the doc. The view also accepts `ShortcutOverride` for Delete/Backspace/Insert so that a window-level `QAction` with the same shortcut does not steal the key while the strip has focus.
- **Context menu:** `contextMenuEvent` makes the clicked frame current (and selects it if it was not already part of the selection, like file managers do), then `build_context_menu(row).exec(...)`. The menu itself is built by a public method so tests can trigger its actions without a real popup.
  - *Delete frame(s)* is enabled if any target frame is not deleted; *Restore frame(s)* if any is deleted.
  - *Set trim start here* / *Set trim end here* call `doc.set_trim(..., merge_key=None)` so each click is its own undo step. Setting the start keeps the existing end (the duration is recomputed; if the end would be before the new start, the duration becomes `None` = to the end). Setting the end on the last frame gives `None` so the trim follows the GIF's end; an end at or before the trim start emits `errorOccurred`.
- **Visible range:** reported to the model on scroll, resize and model reset (plus once more after the layout pass via a 0 ms timer, because right after a reset the cells have no geometry yet).
- **Empty state:** when `doc.is_open` is False the model has 0 rows and the view is disabled.

### Painting (`FrameDelegate`)
1. Background via the style's `PE_PanelItemViewItem` (selection/hover look of Fusion).
2. The thumbnail fitted into an 80×80 logical box (aspect kept, smooth scaling). Outside the trim → opacity 0.4; deleted → opacity 0.3.
3. Deleted → grey wash, red diagonal strike (2 px **cosmetic** pen, i.e. 2 device-independent pixels at any zoom), and a small red "deleted" label.
4. Text `#N` / `delay ms` under the thumbnail, faded for deleted/out-of-trim frames.
5. The current frame (`view.currentIndex()`) gets a 2 px highlight-colour border.
All coordinates are logical pixels; Qt scales them on HiDPI screens.

## Invariants & gotchas
- Rows are **source** frames, never output frames. Deleted frames stay in the list (greyed) so they can be restored.
- Never create `QPixmap` in `work()`; only in `on_thumbnails_loaded` (GUI thread).
- `on_thumbnails_loaded` must keep ignoring old generations; tests rely on calling it directly.
- Only rows covered by a result leave the "loading" set; `is_loading` becomes False when none are left.
- The view must stay the only object that changes the selection model; the model never touches selection.
- In pytest-qt, widgets registered with `qtbot.addWidget` are `deleteLater()`'d **before** fixture teardown runs, so a fixture must not poll the widget in its teardown (see the test page).
- Ctrl+Shift+Delete is checked before plain Delete; plain Delete requires no Ctrl/Shift.

## Tests
- `tests/ui/test_filmstrip.py`: row count and roles, thumbnail loading (pixel colour), placeholder aspect, selection and current-index sync both ways, Delete/Backspace/restore keys and undo, delete-all error, context-menu actions (delete/restore/select all/trim start/trim end), `InTrimRole`, stale-generation results, empty document, close, painting with every state.
- Gaps: scroll-driven prioritisation (which batch loads first) and the right-click `contextMenuEvent` popup itself are not tested (popups block in offscreen tests).

## History
- Milestone 2 (filmstrip worker): first version. Decisions: one batch in flight at a time; `NoUpdate` when following the playhead; Delete falls back to the current frame; "Set trim start here" keeps the trim end.
