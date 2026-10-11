# 02 — Plan: GIF Editor

## 1. Vision
GIF Editor is a fast, offline Windows desktop tool for reshaping existing GIFs. You load a GIF and scrub through it frame by frame. You can trim it, delete frames, crop with a draggable rectangle, and set speed, FPS, quality and output size. A live summary shows exactly what you will get. One **Generate** click writes the new GIF. All edits are non-destructive and undoable until you generate.

## 2. MVP scope

### Must-have (v1)
1. **Load a GIF** (file dialog plus drag-and-drop). The file is decoded with correct disposal and transparency handling, and source info is shown: frames, duration, W×H and size.
2. **Frame inspector (right panel):**
   - a zoomable canvas with Fit and 100% zoom
   - a timebar with playhead, frame ticks and green/red **trim handles** (start time and duration)
   - a thumbnail **filmstrip**
   - play/pause and frame stepping, with keyboard shortcuts
3. **Frame deletion:**
   - delete the current frame or a multi-selection
   - deleted frames stay visible greyed out and can be restored
   - full **undo/redo** (Ctrl+Z / Ctrl+Y)
4. **Interactive crop:**
   - a rectangle with 8 handles; drag inside it to move it
   - aspect presets: Free, Original, 1:1, 4:3, 16:9, 9:16
   - X/Y/W/H spinboxes kept in sync both ways
   - the area outside the crop is dimmed
5. **Output settings (left panel):**
   - **Speed** (0.25×–4×)
   - **Output FPS** (Original, or a target ≤ 50)
   - **Start time / Duration** (linked to the trim handles)
   - **Size** (W/H with aspect lock, or scale %)
   - **Quality** (preset High / Medium / Low, plus advanced: colours 2–256, dithering on/off)
6. **Live summary and preview:**
   - "Frames 120 → 61 · 3.2 s · 480×270 · ≈1.4 MB"
   - a toggle that plays the *edited* result live, with timing and geometry applied
7. **Generate and Save frame:**
   - Generate runs in the background with progress and Cancel, then writes the GIF safely (temp file, then rename)
   - **Save current frame as PNG**, either as in the original or with the crop and resize applied

### NOT in v1
- Recording the screen or webcam, or importing video
- Export to WebP, MP4 or APNG (GIF and PNG only)
- Per-frame delay editing, reordering or duplicating frames
- Text, annotations, filters, transitions, rotation
- Per-frame (animated) crop
- Project files or saving a session
- Bundled gifsicle or gifski / lossy optimisation
- Batch processing, CLI, macOS or Linux builds
- Auto-update, code signing (decide separately; see the open questions)

### Timing model (resolves the speed / FPS / duration conflict)
1. **Trim**: *Start time* and *Duration* select a window in **source time**. They are synced with the trim handles.
2. **Delete**: deleted frames are removed together with their delay, so the timeline shrinks.
3. **Speed** *s*: every remaining delay is divided by *s*.
4. **Output FPS** (optional): the result is resampled onto a uniform 1/FPS grid by picking the visible frame at each tick. The target is capped at 50 fps and at the source's own effective frame rate. Frames are only ever dropped, never duplicated.
5. Delays are rounded to whole centiseconds with the rounding error carried forward, and every delay is at least 20 ms. A warning appears when a requested speed or FPS can't be met exactly.
6. **Output duration is derived and read-only** in the summary.
7. Geometry is applied in this order: **crop → resize → quantize**. The crop is one rectangle for all frames.

## 3. Chosen stack
| Piece | Choice (pinned) |
|---|---|
| Language | Python 3.13 x64 |
| UI | **PySide6-Essentials 6.12.0** (Qt Widgets; no WebEngine or 3D, which keeps the build small) |
| GIF I/O and imaging | **Pillow 12.3.0** |
| Array helpers | **numpy 2.5.3** (fast QImage↔array handoff, alpha handling) |
| Tests | pytest 9.1.1, pytest-qt 4.5.0 |
| Lint/format | ruff 0.17.0 |
| Packaging | **Nuitka 4.3 `--onefile`** → single portable `GifEditor.exe` (decided at Gate 1; replaces PyInstaller one-dir) |
| CI | GitHub Actions `windows-latest` (lint, tests, build artifact) |

**Why this stack:**
- PySide6 was your choice, and its QGraphicsView and QUndoStack provide the zoomable crop canvas and undo almost for free.
- Pillow already composites GIF frames and quantises with permissive licensing. FFmpeg (+50–100 MB, more licence risk) and gifski or libimagequant (AGPL/GPL) both lost on licence or size.
- Gate 1 decision: you want a **literal single .exe**. Nuitka onefile is less prone to antivirus false positives than PyInstaller onefile, and its official PySide6 plugin keeps the build small.
- Trade-offs accepted: Nuitka needs a C compiler (MSVC Build Tools, or MinGW that Nuitka downloads into its own cache), so the release build runs on Windows CI. Builds take minutes. Onefile unpacks to a temporary folder on launch, using Nuitka's cached extraction directory.
- LGPL: with a onefile build, Qt can't be swapped out in place. To stay compliant we publish the app source and a "how to rebuild with your own Qt" note, plus the licence texts and a Qt source link.

## 4. Architecture

```mermaid
flowchart LR
    subgraph Core["core/ (pure Python, no Qt)"]
        DEC[decoder.GifSource\nindex + composited RGBA\nLRU cache + keyframes]
        MOD[models.EditState\ntrim, deleted, crop,\nspeed, fps, size, quality]
        TL[timeline.plan_output\n→ list of (src_idx, delay_cs)]
        REN[render.render_frame\ncrop → resize → quantize]
        ENC[encoder.write_gif\nstreaming, progress, cancel,\ntemp+rename, verify]
    end
    subgraph UI["ui/ (PySide6)"]
        MW[MainWindow]
        SP[SettingsPanel\n+ live summary]
        INS[Inspector\ncanvas + CropItem\ntimebar + filmstrip]
        US[QUndoStack\nEdit commands]
        WK[Workers\nQThreadPool]
    end
    File[(input.gif)] --> DEC
    DEC --> INS
    SP -- commands --> US
    INS -- commands --> US
    US --> MOD
    MOD --> TL
    DEC --> TL
    TL --> SP
    TL --> INS
    MW -- Generate --> WK
    WK --> ENC
    TL --> ENC
    DEC --> REN
    REN --> ENC
    ENC --> Out[(output.gif)]
    INS -- Save frame --> PNG[(frame.png)]
```

- **core/** has no dependency on Qt and is fully unit-testable. `GifSource` reads the file once and caches composited frames.
- **`EditState`** is the single source of truth for every edit. It is immutable and replaced on each change.
- **`plan_output(source_meta, edit_state)`** is a pure function that returns the ordered list of (source frame, output delay). The summary, the live preview and the encoder all use it, so the preview always matches the output.
- **UI** widgets never change state directly. They push `QUndoCommand`s that swap in a new `EditState`, and views re-render through a single `stateChanged` signal.
- **Heavy work runs off the GUI thread** in QThreadPool workers: indexing, thumbnails, size estimate and Generate. Workers emit QImage or bytes, never QPixmap.

## 5. Folder structure
```
gif-editor/
├─ pyproject.toml            # deps, ruff, pytest config
├─ README.md  AGENTS.md  .gitignore
├─ .github/workflows/ci.yml
├─ docs/                     # 00-brief, 01-research, 02-plan
├─ src/gif_editor/
│  ├─ __init__.py  __main__.py  app.py
│  ├─ core/
│  │  ├─ models.py           # EditState, CropRect, Quality, OutputSize
│  │  ├─ decoder.py          # GifSource, FrameMeta, limits
│  │  ├─ timeline.py         # plan_output(), cs rounding
│  │  ├─ render.py           # crop/resize/quantize
│  │  └─ encoder.py          # write_gif(), estimate_size()
│  ├─ ui/
│  │  ├─ main_window.py
│  │  ├─ settings_panel.py
│  │  ├─ commands.py         # QUndoCommand subclasses
│  │  ├─ workers.py
│  │  ├─ qt_image.py         # PIL/numpy ↔ QImage helpers
│  │  └─ inspector/
│  │     ├─ canvas.py  crop_item.py  timebar.py  filmstrip.py  transport.py
│  └─ resources/icons/
├─ tests/
│  ├─ conftest.py            # generates fixture GIFs on the fly
│  ├─ core/  ui/
└─ packaging/
   ├─ build_nuitka.ps1
   └─ licenses/              # LGPL/GPL texts, THIRD_PARTY_LICENSES
```

## 6. Milestones
| # | Milestone | Deliverables | Done when |
|---|---|---|---|
| **M1** | **Core engine (headless)** | `models`, `decoder`, `timeline`, `render`, `encoder` and a test corpus of generated GIFs | `pytest tests/core` is green; a script can load a GIF, apply trim, deletes, crop, speed, FPS, size and quality, and write a valid GIF that reads back with the expected frames and delays |
| M2 | Window + inspector | Main window, settings panel (no crop yet), canvas with zoom, timebar with trim handles, filmstrip, playback, delete/restore, undo/redo, Save PNG | You can open a GIF, scrub, delete and undo, trim with the handles, and save a frame; pytest-qt smoke tests pass |
| M3 | Crop + live preview | CropItem with handles, aspect lock, spinbox sync, edited-preview toggle, live summary with size estimate | Crop and preview match the Generate output frame for frame (automated comparison) |
| M4 | Generate + hardening | Background Generate with progress and cancel, error dialogs, input limits, corrupt-file handling, HiDPI pass, shortcuts, accessibility names | You can cancel mid-export with no partial file; large and corrupt fixtures don't freeze or crash the app; works at 150% and 200% scaling |
| M5 | Packaging | Nuitka `--onefile --enable-plugin=pyside6` build script, icon/version info, licence bundle, Windows CI build artifact | `GifEditor.exe` runs on a clean Windows 11 VM with no Python, from any folder or a USB stick |

## 7. Milestone 1 task breakdown (independent, each ≤ ½ day)
Interfaces are fixed in advance (in `AGENTS.md`) so the tasks can run in parallel.

- **T1 – `core/models.py`**
  - Frozen dataclasses: `CropRect(x, y, w, h)`, `OutputSize(width, height, keep_aspect)`, `Quality(colors, dither)` with presets, and `EditState(trim_start_ms, trim_duration_ms|None, deleted: frozenset[int], crop: CropRect|None, speed: float, fps: float|None, size: OutputSize|None, quality)`.
  - `with_*` helpers and validation.
  - Tests.
- **T2 – `core/decoder.py`**
  - `GifSource.open(path, limits)` produces a `meta` with canvas size, loop and `FrameMeta(index, delay_ms, disposal)`. A 0 or 10 ms delay counts as 100 ms for display.
  - `frame(i) -> PIL.Image RGBA`, served from an LRU cache with a byte budget plus keyframe checkpoints.
  - `thumbnail(i, max_side=96)`.
  - Limits on canvas size, frame count and decoded bytes; per-frame error tolerance.
  - Tests.
- **T3 – `core/timeline.py`**
  - `plan_output(frame_delays_ms, state) -> list[OutputFrame(src_index, delay_cs)]`.
  - Applies trim, deletion, speed and FPS resampling (drop only), with centisecond rounding, the error carried forward and a 2 cs floor.
  - `summary()` returns frame count, duration and warnings.
  - Extensive table-driven tests.
- **T4 – `core/render.py`**
  - `render_frame(img_rgba, crop, size) -> RGBA`: crop, then LANCZOS resize with premultiplied alpha.
  - `quantize(img, quality) -> P-mode image` with an explicit transparent index (FASTOCTREE when there is alpha, MEDIANCUT when opaque).
  - Tests.
- **T5 – `core/encoder.py`**
  - `write_gif(frames: Iterable[(P-image, delay_ms)], path, loop=0, progress=cb, cancel=Event)`: streams the frames, writes to a temp file then renames, and reads the result back to verify it.
  - `estimate_size(sample)`.
  - Tests.
- **T6 – Test corpus (`tests/conftest.py`)**
  - Fixture factories that generate tiny GIFs: disposal 0–3, partial frames with offsets, local palettes, changing transparency, 0-delay frames, a single frame, and a truncated or corrupt file.
  - A `make_gif()` helper.
- **T7 – Integration (orchestrator, after T1–T6)**
  - `gif_editor.core.pipeline.generate(source, state, out_path)` wires the pieces together.
  - End-to-end tests.

## 8. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Large GIFs exhaust RAM | Byte-budgeted LRU cache, keyframes, thumbnails; limits checked on load |
| Scrubbing backwards is slow (Pillow seeks sequentially) | Keyframe checkpoints, debounced scrub, show the thumbnail first |
| Pillow GIF quirks (disposal, palettes, transparency, frame merging) | Pin Pillow 12.3.0, golden test corpus, read output back to verify, explicit loop/duration/disposal |
| Speed, FPS and duration contradict each other | Fixed timing model (§2); duration derived; warnings when a target can't be met |
| UI freezes | All heavy work in workers; QPixmap only on the GUI thread |
| Malicious or corrupt GIFs | `MAX_IMAGE_PIXELS` kept on, app limits, per-frame try/except |
| Antivirus / SmartScreen warnings | One-dir build, no UPX; signing is an open question |
| LGPL compliance | Qt DLLs stay replaceable; licence texts and Qt source link included |
| HiDPI crop mapping bugs | Store coordinates in source pixels, cosmetic pens, tests at 150% and 200% |

## 9. Open questions for you
1. **Distribution:** one-dir **installer + portable zip** (recommended), or a literal single .exe (Nuitka onefile: slower builds, some antivirus risk)?
2. **"Duration" meaning:** the length of the trim window from the start time (recommended), or a target *output* length that automatically sets the speed?
3. **Deleting a frame:** remove its time (recommended, the GIF gets shorter), or give its delay to the previous frame (total length stays the same)?
4. **Transparency:** keep the source's transparency (recommended), or flatten onto a background colour?
5. **App licence:** open source (e.g. MIT) or closed? This only affects notices for now.
6. **Code signing:** skip for v1 (users see a SmartScreen warning), or plan for it (~$10/month Azure if eligible, or ~$200–600/year)?

## 9b. Gate 1 decisions (2026-10-10)
- **Distribution:** a literal single .exe built with **Nuitka onefile**.
- **Duration:** the length of the trimmed section, counted from the start time.
- **Deleting a frame:** removes that frame's time, so the GIF gets shorter.
- **Transparency:** the source's transparency is preserved.
- Still open: app licence (#5) and code signing (#6). Not needed until M5.

## 10. Cost / effort estimate (rough estimate, not a quote)
- **Effort:** M1 about 2–3 dev-days; M2 about 3–4; M3 about 2–3; M4 about 2–3; M5 about 1–2. **Total ≈ 10–15 dev-days** of equivalent work, much of it parallelisable by subagents.
- **Money:** $0 for the libraries and tools (all free). Optional code signing ≈ $120/year (Azure Artifact Signing) or $200–600/year (OV certificate). AI token costs depend on how much is delegated.
- **Build size:** the installer is about 30–45 MB, and the one-dir folder about 70–120 MB unpacked (estimate).

## Implementation notes (deviations)
This plan is kept as written at Gate 1. The code deviates from it in the points below (status at the end of Milestone 3). Where they disagree, the code and [03-architecture.md](03-architecture.md) are the truth.

| Plan says | Code does | Why |
|---|---|---|
| `OutputSize(width, height, keep_aspect)` (§7 T1) | `OutputSize(width, height)`; the aspect lock is a settings-panel control, and a size equal to the base size is stored as `size=None` | The lock is UI behaviour, not part of the output; `None` keeps the size following the crop |
| `FrameMeta(index, delay_ms, disposal)` (T2) | adds `effective_delay_ms`; `SourceMeta` adds `delays_ms`, `has_transparency`, `loop` | The 0/10 ms → 100 ms rule needs both values |
| `plan_output(...) -> list[OutputFrame]`, `summary()` in timeline (T3) | returns a `TimelinePlan(frames, duration_ms, warnings)`; the summary is `pipeline.summarize` → `Summary` | Warnings and duration belong to the plan; the summary also needs geometry from `render` |
| `quantize(img, quality)`: FASTOCTREE with alpha, MEDIANCUT opaque (T4) | one **shared palette** per output (`build_palette`: exact colours if few, else median cut) and `quantize(..., palette, previous)` | A palette per frame made files ~10× larger and colours shimmer ([dev log](04-development-log.md#independent-review--fixes)) |
| `write_gif(frames: (P-image, delay_ms), ...)` with Pillow (T5) | own GIF writer; frames are `(P-image, delay_cs)`; lossless difference frames; a `verify` hook before `os.replace`; `loop=None` keeps "play once" | Pillow's `save_all` crops opaque pixels and can write a second header mid-file with transparency ([dev log](04-development-log.md#wave-1-five-parallel-workers)); delays are already whole cs from the timeline |
| `estimate_size(sample)`; summary "≈1.4 MB" (§2.6) | `pipeline.estimate_size(source, state, timeline)` encodes a contiguous middle run of real output frames as one stream (`encoder.write_stream` into memory) and extrapolates; shown as "Size: ≈ …" via `PreviewService`. `encoder.estimate_size` (M1) remains but is unused | Frames are stored as differences, so single-frame samples overestimated 3.4× |
| Test corpus in `tests/conftest.py` (T6) | `tests/gifgen.py` (simple GIFs via Pillow) and `tests/corpus.py` (raw GIF89a writer + reference compositor); `conftest.py` only exposes fixtures | Edge cases Pillow cannot write needed a byte-level writer |
| `commands.py`: one `QUndoCommand` subclass per edit (§5) | one generic `SetStateCommand(old, new)` with `merge_key` gesture merging | States are immutable values, so one command covers every edit |
| Tree: `inspector/canvas.py crop_item.py timebar.py filmstrip.py transport.py` (§5) | `crop_item.py` exists (M3); also `inspector/preview.py` (`PreviewService`) and `ui/crop_panel.py`; added `inspector/player.py` (playback engine) and `inspector/inspector.py` (panel composition); added `ui/document.py` (the hub) | Playback needed a non-visual owner shared by buttons and shortcuts |
| No self-test in the plan | `core/selftest.py`, run by `app.main` at startup | We depend on undocumented Pillow internals |
| Pipeline in T7 only `generate(...)` | `core/pipeline.py` also has `plan`, `summarize`, `render_output_frame`, `output_palette`, `iter_output_frames`, `export_frame_png` | One shared path for summary, preview, Generate and PNG export |
| Preview toggle: timing + geometry (§2.6, M3) | Implemented in M3 as planned: "Preview edits" (P) plays the output timing and shows crop + resize on the canvas (in M2 it was timing only) | — |
| Load shows "frames, duration, W×H and size" (§2.1) | the status bar shows frames and W×H (plus decoder warnings); duration is in the timebar and summary; file size is not shown | Not needed for M2's exit criteria |
| Undo/redo Ctrl+Z / Ctrl+Y (§2.3) | Ctrl+Z / Ctrl+Y, plus Ctrl+Shift+Z (see the [main window page](codebase/src/gif_editor/ui/main_window.md#actions-and-shortcuts)) | Added in `76cd65c` |
| Deleted frames "greyed out" (§2.3) | filmstrip: faded thumbnail with a grey wash and a red diagonal strike; canvas: red tint + "Deleted" badge; timebar: red hatching | Readable even in greyscale; matches the plan's intent |
