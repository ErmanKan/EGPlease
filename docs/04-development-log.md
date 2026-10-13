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

## Milestone 4: Hardening

Goal (from [02-plan.md §6](02-plan.md#6-milestones)): large and corrupt files must not freeze or crash the app, and it must work at 150 % and 200 % scaling. The work list from [RESUME-HERE](RESUME-HERE.md) was: input limits explained in the UI, plain corrupt-file messages, a HiDPI pass, an accessibility audit, consistent error dialogs. Along the way the test suite showed two rare native failures (one crash, one hang) that took most of the milestone's care; they are described honestly below, including what is still unknown.

### Commits
| Commit | Delivered |
|---|---|
| `d3f0297` | HiDPI test pass (virtual 4K offscreen screen, `scripts/test-hidpi.sh`); accessible names for three unnamed containers; `GifLoadError.kind` / `.info`; `scripts/stress_probe.py` |
| `95b4f03` | Plain-language error dialogs: `ui/messages.py`, `MainWindow.show_explanation` (headline, what to do, technical details behind Show Details…); Information dialog for a partly-loaded file; `tests/ui/test_messages.py` |
| `c4b9329` | Workers: a relay is freed only after its worker has left `emit()`; autouse `_drain_workers` fixture; test temp files inside the project (`--basetemp`, `--capture=sys`) |
| `9361dd6` | The window fits the screen at high scaling; Generate pinned below the settings; closing during Generate closes after the cancel; `app.main` waits for workers before exit; one temp folder per test run |
| `0b07218` | Space+drag pans the canvas (the canvas claims Space via `ShortcutOverride`; a tap still plays) |
| `39e533b` | Every setting explains its range and why (tooltip + accessible description); plain self-test failure dialog |
| `c254cc1` | `scripts/fuzz_decoder.py`: damaged corpus files must load or be refused cleanly |
| `9ab961f` | Pool jobs are plain callables, not a Python `QRunnable` subclass |
| `5c40830` | Expensive source frames render off the GUI thread (scrub stall 384 ms → 28 ms); non-blocking `GifSource.frames_to_decode`; no tracebacks for handled worker errors |

### HiDPI: the test screen was too small, not the app (`d3f0297`)
Running the UI tests at `QT_SCALE_FACTOR=2` made one timebar test fail. The cause was the test environment: Qt's default offscreen screen is **800×600 physical pixels**, which at 200 % is only **400×400 logical** pixels, smaller than the test windows. Qt does not deliver mouse events outside the screen, so a click past x=400 never arrived. The fix is a configuration file, [`scripts/offscreen-screen.json`](codebase/config-files.md#scriptsoffscreen-screenjson), that gives the offscreen platform one virtual **3840×2160** screen; `scripts/test.sh` passes it with `QT_QPA_PLATFORM=offscreen:configfile=…`. The new [`scripts/test-hidpi.sh`](codebase/scripts/test-hidpi.md) runs `tests/ui` at 1.5 and 2. At the end of the milestone: **278 passed at 150 %, 278 passed at 200 %**. No app code needed a HiDPI fix: painting already used cosmetic pens and logical pixels.

### The window did not fit the screen (`9361dd6`)
The window opened at a fixed 1300×820. Display scaling shrinks the screen in logical pixels, and the measured logical sizes were all smaller than that:

| Screen and scaling | Logical size |
|---|---|
| 1366×768 at 150 % | 911×512 |
| 1920×1080 at 150 % (the most common laptop setup) | 1280×720 |
| 1920×1080 at 200 % | 960×540 |
| 1280×800 at 125 % | 1024×640 |

So on every one of these the bottom of the window, with the Generate button, was off-screen. Now `MainWindow._fit_to_screen` opens at the preferred 1300×820 but **at most 90 % of the available screen**, centred. The window's minimum size is **779×344**, which fits all four. The Generate button also moved **out of the settings scroll area** into a pinned footer below it: the main window removes it from the panel's layout, while the panel still owns the button and its `generateRequested` signal. At 150 % on a 1080p laptop the settings column scrolls, and the main action must not scroll away with it.

Remaining limitation: at 911×512 the canvas gets only about **184 px** of height, because the filmstrip has a fixed height of 140 px.

### Accessibility (`d3f0297`, `39e533b`)
- **Audit:** every control already had an accessible name except three containers: the `Inspector`, the settings `QScrollArea` and the `CropPanel`. They are now "Frame inspector", "Output settings" and "Crop settings". The tab order was checked and found logical, so it was not changed.
- **Inputs explain their limits.** Spin boxes silently clamp typed values to their range, which looks like the app ignoring you. `SettingsPanel._explain(widget, text)` sets the same text as tooltip and accessible description, stating each range **and why**: FPS max 50 because GIF delays are whole hundredths of a second and viewers slow down delays under 20 ms; at most 256 colours per GIF; 8,192 px maximum side; for speed, frames that would be shorter than 20 ms are merged and the summary shows how many. `test_every_input_explains_its_limits` enforces that every input has such a text.
- **A wrong claim, caught in review.** A draft of the speed tooltip said that very high speeds make a GIF play *slower*. That is what happens with a naive writer, not with ours: the timeline never writes a delay under 20 ms, it folds the short frames into their neighbours. The text was corrected before commit. The test checks that the texts exist and name the key numbers; it cannot check that a claim is true, so tooltip wording must be checked against `core/timeline.py` by hand.

### Errors in plain language (`d3f0297`, `95b4f03`, `39e533b`)
Before M4 the dialogs showed the core's technical messages ("Could not open x.gif:\nCanvas 70000x2 exceeds the maximum side of 8192 px"). Now:
1. The core says *why*: `GifLoadError` has a `.kind` (`NOT_FOUND`, `IS_DIRECTORY`, `UNREADABLE`, `EMPTY`, `NOT_GIF`, `TOO_LARGE`, `TOO_MANY_FRAMES`, `MALFORMED`) and an `.info` dict with the numbers. The message text is unchanged, so tests that match it still pass.
2. The new [`ui/messages.py`](codebase/src/gif_editor/ui/messages.md) turns an exception into an `Explanation(title, headline, body, details)`: `explain_load_error`, `explain_load_warnings` and `explain_generate_error`. For write errors it maps `errno` `EACCES`/`EPERM`, `ENOSPC`, `ENOENT`, `ENAMETOOLONG` and `MemoryError`, with a fallback. On Windows a file locked by another program fails with `EACCES` too, so `winerror` 32/33 (sharing/lock violation) is checked first and reported as "open in another program", not as "no permission". Every write-failure message says **"Nothing was written; any existing file with that name is unchanged."**, which is true because both writers use a temp file + rename.
3. `MainWindow.show_explanation(expl, icon)` shows the headline, the body as informative text, and the technical details behind Qt's **Show Details…** button. It keeps `last_error` (headline + body) and `last_dialog` for the headless tests.
4. A **partly-loaded** (truncated) file now gets an Information dialog ("“x.gif” is damaged; 3 frames could be loaded.") instead of a status-bar line that vanished after 8 s, because a partial file changes the result.
5. The **startup self-test** failure (only possible with a broken build) now says "GIF Editor can't start because one of its components is not working… Download it again", with the technical text kept as details.

`tests/ui/test_messages.py` covers the branches with real files where possible and checks that no jargon ("Errno", "malformed", "decodable", "exceeds"…) appears in a headline or body. (Not covered: the `UNREADABLE` branch, which needs an existing file that cannot be read.)

### Shutdown (`9361dd6`)
- **Closing during Generate.** The close used to be ignored with "close again in a moment". Now the first close cancels Generate and sets `_close_when_idle`; when the worker reports back, `finish()` closes the window with `QTimer.singleShot(0, self.close)`. One click is enough, and nothing is torn down under a running worker.
- **Waiting for workers at exit.** `app.main` calls `QThreadPool.globalInstance().waitForDone(10_000)` after `app.exec()` returns, so Python's interpreter teardown never runs while a pool thread (a preview render, the size estimate, a thumbnail batch) is still alive.

### Space+drag pan, finally (`0b07218`)
Known since M2: the window's Space play/pause shortcut ate the key, so the canvas's Space+drag pan never started. Qt offers every key to the focused widget as a `ShortcutOverride` event before firing a window shortcut. `FrameCanvas.event` now **accepts** that event for plain Space while a file is open, so the canvas receives Space as a normal key. A tap without a mouse press emits the new `spaceTapped` signal, which the main window connects to `player.toggle`, so tapping Space on the canvas still plays and pauses. With another widget focused, Space plays through the window action as before. The drag test **fails with the fix disabled** (checked), so it really tests the fix.

### Big GIFs: the scrub stall (`d3f0297`, `5c40830`)
The new [`scripts/stress_probe.py`](codebase/scripts/stress_probe.md) opens hard files through the real `MainWindow` and measures GUI-thread stalls with a 10 ms `QTimer` (the gap between ticks is how long the window was frozen), for open, scrubbing backwards, playing, preview and Generate.
- 1280×720×150 frames: open 0.69 s, worst stall 51 ms. Fine.
- 1920×1080×200 frames (bigger than the 512 MB frame cache): open 1.9 s, but **scrubbing backwards stalled up to 384 ms** (10 stalls over 100 ms). The canvas decoded the frame on the GUI thread, and a backward step past the cache means re-compositing up to ~30 full frames from a checkpoint.

The fix:
1. `GifSource.frames_to_decode(i)` says how many frames `frame(i)` would composite (mirroring `_resume_point`, without copying any canvas).
2. The canvas computes `frames × pixels`; above `SYNC_DECODE_PIXELS = 4,000,000` (about 25 ms) it asks `PreviewService.request_frame(i)` (with geometry off, that renders the plain source frame; latest request wins) and keeps the old frame up until the new one arrives (`_awaiting_source`). Small GIFs and playback (the next frame costs 1) stay synchronous.
3. **The first version still stalled 643 ms.** `frames_to_decode` waited for the decoder lock, which the background render was holding. It now never blocks: if another thread holds the lock it returns `GifSource.BUSY` (a huge cost), so the canvas goes asynchronous. Result: **worst stall 28 ms, none over 100 ms.**

The corrupt corpus files in the probe showed the new plain messages.

### Fuzzing the decoder (`c254cc1`)
[`scripts/fuzz_decoder.py`](codebase/scripts/fuzz_decoder.md) damages the corpus GIFs (byte flips, truncation, inserted junk, header bytes, zero runs, duplicated slices), opens each with `GifSource`, renders every frame, and allows 10 s per case. **22,750 damaged files** over seeds 1–3: about **59 %** refused with `GifLoadError`, **28 %** loaded with warnings, **13 %** loaded; **0 unexpected exceptions, 0 hangs**. The slowest case took 711 ms (a damaged header declaring a large canvas). It writes only inside `out/fuzz/`.

### Stability: one crash and one hang in the test suite (`c4b9329`, `9ab961f`)
This part is told in full because **the root cause is not confirmed**.

**What happened.**
1. After the test temp files were moved onto the project drive, one full-suite run died with a **segmentation fault in a native pool thread** (1 run of about 16). The main thread was in `pathlib.stat` at that moment, i.e. doing nothing unusual.
2. Later, one run **deadlocked** at about 97 %. A `faulthandler` dump (triggered with `SIGABRT`) showed the GUI thread "Garbage-collecting" inside `run_async`, and a pool thread at the entry of the Python `QRunnable` subclass's `run()` method.

**How it was investigated.** Probes started **120,000 tasks** through `run_async`, with both `QCoreApplication` and `QApplication`, with forced garbage collection. They reproduced **neither** failure.

**What was changed** (each change removes a plausible cause; none is proven to be *the* cause):
- (a) **Relay lifetime** (`c4b9329`). A worker emits `finished`, and the GUI thread could run the callback and delete the relay before the worker had returned from `emit()`. Deleting a `QObject` while another thread is inside its emit is undefined behaviour. Now the worker sets a `threading.Event` (`exited`) when it is done, and `_release` frees the relay only after that, retrying with `QTimer.singleShot(1)`.
- (b) **Drain after every UI test** (`c4b9329`). The autouse `_drain_workers` fixture in `tests/ui/conftest.py` (it depends on `qtbot`, so it tears down first) waits for the pool and processes events after each UI test. Before, a worker from one test could still be calling back while the next test set up, an ordering that never happens in the app.
- (c) **No Python `QRunnable` subclass** (`9ab961f`). Jobs are plain callables passed to `QThreadPool.start(callable)`. With a subclass, Qt calls a Python-overridden `run()` on a C++-owned object from a pool thread, and PySide must keep the Python wrapper alive and dispatch the override across threads; the deadlock dump pointed exactly there. A plain callable has no such wrapper.
- Also (`5c40830`): workers print a traceback only when no `on_error` handler exists, so the test output (and a user's console) is not filled with tracebacks of errors that were handled.

**Soak test.** A 30-run soak on the frozen HEAD (a git worktree under `out/`, see [06-testing](06-testing.md#soak-test-repeated-full-runs)) checks whether either failure comes back:

**30 of 30 runs exited 0** (679 passed + 2 xfailed each, 36-49 s per run); no exit 1, no 124 (timeout/hang), no 139 (segmentation fault). Root cause of the two pre-fix failures remains unidentified, but nothing reproduced in 30 consecutive full runs on the fixed code (plus the 18 runs during development: 48 clean runs in total since `9ab961f`/`c4b9329`).

**Still unknown:** what exactly crashed and what exactly deadlocked. If either appears again, the `faulthandler` dump (`kill -ABRT <pytest pid>` for a hang) is the first thing to collect.

### Test infrastructure (`c4b9329`, `9361dd6`)
- **Temp files inside the project.** Earlier probes and pytest itself wrote to the container's `/tmp`, a violation of the project's hard rule (files only inside the repo). It was cleaned up. `scripts/test.sh` now passes `--basetemp=out/pytest-tmp/run-<pid>`: **one folder per run**, and folders of runs that have exited are removed by the next run.
- **Why per run.** pytest empties `--basetemp` when it starts. With one shared folder, a second run wiped the corpus files of a run in progress: **40 failures** in a parallel run.
- **Why `--capture=sys`.** pytest's default `fd` capture uses temp files that are deleted while still open; the `F:` drive mount rejects that, so `TMPDIR` cannot simply point into the project. `sys` capture keeps output in memory.
- **Cost:** the full suite went from about **15 s to about 38 s**, because the temp files now live on the mounted drive.

### The orchestrator's own mistakes
Recorded so they are not repeated:
1. **Probes wrote to `/tmp`.** The worker-crash probes and the pytest runs used the container's `/tmp`, which the hard rules forbid. Cleaned up; all tools now write under `out/`.
2. **A test run started next to a running soak loop** shared its temp folder and wiped it (the 40 failures above). This is what led to the per-run folders. Lesson: never start a second test run that shares a temp folder with a running one.
3. **`pkill -f` killed its own shell.** Stopping the soak loop with `pkill -f <pattern>` matched the orchestrator's own command line (which contained the pattern), so it killed the shell it was running in. Lesson: kill by PID, or use a pattern that cannot match the command doing the killing.
4. **A wrong tooltip claim** (speed) was written and only caught in review (see Accessibility above).

### Verification
- Full suite: **679 passed + 2 xfailed** (the documented Pillow disposal-2 differences), about 39 s; ruff format and lint clean.
- HiDPI: `scripts/test-hidpi.sh` **278 passed** at 150 % and **278 passed** at 200 %.
- Fuzz: **22,750** damaged files, 0 unexpected exceptions, 0 hangs.
- Stress probe: 1080p×200 scrub worst stall **384 → 28 ms**, no stall over 100 ms.
- Soak: see the SOAK RESULT line in the stability section above.

### Known limitations (carried to M5)
- The filmstrip has a fixed height of 140 px, so on the smallest screens (911×512 logical) the canvas gets only about 184 px.
- The size estimate can be low (0.67×) on long GIFs whose middle is unrepresentative.
- The root cause of the one crash and the one hang is unconfirmed; three plausible causes were removed and a soak run checks the result.

### Documentation pass (end of M4)
New pages for `ui/messages.py`, `tests/ui/test_messages.py`, `scripts/test-hidpi.sh`, `scripts/stress_probe.py` and `scripts/fuzz_decoder.py`; `offscreen-screen.json` added to the config page; the workers, decoder, canvas, main window, settings panel, app, `test.sh`, UI conftest and test pages updated; the architecture page's threading section rewritten and an error-flow section added; this section; the testing guide (HiDPI, fuzz, stress, soak, temp-dir policy); README, RESUME-HERE and AGENTS.md describe the state after M4. Stale test counts on two older pages (`test_estimate`, `test_m3_integration`) were corrected on the way.

## Milestone 5: Packaging

Goal (from [02-plan.md §6](02-plan.md#6-milestones)): a single `GifEditor.exe` (Nuitka onefile with the PySide6 plugin), with an icon and version information, a licence bundle and a Windows CI build artifact. **Done when** the `.exe` runs on a clean Windows 11 machine with no Python installed, from any folder or a USB stick.

**Status at the end of this section: in progress.** The build recipe, the icon, the checks and the CI workflow exist and were proven by building a *Linux* binary. The Windows `.exe` itself has not been produced yet, for the reason explained first below.

### Commits
| Commit | Delivered |
|---|---|
| `3531ca0` | `scripts/build.py` (Nuitka onefile recipe), `scripts/make_icon.py` and the generated icons, `gif_editor/resources` (`icon_path`), the hidden `--edit-spec` mode (`gif_editor/headless.py`, handled in `app.main` before any Qt import), window icon, `scripts/smoke_build.py` |
| `4779648` | `.github/workflows/build-exe.yml` (Windows build + smoke test + artifact) and the pinned `packaging/build-requirements.txt` |
| `c777acb` | `docs/RESUME-HERE.md` rewritten before a planned PC shutdown |
| `a2e41d0` | Fix: `icon_path()` looked in `resources/resources` and never found the icon; `scripts/check_build_flags.py` validates every Nuitka flag for both platforms; `build_command(windows=)`; `headless` docstring fixed and `_ms` helper; tests `test_headless.py`, `test_resources.py`, `test_check_build_flags.py` |
| `7bac56c` | Fix: the smoke test would have hung and never tested Qt; `--smoke-gui`; pass/fail by exit code and file; `make_icon.py --check` compares pixels; flag check in the build workflow |

### Why there is no `.exe` yet: Nuitka cannot cross-compile
Nuitka translates Python to C and compiles it with the target platform's C compiler, so a Windows `.exe` must be built **on Windows**. The development container is Linux with no Windows toolchain: no MSVC, no mingw, no wine. The Windows host is not executable from inside it either (its `C:` drive is visible only as inert files). So the `.exe` can come from two places only:
1. the GitHub Actions workflow [`build-exe.yml`](codebase/config-files.md#githubworkflowsbuild-exeyml) on a `windows-latest` runner (it uploads `GifEditor-windows`), or
2. the user's Windows PC (`python scripts\build.py`; commands in the [README](../README.md#build-the-exe)).

What *was* done here: the **same recipe** was built for Linux. The result, `out/dist/GifEditor`, is an **11.5 MB** self-contained onefile whose only dynamic dependency is the C library. That proves the parts of the recipe that do not depend on the OS: the include rules, the package data (icons), the PySide6 plugin, the onefile packing. It does not prove the Windows-only parts (the `.ico` resource, console mode `attach`, Windows DLLs); those are validated by the flag checker below and, finally, by the first Windows build.

### Four wrong flags, four lost builds
A from-scratch Linux build took about **20 minutes** in the container (why it is that slow *here* is explained [below](#two-wrong-claims-about-why-the-build-was-slow); it is not the drive and not the C compiler). Four mistakes in `scripts/build.py` were each found only by running a build, before a flag checker existed; each cost about one ~20-minute build cycle:
1. **`--cache-dir`**: not a Nuitka option; Nuitka rejected it (that build exited with code 2). Nuitka's cache location is set with the `NUITKA_CACHE_DIR` environment variable, not a flag.
2. **`--no-console`**: not a Nuitka option either (rejected the same way). The real one is `--windows-console-mode=…` (`attach` on Windows: output reaches a terminal if started from one, no console window otherwise).
3. **Missing `--include-package=gif_editor`**: pointed only at `__main__.py`, Nuitka compiled happily, but the binary died at start with `No module named 'gif_editor.app'`. This one cost a *full* compile plus a run.
4. **Missing `PYTHONPATH` for `--include-package`**: the option is resolved through the build interpreter's import path, which does not contain `src/` (the app is never installed). Nuitka stopped with "failed to locate package". `build.py` now sets `PYTHONPATH=src` for the Nuitka child process.

A fifth flag was removed rather than fixed: `--onefile-tempdir-spec` with `{TEMP_DIR}`. That variable does not exist (Nuitka's is `{TEMP}`), and the default already unpacks into the user's temp folder, which is exactly what we want: the `.exe` never writes next to itself, so it works from a read-only folder or a USB stick.

**The fix for the process** (`a2e41d0`): [`scripts/check_build_flags.py`](codebase/scripts/check_build_flags.md) imports Nuitka's own option parser and checks every flag of both the Linux and the Windows command line in about a second. `build_command` gained a `windows=` parameter for that, so the Windows command can be checked on Linux. Two details had to be modelled: `--enable-plugin` (the documented spelling) is accepted by Nuitka as an abbreviation of `--enable-plugins`, and the `--noinclude-*-mode` options are registered only while a command line is parsed, so neither is in the static table. `--windows-console-mode` turned out to be accepted on every platform (Nuitka only warns); the truly Windows-only flag is `--windows-icon-from-ico`. Its test injects each historical mistake and checks it is caught. AGENTS.md now says: run the checker after touching `build.py`. (Re-reading Nuitka 4.3's source for the docs pass showed that the checker's rule for `--noinclude-*-mode` is stricter than Nuitka needs; see the [checker page](codebase/scripts/check_build_flags.md#why-the-plugin-options-are-special). It can only cause a false alarm, never miss an error.)

### The icon that never loaded
`gif_editor/resources/__init__.py` resolves bundled files. Its first version took the folder of `__file__` (which already *is* `resources/`) and appended `"resources"` again, so it looked in `resources/resources/icons/`. Because the helper is designed never to raise (a missing icon must not stop the app), nothing failed: `icon_path()` returned `None` and the app **never set its window icon**, from source or in a build. The new `tests/core/test_resources.py` caught it the first time it ran. Fixed in `a2e41d0`; after the fix the application's window icon was verified to be non-null. Lesson: a helper that hides failures needs a test that the normal case actually finds something.

### The smoke test would have hung
`scripts/smoke_build.py` runs a built binary as a child process. Its first version (`3531ca0`) was written while no binary existed yet. Reading it again **before its first real run** found two faults:
1. **It would have hung.** Its first step started the binary with a missing file and expected exit code 1. But that starts the **GUI**: the window opens, shows its "can't open file" dialog, and keeps running until someone closes it. Nobody would.
2. **It never exercised Qt.** Its other step used `--edit-spec`, which by design returns before anything imports Qt. A binary missing its Qt platform plugin, the most likely packaging failure, would have passed.

The rewrite (`7bac56c`) has three steps: a missing file through `--edit-spec` (exit 1, no traceback); a real edit (exit 0 and a 32×24 GIF on disk); and the new **`--smoke-gui`** flag, which starts the real window offscreen, opens the GIF and makes the app quit by itself with exit code 0 or 1 (`app._arm_smoke_exit` polls every 50 ms, 30 s timeout). It also stopped depending on printed output: a Windows GUI executable with console mode `attach` may not deliver stdout to a pipe, so pass/fail is decided by **exit codes and the written file only**; the printed `RESULT`/`GUI OK` lines are diagnostics.

### The icon and its check
The icon is generated by [`scripts/make_icon.py`](codebase/scripts/make_icon.md): a dark rounded plate with a white play triangle, plus green film sprockets from 48 px up. Small sizes (≤ 32 px) are **drawn as a simplified design**, not scaled down: at 16 px the detailed design came out as a featureless dark square. Every size is drawn at 4× and reduced (anti-aliased edges), and `icon.ico` holds 16, 24, 32, 48, 64, 128 and 256 px.

The first CI step regenerated the icons and failed on `git diff`. That compares **bytes**, and PNG/ICO bytes depend on the zlib inside Pillow's wheel, which differs between Windows and Linux, so a Windows runner could fail on pixel-identical files. `make_icon.py --check` (`7bac56c`) compares **decoded pixels** instead; a deliberate 1-pixel change was verified to be caught.

### The headless `--edit-spec` mode
`GifEditor --edit-spec IN.gif "trim=0:400,delete=2,crop=8:6:40:30,size=32x24,out=OUT.gif"` runs one edit and Generate with no window and prints `RESULT …` or `ERROR …` ([headless page](codebase/src/gif_editor/headless.md)). It exists so a packaged build can be checked automatically, and it runs exactly the GUI's Generate code. `app.main` handles it **before any Qt import**: importing Qt loads `libEGL` and a platform plugin, and this path must work on a bare server. The first docstring documented `delete=0,3,5`, which the grammar cannot express (commas separate items; lists use colons: `delete=0:3:5`); it was noticed while writing `tests/core/test_headless.py` and fixed in `a2e41d0`, together with rounding instead of truncating when a decimal (seconds) is converted to milliseconds.

### Container quirks
- **`patchelf`.** Nuitka's onefile mode on Linux needs the `patchelf` tool. Installing it system-wide would break the hard rule, so it is installed **project-locally** as the pinned wheel `patchelf==0.19.1.0` in the venv (and listed in `packaging/build-requirements.txt` for non-Windows only). A local build needs `.venv/bin` on `PATH`.
- **`noexec` mounts.** `/tmp`, `/dev/shm`, `/var/tmp` and the project drive are mounted `noexec` in the container. A onefile binary unpacks itself into `TMPDIR` and executes the unpacked program, so in the container it only runs with `TMPDIR` pointed at an executable folder under `$HOME`. This affects only the container; Windows and CI need nothing.

### Two wrong claims about why the build was slow
The Linux builds in the container took about 20 minutes. The orchestrator explained this wrongly **twice**; both explanations are recorded here because they were stated as facts.

**Wrong claim 1: "the `F:` drive is slow."** The orchestrator blamed the project's `F:` drive (a Windows drive mounted into the container). **The user challenged this, and a measurement showed it was wrong.** Writing and reading 300 small files took **636 ms** on the project drive vs **655 ms** on the container's own disk; sequential throughput was **247 MB/s** vs **207 MB/s**. The drive is not slow.

**Wrong claim 2: "it is the C compile plus the rebuilds."** The orchestrator's replacement explanation was not measured either, and it was also wrong. **Profiling the running build** showed that during the slow phase **no compiler runs at all**. The time goes into Nuitka's Linux dependency scan:
- for every shared library it bundles (**269 `.so` files** in PySide6 alone) Nuitka runs `ldd` once, with an `LD_LIBRARY_PATH` of **104 directories** that it builds itself;
- `ldd` on one Qt plugin (`libqtga.so`) took **30 ms** with no `LD_LIBRARY_PATH`, **4.4 s** with Nuitka's 104-directory path on the `F:` drive, and **5.9 s** with 104 *empty* directories on the container's own disk;
- the cause is failed file lookups: `ldd` tries each needed library in each of the 104 directories, and a lookup that finds nothing costs **158 µs** on `F:` but **1,054 µs** on the container's own disk (Docker overlayfs with about 20 lower layers, where every miss is checked in each layer).

So the slow part is (number of libraries) × (104 directories × each library they need) × (slow negative lookups in this container). It is neither the `F:` drive (which is actually the *faster* place for these misses) nor the compiler. **On Windows, Nuitka uses its own DLL dependency walker instead of `ldd`**, so CI and the user's PC do not hit this.

Lesson: measure before explaining, and an explanation that replaces a refuted one needs a measurement too. This also puts a question mark on the M4 explanation that the test suite slowed from about 15 s to 38 s *because* its temp files moved onto the mounted drive; that explanation was never measured in the same way and has not been re-checked.

### A test that is flaky under load
One full-suite run made *during* a Nuitka build failed `tests/core/test_timeline.py::test_performance_10k_frames`, which asserts that planning 10,000 frames takes under **50 ms** of wall-clock time. The machine's load average was **4.7** (normally about 1.7) because of the running build. It passes alone and in every other run. It is a known **flaky-under-load** test: if CI ever reports it, check the runner's load before suspecting the timeline code.

### The PC shutdown mid-milestone
The user's PC had to be shut down in the middle of M5. Before that, all work was committed and `docs/RESUME-HERE.md` was rewritten (`c777acb`) with the state, the next steps and the container quirks, so the work could be resumed without the conversation history (the same procedure as in M3).

### Verification
- Full suite: **709 passed + 2 xfailed** (679 from M4, plus 19 + 5 + 6 new); ruff format and lint clean.
- `scripts/check_build_flags.py`: Linux and Windows command lines valid (22 arguments each).
- `scripts/make_icon.py --check`: icons up to date.
- Linux onefile build of the same recipe: 11.5 MB, only libc dynamic.

LINUX BINARY SMOKE RESULT: pending (filled in by the orchestrator)

### Still open for M5
- **The exit criterion is not met yet:** `GifEditor.exe` has never been built or run. Next: run `build-exe.yml` (or build on the user's PC), then run the `.exe` on a **clean Windows 11 VM without Python**, from a normal folder and from a USB stick.
- **Licence bundle:** `packaging/licenses/` contains only a `.gitkeep`. The `.exe` bundles Python, Qt/PySide6 (LGPL), Pillow, numpy and others, whose licence texts must ship with it.
- **Code signing:** optional (plan §6); an unsigned `.exe` will trigger Windows SmartScreen warnings on other people's machines.
- Small code fixes the docs pass found, applied afterwards by the orchestrator: `build.py`'s docstring claimed a cache under `out/nuitka-build/` (now describes the real cache and the build-time cause); `check_build_flags.py` printed `Nuitka unknown` (now reads `nuitka.Version.getNuitkaVersion()`); under `--smoke-gui` a failed self-test showed a blocking dialog, so the smoke test would only fail at its 120 s timeout (now it prints `GUI FAIL startup self-test: ...` and exits 1 at once); and `app.main`'s `--edit-spec` and `--smoke-gui` branches had no tests (5 added to `tests/ui/test_smoke.py`).

### Documentation pass (M5)
New pages for `scripts/build.py`, `check_build_flags.py`, `make_icon.py`, `smoke_build.py`, `gif_editor/headless.py`, `gif_editor/resources/__init__.py` and the three new test files; the icons, `packaging/build-requirements.txt` and `build-exe.yml` added to the config page; the `app.py` page updated (`--edit-spec`, window icon, `--smoke-gui`, file argument); INDEX rows (and two missing page links fixed); this section; the testing guide (build checks, smoke test, the `TMPDIR` note); README (status, *Build the .exe*), AGENTS.md (M5 interfaces and rules) and the architecture tree.
