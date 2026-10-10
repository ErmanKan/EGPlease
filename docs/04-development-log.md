# Development log

A chronological record of how GIF Editor was built: what was decided, by whom, and why.
Newest milestone at the bottom. Commit hashes refer to `git log`.

The work is orchestrated by a planning agent that does design, integration and verification itself, and delegates well-bounded tasks to parallel worker agents. Every worker gets the hard rules (files only inside the repo, no global installs, no package installs; it must request packages instead), owns an explicit list of files, runs lint + tests and commits only its own files.

---

## Phase 0: Intake (2026-10-10)
- The idea was restated and four intake questions were asked. Answers: **Windows only**, **Python + PySide6**, **single portable .exe / installer**, **GIF output only (+ PNG for single frames)**.
- Recorded in `docs/00-brief.md`.

## Phase 1: Research
Four read-only research agents ran in parallel (prior art, tech stack, risks, UX patterns). Results were synthesised in `docs/01-research.md`. Key takeaways:
- **Prior art:** ezgif has the right tools but is online-only and split into separate pages. ScreenToGif has the best editor UX but is recorder-first and dense. Our niche is "ezgif's tools, offline, in one window, with a frame inspector".
- **Stack:** Pillow for GIF I/O and quantisation; avoid gifsicle/gifski/libimagequant (GPL/AGPL).
- **Timing:** GIF delays are whole centiseconds, and browsers clamp delays ≤ 10 ms to 100 ms, so 50 fps is the real maximum.
- **Conflict found:** "speed", "FPS" and "duration" over-constrain each other, so a single timing model was needed.

## Phase 2: Plan and Gate 1
`docs/02-plan.md` defined the MVP, the **timing model** (trim → delete → speed → FPS resample → centisecond rounding; output duration derived), the architecture (pure-Python `core/` + Qt `ui/`, an immutable `EditState`, one `plan_output()` used by preview and export), and 5 milestones.

User decisions at Gate 1:
| Question | Decision |
|---|---|
| Distribution | Literal single `.exe` via **Nuitka onefile** (instead of the recommended installer + zip) |
| Meaning of "Duration" | Length of the trimmed section, starting at Start time |
| Deleting a frame | Removes its time (GIF gets shorter) |
| Transparency | Preserve source transparency |
| Loop (asked later, no answer) | Default chosen: keep source behaviour (no loop block → plays once) |

## Phase 3: Scaffold (`7a7b418`)
- Folder layout, `pyproject.toml` (pins), `AGENTS.md` (contract for all contributors), ruff/pytest config, Windows CI workflow.
- Dependencies were vetted (exact names, latest versions, wheel-only, licences) and installed into the project `.venv` only: PySide6-Essentials 6.12.0, Pillow 12.3.0, numpy 2.5.3, pytest 9.1.1, pytest-qt 4.5.0, ruff 0.17.0.
- The orchestrator wrote `core/models.py` (`EditState` etc.) itself so parallel workers had a fixed contract to build on.
- **Environment limitation:** the Linux dev container lacked `libEGL.so.1`, so Qt could not load. Milestone 1 core work runs without Qt.

## Milestone 1: Core engine
### Wave 1: five parallel workers
| Commit | Module | Notes |
|---|---|---|
| `719c05c` | `render.py` | crop → premultiplied LANCZOS resize → quantize. Found: Pillow ignores `dither` for MEDIANCUT, so it builds the palette first and maps second |
| `f7a81ac` | `decoder.py` | `GifSource` with LRU frame cache |
| `c06ef17` | `timeline.py` | `plan_output()` |
| `cc5e164` | `tests/corpus.py` | Hand-written GIF89a writer + reference compositor → 13 tricky test GIFs. Found Pillow composites *disposal 2* wrongly |
| `cca60c1` | `encoder.py` | Found Pillow's `save_all` crops opaque pixels and can even write a second header mid-file when transparency is involved, so the GIF writer is our own (Pillow is used only for LZW compression) |

The orchestrator then wrote `pipeline.py` (`f9add66`), which glues plan → render → quantize → encode.

### Wave 2: decoder rewrite (`212b23f`)
Our own GIF block parser plus a numpy compositor using **browser** disposal semantics (Pillow is used only for LZW decoding). Keyframe canvas checkpoints make backward scrubbing fast.

### Independent review → fixes
A `/review` agent found real defects (all reproduced by the orchestrator before fixing):
1. The FPS cap did not cap (frames kept their original start times). → `e8bcb7e`: strict grid resample.
2. Output was ~10× larger and colours flickered (a palette per frame, full frames). → `8e7d34c`: **shared palette + lossless frame differencing**. Re-saving went from 679 KB to 21 KB on the test GIF.
3. A 40-byte GIF could make the decoder allocate ~1.25 GB (unchecked per-frame header size). → `5a464d8`: per-frame limits.
4. Trim lost time (a partially visible first frame was dropped). → `e8bcb7e`: frames visible in the window are kept and shortened.
5. Delays > 65535 cs crashed Generate. → split into repeated frames with a warning.
6. Saving over the open source would fail on Windows (file handle kept open). → `5a464d8`: file read into memory, handle closed.
7. Output was not verified after writing. → `f7056d9`: verify-before-replace hook.
8. Loop forced to infinite. → `f7056d9`: source loop behaviour kept.
Also added: a Pillow-internals **self-test** (`c0dbd20`), because we depend on undocumented Pillow internals (Pillow is pinned).

Result: 392 tests passing, lint clean.

### Headless Qt (`cc9f0fa`)
With the user's approval, Debian's `libegl1` was fetched into the project-local, gitignored `.devlibs/`. It was verified through Debian's signed archive index and the package SHA-256, and unpacked with `dpkg-deb -x` (not installed). `scripts/test.sh` runs everything headlessly.

## Milestone 2: Window and inspector

### Foundation (`0137178`, orchestrator)
Before any widget was written, the orchestrator fixed the contract every widget builds on:
- `ui/document.py`: `Document`, the hub that owns the source, the `EditState`, the undo stack, the current frame and the selection. Widgets talk only to it, never to each other.
- `ui/commands.py`: one generic undoable `SetStateCommand(old, new)` with gesture merging by `merge_key`. Because states are immutable values, one class covers every edit.
- `ui/workers.py`: `run_async`, which runs work on the thread pool and delivers callbacks on the GUI thread.
- `ui/qt_image.py`: `pil_to_qimage` and the checkerboard brush.
- The docs framework (`docs/README.md`, the per-file template) and this log. The *UI interfaces* block and the widget rules went into `AGENTS.md`.

### Parallel workers
Five widget workers and one documentation worker ran in parallel. Each owned its files, its tests and its doc page.

| Commit(s) | Worker | Delivered |
|---|---|---|
| `3b340fc` | settings panel | `SettingsPanel`: Start/Duration, Speed (spin + slider), FPS limit, Size (aspect lock, scale %, reset), Quality preset/colours/dither, live summary card, Generate button |
| `b0c3c72`, `44f3b6b` | canvas | `FrameCanvas`: zoom (Fit, 100 %, Ctrl+wheel at the mouse), Space/middle-drag pan, deleted overlay; scene coordinates = image pixels, ready for the M3 crop rectangle. `44f3b6b` ruff-formatted a code block in its page |
| `ab5a9e8` | timebar | `TimeBar`: custom-painted source timeline, playhead, snapping trim handles, keyboard, accessible description |
| `eb68853` | filmstrip | `Filmstrip`: lazy thumbnail batches on the pool, multi-select, Delete/Restore, trim context menu |
| `51e067d`, `684315e` | player + transport | `Player` (drift-free playback, source or edited timing) and `TransportBar`. `684315e` fixed a test count in its page |
| `1a3f6dc`, `c72e219`, `9291fba` | documentation | Per-file pages for `src/` (`1a3f6dc`) and for tests, scripts and config (`c72e219`); architecture, GIF primer, testing guide and codebase index (`9291fba`) |

### Notable decisions
- **The filmstrip follows the playhead without clobbering the selection.** On `currentIndexChanged` it moves its current item with `QItemSelectionModel.NoUpdate`. Otherwise every frame of playback (or a timebar scrub) would replace whatever the user had selected for deletion.
- **Timebar snapping and the tie rule.** A dragged handle snaps to the nearest frame boundary inside the allowed range. On an exact tie the **earlier** boundary wins (`min` by `(distance, boundary)`), so the result is deterministic. Alt drags freely (whole ms). Each press gets a fresh merge key (`trim-drag-N`), so one drag is one undo step and two drags are two. The release position is deliberately not re-applied, because users often let go of Alt a moment before the button.
- **A size equal to the base size is stored as `None`.** The settings panel writes `size=None` when the requested W×H equals the base size (the crop, or the canvas). `None` means "follow the crop", so a later M3 crop change still resizes correctly, and an untouched size never counts as an edit.
- **The player resumes from a clicked frame and re-anchors after a long stall.** If someone else moves the playhead while playing (a filmstrip click, a timebar scrub), the player continues from that frame with a fresh timing base instead of jumping back. Scheduling uses an ideal timeline on a monotonic clock, so it does not drift and it skips frames when late. If it is more than one whole loop late (debugger, laptop sleep), it rebases `due = now` instead of fast-forwarding through loops.
- **The pytest-qt `deleteLater` teardown trap → `QThreadPool.waitForDone`.** pytest-qt `close()`s and `deleteLater()`s every `qtbot.addWidget` widget **before** the fixture code after `yield` runs. The filmstrip fixture first polled the model in its teardown; that spun the event loop, the widget and its model were deleted, the last thumbnail batch was never delivered, and the test flaked with a timeout. The fixture now only calls `QThreadPool.globalInstance().waitForDone(5000)`, so in-flight jobs finish before the `doc` fixture closes the source. See [06-testing](06-testing.md#the-deletelater-teardown-trap).

### Integration (`be70f38`, orchestrator)
- `ui/main_window.py`: `MainWindow` with the layout (settings panel in a scroll area | inspector), File/Edit/Playback/View menus, window-wide shortcuts, async open + drag-and-drop, Generate with an immutable state snapshot, progress dialog and cancel `Event`, Save frame as PNG (original or with crop/size), trim at the playhead (I/O), busy flags, and `closeEvent` that cancels a running Generate first. Errors use the non-blocking `QMessageBox.open()` plus `last_error`, so the integration tests run headlessly.
- `ui/inspector/inspector.py`: `Inspector`, which composes canvas, transport, timebar and filmstrip.
- `app.py`: the real entry point. It runs the Pillow **self-test at startup** (exit code 1 with a dialog on failure), shows the window, and opens a path given on the command line.
- **`Document.close()` fix:** it now also emits `currentIndexChanged(0)` and `selectionChanged`, exactly like `set_source`. Close resets the index and selection, and listeners of those two signals now see that reset directly instead of having to infer it from `sourceChanged`.
- `tests/ui/test_main_window.py`: 14 integration tests driving the real window.

### Verification
- Full suite: **522 passed + 2 xfailed** (the two documented Pillow disposal-2 differences), stable over 3 consecutive runs; ruff format and lint clean.
- A layout check of the real window at **1300×820** (offscreen, screenshot) found no overlapping panels, and the live numbers were correct. With a 40-frame demo GIF, trim 0.3–2.1 s, 3 frames deleted and speed 1.5×, the summary showed **27 frames, 1.08 s**.
- The screenshot is at `out/m2-window.png`. `out/` is gitignored, so it is not in the repo.

### Known limitations (carried to M3)
- **Space vs Space+drag:** Space is the window's play/pause shortcut, and window shortcuts are matched before the canvas's key handler, so Space+drag panning does not work inside the app. Middle-drag pans. Related: widgets that accept `ShortcutOverride` (spin boxes; the filmstrip for Delete) keep those keys, which is the desired behaviour for typing.
- **Geometry and crop preview come in M3:** "Preview edits" plays the edited timing only, and the crop rectangle, crop/resize preview and the file-size estimate are M3 work.

### Documentation pass (end of M2)
The documentation was brought up to date for the finished milestone: new pages for the main window, the inspector and the main-window tests; the architecture page now shows the real widget tree and signal flow; AGENTS.md gained the per-widget interfaces; README lists features and shortcuts; `02-plan.md` got an *Implementation notes (deviations)* section instead of a rewrite; the decoder's module docstring now names the right Pillow call.
