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

## Milestone 2: Window and inspector (in progress)
- Orchestrator foundation: `ui/document.py` (`Document`: the hub every widget talks to), `ui/commands.py` (one generic undoable `SetStateCommand` with gesture merging), `ui/workers.py` (`run_async` thread-pool helper), `ui/qt_image.py`.
- Parallel workers: settings panel, frame canvas, timebar, filmstrip, transport + player, plus a documentation worker.
- The user asked for extensive documentation, so `docs/README.md`, `docs/03…06`, a per-file page for **every** file under `docs/codebase/`, and this log were added. Keeping the per-file docs up to date is now part of the definition of done in `AGENTS.md`.
