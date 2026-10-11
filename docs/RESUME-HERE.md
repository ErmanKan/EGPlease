# RESUME HERE — after Milestone 4

**Written:** 2026-10-11, at the end of Milestone 4 (hardening).
**Repo:** `/workspace/projects/gif-editor` (host: `F:\Projects\gif-editor`), branch `main`.

## State

Everything is committed; no snapshot or unverified work is left.
Tests: **679 passed + 2 expected failures** (the documented Pillow disposal-2 differences), lint clean,
UI tests also green at 150 % and 200 % scaling (`scripts/test-hidpi.sh`).

| Milestone | Status |
|---|---|
| M1 Core engine (decoder, timeline, render, encoder, pipeline, self-test) | ✅ Done |
| M2 Window and inspector (document/undo, settings panel, canvas, timebar, filmstrip, player, transport, main window) | ✅ Done |
| M3 Crop and live preview (size estimate, `PreviewService`, `CropPanel`, `CropItem`, crop tool + Crop menu, P previews timing and geometry) | ✅ Done |
| M4 Hardening (plain-language errors, HiDPI, accessibility, responsive large-file handling, stability) | ✅ Done (last code commit `5c40830`, then the M4 documentation pass) |
| M5 Single `.exe` (Nuitka onefile) | ⏭ Next |

What M4 changed, one line each: `GifLoadError.kind`/`.info` and `ui/messages.py` (headline + what to do +
technical details behind "Show Details..."); a partly-loaded file gets a dialog; `_fit_to_screen` and a pinned
Generate button; tooltip + accessible description on every input; Space+drag pans; background rendering for
source frames too slow for the GUI thread (`GifSource.frames_to_decode`, `SYNC_DECODE_PIXELS`); closing during
Generate cancels and closes; worker relays are freed only after the worker leaves `emit()`; pool jobs are plain
callables (never a Python `QRunnable` subclass). See [the dev log, Milestone 4](04-development-log.md#milestone-4-hardening).

## Next: M5 (single `.exe`)

Nuitka `--onefile --enable-plugin=pyside6` build script, icon and version info, the licence bundle
(`packaging/licenses/`), and a Windows CI build artifact. Exit criterion: `GifEditor.exe` runs on a clean
Windows 11 VM with no Python, from any folder or a USB stick. See [02-plan.md §6](02-plan.md#6-milestones).

Notes for whoever builds it:
- The build must run on Windows (Nuitka compiles with MSVC or MinGW); it cannot be produced in this Linux
  container. The container can only lint, test and dry-run the build script's argument construction.
- Pillow is pinned at 12.3.0 because the decoder relies on undocumented `"gif"` decoder args; `core/selftest.py`
  verifies a decode/encode round trip at startup and the build must keep it working (a frozen build can break
  `Image.open` plugin discovery: check `--include-module=PIL.GifImagePlugin` if a GIF fails to open).
- The `.exe` must not write next to itself (a USB stick may be read-only): temporary files go to the system temp
  directory, which the encoder already does (`tempfile` + `os.replace`).

## Known issues carried forward

- The filmstrip has a fixed 140 px height, so at a small window (a 1366×768 laptop at 150 % is 911×512 logical)
  the canvas gets only ~184 px of height.
- The size estimate can be low (about 0.67×) on long GIFs whose middle is not representative of the rest.
- The crash and the deadlock seen in the test suite before `9ab961f` were never reproduced on demand after the
  fix; the 30-run soak is the evidence for them being gone (see the SOAK RESULT line in the dev log and
  [06-testing.md](06-testing.md)).

## Environment reminders

- Run tests with `scripts/test.sh` (sets `LD_LIBRARY_PATH` for the project-local libEGL in
  `.devlibs/` and `QT_QPA_PLATFORM=offscreen:configfile=scripts/offscreen-screen.json`).
  Plain `pytest` fails to import PySide6 here.
- `scripts/test-hidpi.sh` runs the UI tests at 150 % and 200 % (`QT_SCALE_FACTOR`).
- Test temp files live under `out/` (`--basetemp=out/pytest-tmp/run-<pid>`, `--capture=sys`), never `/tmp`.
  `scripts/stress_probe.py` and `scripts/fuzz_decoder.py` also work only inside `out/`.
- `scripts/fetch-devlibs.sh` re-downloads libEGL (SHA-256 pinned, gitignored) if `.devlibs/` is lost.
- To leave out a file that a worker is still writing, use `scripts/test.sh --ignore=<path>`;
  never move or rename a worker's file.
- Delegation workers are NOT durable: closing the PC kills them, and a provider key can be revoked mid-run
  (the M4 docs worker died at 26 files and its work had to be committed by the orchestrator). Commit early,
  snapshot unfinished work (clearly flagged), and update this note before shutting down.
- Subagents inherit the parent model by default; pin `delegation.model` in `config.yaml` on the host
  to run them on a cheaper model (not settable from inside the container).

## Full design history

See `docs/04-development-log.md` and `docs/02-plan.md` (with its deviations section).
