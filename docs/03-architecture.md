# 03 — Architecture (the code as it is today)

This page describes the code on `main` as of the end of Milestone 2 (window and inspector). For the *intended* design see [02-plan.md](02-plan.md); for how we got here see [04-development-log.md](04-development-log.md). Every file has its own page under [codebase/](codebase/INDEX.md).

## 1. Layers

```mermaid
flowchart TB
    subgraph UI["ui/ (PySide6, GUI thread)"]
        MW["MainWindow<br/>menus · shortcuts · open · Generate · Save frame"]
        W["widgets<br/>settings panel · canvas · timebar · filmstrip · transport · player"]
        DOC[Document<br/>hub: source, EditState, undo, current frame, selection]
        CMD[SetStateCommand<br/>QUndoStack]
        WK[run_async<br/>QThreadPool]
        QI[qt_image<br/>PIL → QImage]
    end
    subgraph CORE["core/ (pure Python + Pillow + numpy, no Qt)"]
        MOD[models<br/>EditState]
        DEC[decoder<br/>GifSource]
        TL[timeline<br/>plan_output]
        REN[render<br/>crop · resize · palette · quantize]
        ENC[encoder<br/>write_gif]
        PIPE[pipeline<br/>plan · summarize · generate · export PNG]
        ST[selftest]
    end
    MW -->|composes, wires actions| W
    MW -->|set_source · close · undo_stack| DOC
    W -->|calls / signals| DOC
    MW --> WK
    DOC --> CMD
    W --> WK
    W --> QI
    DOC --> PIPE
    PIPE --> TL & REN & ENC & DEC
    TL --> MOD
    ST --> ENC & DEC
```

- **core** is a headless GIF engine. It has no Qt imports (an AGENTS.md rule), so it is fully unit-testable and could back a CLI. It depends only on Pillow and numpy. Pillow is used narrowly: LZW decode/encode, quantisation, resizing, and PNG writing.
- **ui** is PySide6. Widgets talk **only** to `Document`; the main window composes them and wires menu actions to them (§9). Long work goes through `run_async`.

## 2. Directory tree

```
gif-editor/
├─ AGENTS.md                      contributor contract: rules, commands, interfaces, definition of done
├─ README.md                      short intro + Windows dev commands
├─ pyproject.toml                 pins, pytest config (pythonpath src+tests), ruff config
├─ requirements.txt               runtime pins (mirror of pyproject)
├─ requirements-dev.txt           runtime + pytest, pytest-qt, ruff
├─ .gitignore                     venv/caches/build output, .devlibs/, scratch
├─ .github/workflows/ci.yml       Windows CI: ruff + pytest (offscreen Qt)
├─ scripts/
│  ├─ test.sh                     lint + all tests headlessly in the Linux container
│  └─ fetch-devlibs.sh            fetch + SHA-check + unpack libegl1 into .devlibs/
├─ packaging/licenses/            (empty, M5: licence texts)
├─ src/gif_editor/
│  ├─ __init__.py                 package docstring + __version__
│  ├─ __main__.py                 `python -m gif_editor` → app.main()
│  ├─ app.py                      main(): QApplication, Pillow self-test, MainWindow, optional path arg
│  ├─ resources/icons/            (empty; buttons use Qt standard icons)
│  ├─ core/
│  │  ├─ __init__.py              package marker ("no Qt")
│  │  ├─ models.py                EditState, CropRect, OutputSize, Quality (immutable)
│  │  ├─ decoder.py               GifSource: block parser, numpy compositor (browser disposal), LRU + checkpoints
│  │  ├─ timeline.py              plan_output(): trim → delete → speed → fps → min delay → cs rounding → split
│  │  ├─ render.py                crop, premultiplied LANCZOS resize, shared palette, quantize (anti-shimmer)
│  │  ├─ encoder.py               write_gif(): own container, lossless diff frames, atomic, progress/cancel/verify
│  │  ├─ pipeline.py              plan/summarize/generate/export_frame_png glue
│  │  └─ selftest.py              round trip through the Pillow internals we depend on
│  └─ ui/
│     ├─ __init__.py              package marker
│     ├─ document.py              Document: the hub every widget talks to
│     ├─ commands.py              SetStateCommand (old → new EditState, gesture merging)
│     ├─ workers.py               run_async(): QThreadPool + GUI-thread callbacks
│     ├─ qt_image.py              pil_to_qimage(), checkerboard_brush()
│     ├─ settings_panel.py        SettingsPanel: timing/size/quality, live summary, Generate button
│     ├─ main_window.py           MainWindow: layout, actions/shortcuts, open, Generate, Save frame
│     └─ inspector/
│        ├─ __init__.py           package marker
│        ├─ canvas.py             FrameCanvas: zoomable/pannable frame view, deleted overlay
│        ├─ timebar.py            TimeBar: playhead, ticks, snapping trim handles
│        ├─ filmstrip.py          Filmstrip: lazy thumbnails, selection, delete/restore, trim menu
│        ├─ transport.py          TransportBar: play/step buttons, preview toggle, frame info
│        ├─ player.py             Player: drift-free playback timer (QObject, no widget)
│        └─ inspector.py          Inspector: composes the right panel
└─ tests/
   ├─ conftest.py                 session corpus fixtures (no Qt)
   ├─ gifgen.py                   simple GIFs via Pillow
   ├─ corpus.py                   raw GIF89a writer + reference compositor + 13 entries
   ├─ core/test_*.py              one per core module + corpus tests
   └─ ui/conftest.py, test_*.py   pytest-qt tests: foundation, one file per widget, main-window integration
```

## 3. End-to-end data flow: open → edit → preview → generate

```mermaid
sequenceDiagram
    actor U as User
    participant MW as MainWindow
    participant WK as run_async (pool thread)
    participant D as Document (GUI)
    participant V as Widgets
    participant C as core

    U->>MW: Open file
    MW->>WK: GifSource.open(path)
    Note over WK,C: read file into memory, parse blocks,<br/>composite every frame once, fill cache
    WK-->>MW: on_done(source) (GUI thread)
    MW->>D: set_source(source, path)
    D-->>V: sourceChanged, stateChanged, currentIndexChanged, selectionChanged

    U->>V: drag trim handle / change speed / delete frame
    V->>D: set_trim(...) / apply(state.with_(...)) / delete_frames(...)
    D->>D: validate, push SetStateCommand
    D-->>V: stateChanged(new_state)
    V->>D: summary() → pipeline.summarize → timeline.plan_output
    V-->>U: "Frames 120 → 61 · 3.2 s · 480×270"

    U->>V: scrub / play
    V->>D: set_current_index(i)
    D-->>V: currentIndexChanged(i)
    V->>WK: source.frame(i) or thumbnail(i) → pil_to_qimage
    WK-->>V: QImage → QPixmap (GUI thread) → paint

    U->>MW: Generate
    MW->>WK: pipeline.generate(source, state, out, progress, cancel)
    Note over WK,C: plan → shared palette → per frame:<br/>frame(i) → crop → resize → quantize → diff-encode → temp file<br/>→ read back + verify → os.replace
    WK-->>MW: on_progress(done, total) …, on_done(GenerateResult) / on_error
```

The **same** `timeline.plan_output` result drives the summary, the (M3) edited preview and Generate. That is why the preview can be guaranteed to match the output. Inside Generate, per frame:

```mermaid
flowchart LR
    TL[TimelinePlan<br/>src_index, delay_cs] --> F["source.frame(src_index)<br/>RGBA, cached"]
    F --> CR[crop] --> RS[resize<br/>premultiplied LANCZOS] --> Q[quantize onto<br/>shared Palette<br/>+ previous]
    Q --> E[_Writer.add<br/>diff vs previous frame] --> T[(temp file)]
    T --> VF[verify: frame count + durations] --> R[os.replace → out.gif]
```

## 4. EditState, Document and undo

- `EditState` (core/models.py) is a **frozen dataclass** holding every edit: trim, deleted frames, crop, speed, fps, size, quality. Edits produce new states (`state.with_(...)`), never mutate.
- `Document.apply(new, text, merge_key)` is the **only** way to change it:
  1. no-op if `new == state`;
  2. `new.validate(w, h, n)` against the open source; a `ValueError` changes nothing;
  3. push `SetStateCommand(doc, old, new, text, merge_key)`. Qt immediately calls `redo()`, which calls `doc._set_state_raw(new)`, which emits `stateChanged(new)`.
- Undo/redo swap whole states. Because states are values, **one** command class covers every edit type.
- **Gesture merging:** consecutive commands with the same `merge_key` (e.g. `"trim"` while dragging) merge into one undo step. If the gesture ends where it started, the step is dropped (`setObsolete`).
- **View state** (current frame, selection) lives in `Document`, but not in `EditState` and not on the undo stack.

See the [Document page](codebase/src/gif_editor/ui/document.md) for the sequence diagram and the [commands page](codebase/src/gif_editor/ui/commands.md).

## 5. Threading model

| Thread | Does | Must not |
|---|---|---|
| GUI thread | all widgets, `Document`, undo stack, `QPixmap` creation, painting, `summarize()` (cheap), the canvas's `source.frame(i)` (a cache hit for typical GIFs), Save frame's `export_frame_png` (one frame) | block more than about 16 ms: no `GifSource.open`, no `generate`, no bulk decoding |
| Pool threads (`QThreadPool.globalInstance()` via `run_async`) | `GifSource.open` (main window), `thumbnail()` batches + `pil_to_qimage` (filmstrip), `generate` (main window) | touch widgets or `Document`, create `QPixmap` |

- `run_async(fn, *, on_done, on_error, on_progress, pool=None)` creates a `_Relay` QObject **on the calling (GUI) thread**. The worker emits its signals, and Qt queues them back to the GUI thread. Call it only from the GUI thread.
- `GifSource` is **thread-safe**: one lock per source guards decoding and the cache. `frame()` returns copies. Concurrent requests on one source are serialised, not parallel.
- **Cancellation** is cooperative: pass a `threading.Event` to `generate(..., cancel=ev)`. The encoder checks it between frames and before committing, and raises `encoder.Cancelled`, which arrives as `on_error`.
- Results come back in completion order. Widgets must ignore stale results (e.g. a thumbnail for a frame no longer needed, or a source that has since been closed).

## 6. Where each plan decision is implemented

### Timing model (`docs/02-plan.md` §2) → `core/timeline.py`
| Plan step | Code |
|---|---|
| 1. Trim in source time, synced with handles | `timeline._trim` (frames overlapping the window are kept and clipped); `Document.set_trim` |
| 2. Delete removes time | `plan_output` (filter by `state.deleted`); `Document.delete_frames`/`restore_frames` |
| 3. Speed divides delays | `plan_output` (`d / speed`); range in `models.MIN_SPEED`/`MAX_SPEED` |
| 4. FPS resample on a uniform grid, ≤ 50 and ≤ source rate, drop only | `timeline._resample`; `models.MAX_FPS`; the early return when the source is already slower |
| 5. Round to cs with carried error, ≥ 20 ms, warnings | `timeline._enforce_min_delay` + `timeline._round_cs`; warnings in `TimelinePlan.warnings` |
| 6. Output duration derived, read-only | `TimelinePlan.duration_ms` → `pipeline.Summary.duration_ms` |
| 7. Geometry crop → resize → quantize | `render.render_frame` + `render.quantize` via `pipeline.iter_output_frames` |
| (added) GIF max delay 655.35 s | split in `plan_output` |

### Other decisions
| Decision | Code |
|---|---|
| Source delays 0/10 ms → 100 ms | `decoder._effective_delay`, `FrameMeta.effective_delay_ms`, `SourceMeta.delays_ms` |
| Correct disposal + transparency on load (browser semantics) | `decoder._Compositor` |
| Transparency preserved; alpha < 128 → transparent | `render.ALPHA_THRESHOLD`, `pipeline.output_palette(transparent=meta.has_transparency)`, `encoder._Writer` |
| Loop: keep source behaviour | `pipeline.generate(loop=meta.loop)`, `encoder._write_header` |
| Safe write (temp + rename), progress, cancel, verify | `encoder.write_gif`, `pipeline._verifier` |
| Save current frame as PNG (original or edited) | `pipeline.export_frame_png(state=None|state)` via `MainWindow.save_frame_to` |
| Live summary | `pipeline.summarize` (exact), shown by the settings panel; a file-size estimate (`encoder.estimate_size`) is unused until M3 |
| Large GIFs / RAM | `decoder.Limits`, `_FrameCache` (LRU + pinned checkpoints ≤ ¼ budget) |
| Fast backward scrubbing | keyframe checkpoints + `_resume_point` |
| Pillow pinned, internals checked | `pyproject.toml` pins, `core/selftest.py` |

## 7. Error handling and limits

| Situation | Behaviour | Where |
|---|---|---|
| Missing file, not a GIF, unreadable | `GifLoadError` with a user-presentable message | `GifSource.open`, `_read_header` |
| Canvas > 2 × `Image.MAX_IMAGE_PIXELS` (≈ 179 Mpx) or side > 8192 | `GifLoadError` | `_parse` |
| Any frame side > 8192, area > 2 × MAX_IMAGE_PIXELS, or area > max(4 × canvas, 16 Mpx) | `GifLoadError` for the whole file (decompression-bomb guard) | `_check_frame_size` |
| More than 10 000 frames | `GifLoadError` | `_parse` |
| Truncated mid-frame / junk after frames / no trailer | load what is complete, add to `GifSource.warnings` | `_parse` |
| Short/corrupt LZW in a complete frame | keep the decoded pixels, warning | `_decode_indices` |
| Frame data undecodable during load | frame 0 → `GifLoadError`; later → stop there, warning | `GifSource._index` |
| Cache memory | ≤ `cache_budget_bytes` (512 MiB default), checkpoints ≤ ¼ of it | `_FrameCache` |
| Invalid edit values | `ValueError` from `EditState.with_` / `validate`; `Document.apply` pushes nothing | `models.py`, `document.py` |
| Delete every frame | `ValueError` from `Document.delete_frames` | `document.py` |
| Edits leave no frames (trim + deletes) | empty `TimelinePlan` with a warning; `generate` raises `ValueError("nothing to generate: …")` | `timeline.plan_output`, `pipeline.generate` |
| Speed/FPS/delays not exactly representable | warnings ("N frames dropped", "Delays rounded", "Long frame split") | `timeline.plan_output` |
| Cancel | `encoder.Cancelled`; temp file deleted; destination untouched | `write_gif` |
| Any error during writing | temp file deleted, exception re-raised, destination untouched | `write_gif` |
| Output doesn't read back as planned | `RuntimeError("written GIF failed verification…")`, destination untouched | `pipeline._verifier` |
| Pillow internals changed | `SelfTestError` → "Startup self-test failed" dialog, exit code 1, before any window | `core/selftest.py`, `app.main` |
| Worker exception | `on_error(message, exc)` on the GUI thread + traceback on stderr | `ui/workers.py` |
| Open fails (any exception) | non-blocking "Open failed" box + `last_error`; the previous document stays open | `MainWindow.open_file` |
| Generate fails / cancelled | "Generate failed" box, or a status-bar "cancelled" message; destination untouched | `MainWindow.generate_to` |
| Edit refused by a widget (delete all, trim end before start) | `Filmstrip.errorOccurred` / `show_error`; settings panel shows it in its summary card | `filmstrip.py`, `settings_panel.py`, `main_window.py` |

## 8. Extension points: adding a new edit type end to end

Example: a hypothetical *Reverse* toggle (play frames backwards). The same steps apply to any edit.

1. **Model** (`core/models.py`): add a field with a no-op default (`reverse: bool = False`) and validate it in `_validate_fields`, plus `validate()` if it depends on the source. The default must keep `EditState()` the identity. Add cases to `tests/core/test_models.py`.
2. **Decide which stage owns it:**
   - **Which frames / how long** → `core/timeline.py`. This is the *only* place allowed (AGENTS.md). For Reverse: reverse the kept list after trim/delete and before speed. Document the step in the module docstring's numbered list, and add table and property tests to `test_timeline.py`. Preview, summary and Generate pick it up automatically.
   - **Per-frame pixels** (e.g. rotate, a filter) → `core/render.py` `render_frame` (keep the order crop → … → resize, or document a new order). Then `output_dimensions` if the size changes. `pipeline.render_output_frame` is shared with the preview, so they stay in sync.
   - **Palette/colour** → `render.build_palette`/`quantize` via `Quality` or a new field.
   - **Container-level** (e.g. a loop override) → `pipeline.generate` arguments to `encoder.write_gif`.
3. **Summary:** if it changes the size or frame count, check that `pipeline.summarize` reflects it (it does if you used the stages above).
4. **UI:** add a control in the owning widget (settings panel for global options). On change: `doc.apply(doc.state.with_(reverse=v), "Reverse", merge_key=None)`; use a `merge_key` for continuous controls. Update the control from `stateChanged` (block its own signals while doing so, to avoid feedback loops), so undo/redo moves the control too.
5. **Tests:**
   - core: unit tests for the stage, plus an end-to-end case in `test_pipeline.py` (generate → `read_back` matches `plan`);
   - UI: a pytest-qt test that the control calls `apply`, and that undo restores it.
6. **Docs:** update the module page(s), this page's table in §6 if it is a plan decision, the AGENTS.md interface block (orchestrator), and the INDEX line if a file was added.

## 9. M2 UI structure

### Widget tree and ownership
```mermaid
flowchart TB
    MW["MainWindow (QMainWindow)<br/>owns Document + Player · actions · dialogs"]
    SP["QSplitter (horizontal)"]
    SA["QScrollArea"]
    SET["SettingsPanel"]
    INS["Inspector (QVBoxLayout)"]
    CV["FrameCanvas (stretch 1)"]
    TR["TransportBar"]
    TB["TimeBar"]
    FS["Filmstrip"]
    DOC[("Document (QObject)")]
    PL[("Player (QObject, no widget)")]
    MW --> SP
    SP --> SA --> SET
    SP --> INS
    INS --> CV & TR & TB & FS
    MW -. owns .-> DOC
    MW -. owns .-> PL
    TR -. drives .-> PL
```
- `MainWindow` creates the one `Document` and the one `Player`, then the `SettingsPanel` (inside a `QScrollArea`, so it scrolls instead of being squashed) and the `Inspector`, which builds its four children with the same `doc` (and gives the transport the `player`).
- The `Player` is not a widget. The window owns it because two things drive it: the transport buttons and the window's keyboard actions.
- The window is the only code that reaches into widgets, and only to **wire** them: actions call widget methods (`filmstrip.delete_selected`, `canvas.zoom_fit`, `player.step`), and four outward signals come back (`SettingsPanel.generateRequested`, `TransportBar.saveFrameRequested`, `Filmstrip.errorOccurred`, `FrameCanvas.zoomChanged`). Widgets never call each other. Details: [main_window page](codebase/src/gif_editor/ui/main_window.md).

### How signals flow through `Document`
```mermaid
flowchart LR
    subgraph writers["Widgets write (method calls)"]
        SETw["SettingsPanel<br/>apply · set_trim"]
        TBw["TimeBar<br/>set_current_index · set_trim"]
        FSw["Filmstrip<br/>set_current_index · set_selection<br/>delete/restore_frames · set_trim"]
        PLw["Player<br/>set_current_index"]
        MWw["MainWindow<br/>set_source · close · set_trim · undo/redo"]
    end
    D(("Document"))
    subgraph readers["Widgets react (signals)"]
        R1["sourceChanged → everyone refreshes fully"]
        R2["stateChanged → SettingsPanel, TimeBar, Filmstrip,<br/>FrameCanvas (overlay), TransportBar (label), Player (resync)"]
        R3["currentIndexChanged → FrameCanvas, TimeBar,<br/>Filmstrip, TransportBar, Player"]
        R4["selectionChanged → Filmstrip"]
    end
    writers --> D --> readers
```
Example: the user clicks a thumbnail while playing.
1. `Filmstrip` → `doc.set_current_index(5)` (guarded by `_syncing` so its own echo is ignored).
2. `Document` emits `currentIndexChanged(5)`.
3. `FrameCanvas` shows frame 5; `TimeBar` moves the playhead; `TransportBar` updates "Frame 6 / N"; `Player` sees an index change it did not cause and **resumes playback from frame 5** with a fresh timing base.
4. The filmstrip's own `_on_doc_current` moves the current item with `NoUpdate`, so the **selection is not changed** by the playhead.

Edits go the same way: `doc.apply(...)` → `SetStateCommand` → `stateChanged(new)`, and every view redraws from `doc.state`. Undo/redo emit the same signal, so controls, timebar handles and filmstrip marks all follow undo without extra code. To avoid feedback loops, a widget that both writes and listens either blocks its own signals while refreshing (settings panel) or uses a re-entrancy guard (filmstrip `_syncing`, player `_setting_index`).

### Per-widget roles
| Widget | File | Listens to | Calls on `Document` | Notes |
|---|---|---|---|---|
| Settings panel | `ui/settings_panel.py` | `sourceChanged`, `stateChanged` | `apply(..., merge_key=<per control>)`, `set_trim(..., "trim")`, `summary()` | Live summary + warnings; Generate button disabled when the output is empty. A size equal to the base size is stored as `None` ("follow the crop"). |
| Frame canvas | `ui/inspector/canvas.py` | `sourceChanged`, `currentIndexChanged`, `stateChanged` | none (read-only) | Scene coordinates = image pixels (ready for the M3 crop rectangle). Ctrl+wheel zoom, middle-drag pan. |
| Transport | `ui/inspector/transport.py` | `sourceChanged`, `stateChanged`, `currentIndexChanged`; `Player.playingChanged`/`previewEditsChanged` | none (drives the `Player`) | Shortcuts live in the window; "Save frame…" just emits a signal. |
| Timebar | `ui/inspector/timebar.py` | `sourceChanged`, `stateChanged`, `currentIndexChanged` | `set_current_index`, `set_trim(..., "trim-drag-N")` | Handles snap to frame boundaries (earlier boundary on a tie), Alt = free; one undo step per drag. |
| Filmstrip | `ui/inspector/filmstrip.py` | `sourceChanged`, `stateChanged`, `currentIndexChanged`, `selectionChanged` | `set_current_index`, `set_selection`, `delete_frames`, `restore_frames`, `set_trim(..., None)` | Thumbnails in batches of 32 via `run_async`, stale batches dropped by generation number. |
| Player | `ui/inspector/player.py` | `sourceChanged`, `stateChanged`, `currentIndexChanged` | `set_current_index`; reads `plan()` in preview mode | Ideal-timeline scheduling (no drift), skips late frames, rebases after a stall longer than one loop. |
| Inspector | `ui/inspector/inspector.py` | — | — | Composition only. |
| Main window | `ui/main_window.py` | `sourceChanged` | `set_source`, `close`, `set_trim(..., None)`, `plan()`, `undo_stack` | Async open + drag-drop, Generate with progress/cancel, Save frame, busy flags. |

Shared widget rules (AGENTS.md):
- construct with `(doc, parent=None)` (the transport and inspector also take the `player`);
- refresh fully on `sourceChanged`;
- show a disabled/empty state when `doc.is_open` is False;
- never block the GUI thread for more than about 16 ms;
- use `merge_key` for continuous gestures;
- `setAccessibleName` on custom widgets;
- HiDPI-safe painting (cosmetic pens, logical pixels).

### Known UI limitations (M2)
- **Space** is the window's play/pause shortcut, so the canvas's Space+drag pan never sees the key; **middle-drag** pans.
- Window-level arrow and Home/End shortcuts are skipped when the focused widget accepts `ShortcutOverride` for them (the settings panel's spin boxes; the filmstrip claims Delete/Backspace/Insert and handles them itself).
- Preview plays edited **timing** only. Crop/resize preview and the crop rectangle come in M3.

## Known drift between docs and code

Things noticed while writing these docs. The code is the truth.
- `scripts/fetch-devlibs.sh`'s header comment lists the full Debian trust chain as if the script checked it; the script enforces only the pinned SHA-256. The docs ([fetch-devlibs page](codebase/scripts/fetch-devlibs.md#trust-chain), AGENTS.md, [06-testing](06-testing.md#headless-qt-and-the-project-local-libegl)) say what is actually checked and record the one-time manual verification. The script comment itself is code and was left as is.
- `docs/02-plan.md` is the original plan and is not rewritten; where the code deviates, see its [Implementation notes (deviations)](02-plan.md#implementation-notes-deviations).
- `encoder.estimate_size` exists and is tested, but nothing calls it until M3 (the summary shows no size estimate yet).
- `Document.set_trim` defaults to `merge_key="trim"`. That is intended for spinbox scrubbing (the settings panel); drag and menu callers pass their own key (`"trim-drag-N"`) or `None`. Calling it without a key from a new discrete action would silently merge with the previous trim step.

Fixed at the end of M2 (kept here for reference): `app.py` now calls `run_selftest`; `Document.close()` now emits `currentIndexChanged`/`selectionChanged`; the decoder docstring now names the instance method `Image.Image.frombytes`; AGENTS.md now lists `run_async(pool=)`, the full pipeline API and the per-widget interfaces; README.md shows the M2 status.
