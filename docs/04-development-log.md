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

## Milestone 3: Crop and live preview

### Before M3: post-M2 fixes (`76cd65c`)
Standard shortcuts now get all their platform bindings (`setShortcuts`), Close is Ctrl+W and Quit Ctrl+Q, Redo is also Ctrl+Shift+Z; Ctrl+G refuses an empty output like the Generate button does; Generate warnings are shown in the status bar. The `fetch-devlibs.sh` header comment now says it checks only the pinned hash.

### Commits
| Commit(s) | By | Delivered |
|---|---|---|
| `b9021ca` | orchestrator | `pipeline.estimate_size` (+ `_encoded_size`) and `encoder.write_stream`; `tests/core/test_estimate.py` |
| `fe4e1a8` | docs worker | The `CropPanel` **specification** (`crop_panel.md`, rule by rule) and its test checklist, written before any code |
| `053ed66`, `e205656` | orchestrator | **Shutdown snapshot:** `docs/RESUME-HERE.md` and the unverified `preview.py` committed as a flagged snapshot; then lint/format of that file |
| `e904982` | orchestrator | `PreviewService` verified: 4 broken tests fixed, one real thread-safety fix, `tests/ui/test_preview.py` |
| `ac973e9` | orchestrator | `CropPanel` implemented from the spec, `test_crop_panel.py`; the `PreviewService` doc pages |
| `6e8a3ad` | crop-item worker (restarted) | `CropItem`: drag/resize with 8 handles, dimmed outside, one undo step per drag; tests and pages |
| `3adb5bd` | orchestrator | Wiring: geometry preview in the canvas, Size line and crop panel in the settings panel, P previews the whole output; `test_m3_integration.py` |
| `484382d` | orchestrator | Crop tool (C) with the canvas rectangle, Crop menu, Ctrl+arrow nudge / Ctrl+Shift+arrow resize, hidden during output preview; more integration tests |

### The size estimate: measure a run, not single frames (`b9021ca`)
The summary card needed "Size: ≈ …". The first version encoded the sample frames **one at a time** and multiplied the average by the frame count. On a GIF with a static background it **overestimated by 3.4×**. The reason is how GIF (and our encoder) stores animation: every frame after the first is only the *difference* from the previous one (changed rectangle, unchanged pixels transparent). A frame encoded on its own is a full first frame, so each sample paid for the whole picture again.

The fix encodes a **contiguous** run of 5 output frames from the middle of the timeline as **one** stream, encodes the run's first frame alone, and uses the difference as the marginal cost of one more frame: `estimate = first + (run − first) / 4 × (n − 1)`. To encode in memory with the real encoder, the body of `write_gif` was split out as `write_stream` (any open binary stream; `write_gif` delegates to it), so the estimate counts the same bytes Generate would write and never touches the disk.

Measured: estimate / real = **1.00–1.18** on the photo-like and flat cases, **0.67** on a heavily cropped long case; **4–80 ms** per estimate. The UI labels it "≈ … (estimate)". Details: [pipeline page](codebase/src/gif_editor/core/pipeline.md#estimate_size-and-_encoded_size).

### The PC shutdown mid-milestone (`053ed66`, `e205656`)
The PC had to be shut down while two workers were running (the preview service and the crop item); the crop panel and the wiring had not started. **Background workers are not durable**: closing the machine kills them, and whatever they had not committed exists only as loose files. Before shutting down, the orchestrator:
- wrote `docs/RESUME-HERE.md`: what is done and committed, what is unverified, what was never started, the next steps in order, and the environment reminders;
- committed the half-finished `ui/inspector/preview.py` as a clearly **flagged snapshot** ("written but never tested or reviewed; treat as unverified"), then a lint/format commit, so nothing on disk was uncommitted.

On resume:
- **The crop-item worker had died before writing any file.** There was nothing to salvage, so it was restarted from its task spec and delivered `6e8a3ad`.
- **The preview worker's file was verified, not trusted** (`e904982`). Its test file had **4 broken tests** (fixed), and review found **one real thread-safety bug**: the pool-thread render read the live crop/size from the document. An edit made while a frame was rendering could leak into an image that was then cached and labelled with the old request. The worker now receives the geometry **captured at request time** as an argument and reads no shared state; a regression test queues a render with crop A, changes the crop to B, then runs the job and asserts crop A was used.

### Notable decisions
- **Two crop editors, no link between them.** `CropItem` (canvas) and `CropPanel` (settings panel) both write `doc.state.crop` and both refresh from `stateChanged`; neither imports the other. The two-way sync is free because both follow `Document`.
- **Merge keys per gesture.** Crop spinboxes use `"crop"`; each canvas drag uses a fresh `"crop-drag-N"` (like the timebar's `"trim-drag-N"`); buttons, nudges and the Crop tick use `None`. A shared `"crop"` key would have merged a drag with the spinbox edit that follows it (one undo would revert both). See [architecture §9](03-architecture.md#merge-keys-one-undo-step-per-gesture).
- **The checkable `QGroupBox` greys its inputs when unticked.** Qt force-disables the children of an unchecked checkable group box, and that overrides `setEnabled(True)`. The spec had the inputs always editable; we kept Qt's behaviour as the intended **"tick to crop"** UX: with no crop the numbers are read-only and show the full frame, and ticking creates a crop. Recorded as a deviation on the [crop panel page](codebase/src/gif_editor/ui/crop_panel.md#enabled-state).
- **Ticking with a full-frame centre makes an 80 % crop.** Ticking applies the Center rule. With no explicit output size the centred default is the whole frame, which normalises to `crop=None`, so the tick would do nothing. The panel then creates a centred crop at 80 % of each side instead.
- **P previews the whole output.** In M2, "Preview edits" played the edited timing only. Now the same toggle also turns on the canvas's geometry preview (crop + resize), because "what the GIF will look like" includes both. The geometry follows `Player.previewEditsChanged`, so the transport check box drives it too.
- **The canvas does not request preview frames itself.** `PreviewService` already follows `currentIndexChanged`; requesting from the canvas too rendered every frame twice.
- **Crop tool rules.** Off on a new file; turning it on with no crop creates a 10 % inset box (one undo step) so there is something to drag; a crop that appears from the panel (or undo) turns it on; hidden during output preview, because the shown image is already cropped and a source-pixel rectangle would be wrong there. Nudge/resize are window actions on Ctrl+arrows and Ctrl+Shift+arrows, because plain and Shift+arrows step frames.

### Verification
- Full suite: **640 passed + 2 xfailed** (the documented Pillow disposal-2 differences), stable over repeated runs; ruff format and lint clean.
- `test_crop_panel.py`, `test_crop_item.py`, `test_preview.py` and `test_m3_integration.py` were each run **3×** in a row with no flakes.
- A **real mouse drag** on the canvas (press, moves, release on the viewport at zoom 8) was tested end to end: the document is untouched mid-drag, one undo step on release, the crop panel follows. **Generate writes the canvas crop** (32×24 output after C on a 40×30 GIF).
- Layout check of the real window at **1300×820** (offscreen, screenshot): no overlapping panels; the Crop group sits between Output size and Quality; the settings panel now scrolls by about **75 px**; the live numbers (output size, Size estimate, crop status) were consistent. Screenshot: `out/m3-window.png` (`out/` is gitignored).

### Process note: never move a worker's file aside
To run the test suite while a worker was still busy, the orchestrator once moved that worker's in-progress file out of the way. That was a mistake: the worker was still writing the file, so the move raced with it. **Lesson:** to exclude a file that is still being written, pass `--ignore=<path>` to pytest (`scripts/test.sh --ignore=tests/ui/test_x.py`) and leave the file alone.

### Fixes after the documentation pass
The docs worker checked every claim against the code and found two real problems, both fixed by the orchestrator with regression tests:
1. **Crop actions that looked usable but did nothing.** "Remove crop" and the Ctrl+arrow nudge/resize actions were enabled whenever a file was open, but `CropItem` ignored them while the tool was off or hidden by "Preview edits". Now nudge/resize are enabled only while the rectangle is visible, and "Remove crop" works regardless of the tool (removing a crop set from the panel must not require showing the rectangle).
2. **The estimate rendered half the GIF.** `iter_output_frames` is a sequential generator, so reaching the middle sample run rendered and quantized every frame before it. `estimate_size` now slices the timeline to the run (`dataclasses.replace(timeline, frames=...)`), so it renders only the 5 run frames plus up to 16 palette samples, whatever the GIF's length. A test counts the rendered frames on a 200-frame GIF. The docstring, which still described an older "evenly spaced" algorithm, was rewritten, and `write_stream` was added to `encoder.__all__`.

Verification after the fixes: 644 passed + 2 xfailed, three full runs in a row.

### Known limitations (carried to M4)
- Space still toggles playback, so Space+drag does not pan in the app; middle-drag pans.
- The estimate can be low for long GIFs whose middle is unrepresentative (0.67 in the cropped long case).

### Documentation pass (end of M3)
New pages for `tests/core/test_estimate.py` and `tests/ui/test_m3_integration.py`; the pipeline, encoder, canvas, settings panel and main window pages updated; the codebase index completed (and its `test_main_window.py` link fixed); the architecture page shows the M3 widget tree, data flow and the merge-key scheme; README, AGENTS.md and RESUME-HERE describe the state after M3. Stale post-M2 details were corrected on the way (shortcut table, Ctrl+G guard, Generate warnings, the `fetch-devlibs.sh` comment).
