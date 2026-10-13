# GIF Editor

Offline Windows desktop GIF editor (Python 3.13 + PySide6). Load a GIF, scrub it frame by frame, trim, delete frames, crop with a draggable rectangle, change speed / FPS / size / quality, then **Generate** a new GIF. Ships as a single portable `GifEditor.exe` (Nuitka onefile).

Status: **Milestones 1–4 done** (core engine; window and inspector; crop and live preview; hardening). **M5, the single `.exe`, is in progress:** the build recipe, icon, checks and the Windows build workflow exist and the recipe was proven with a Linux build, but `GifEditor.exe` has not been built and tested on Windows yet (see [docs/04-development-log.md](docs/04-development-log.md#milestone-5-packaging) and [docs/RESUME-HERE.md](docs/RESUME-HERE.md)).

## Features (working today)
- **Open** a GIF from File → Open, the command line, or by dragging it onto the window. Decoding runs in the background, with browser-correct disposal and transparency; damaged files load as far as possible, with a warning.
- **Frame inspector:**
  - a zoomable canvas (Fit, 100 %, Ctrl+wheel, middle-drag pan) on a checkerboard;
  - a timebar with playhead and green/red trim handles that snap to frame boundaries (Alt = free);
  - a thumbnail filmstrip with multi-select;
  - play/pause and frame stepping;
  - **Preview edits (P)**: plays the output timing and shows each frame cropped and resized exactly as it will be written.
- **Edit** (all undoable, Ctrl+Z / Ctrl+Y):
  - trim by handles, by Start/Duration fields, or at the playhead (I / O);
  - delete and restore frames (deleting removes their time);
  - speed 0.25×–4×; FPS limit ≤ 50;
  - **crop** by dragging a rectangle on the canvas (crop tool C; 8 handles, Shift keeps the aspect, outside dimmed) or with the Crop fields (aspect presets Free / Original / 1:1 / 4:3 / 16:9 / 3:2 / 9:16, X/Y/W/H, Full image / Center / Reset); the two stay in sync, one undo step per drag;
  - output size with aspect lock or scale % (follows the crop unless set);
  - quality presets, or 2–256 colours with dithering on/off.
- **Live summary:** output frame count, duration, dimensions and warnings, updated on every edit, plus an **estimated file size** ("Size: ≈ 1.2 MB") computed in the background from a few real output frames.
- **Generate** in the background with progress and Cancel. Output uses a shared palette and lossless frame differencing, keeps the source's transparency and loop setting, is verified after writing, and replaces the destination atomically (a cancelled or failed run leaves it untouched).
- **Save the current frame as PNG**, as in the source or with crop/size applied.
- **Errors in plain words** (M4): a dialog says what happened and what to do ("this file is not a GIF", "it is damaged; 2 frames could be loaded", "that file is open in another program"), with the technical text behind **Show Details...**. A failed or cancelled Generate always reports that the destination file is unchanged.
- **Fits your screen** (M4): the window opens at most 90 % of the screen and centred, so it is usable on a 1080p laptop at 150 % scaling; **Generate** is pinned below the settings and never needs scrolling. Every field's tooltip (and screen-reader description) states its range and why — e.g. why FPS stops at 50.
- **Stays responsive on large GIFs** (M4): opening, playback, scrubbing, previewing and Generate all run off the GUI thread; a frame that would take too long to decode is fetched in the background instead of freezing the window.
- In progress: the `.exe` build (M5), see [Build the .exe](#build-the-exe).

## Run

Windows (PowerShell, from the repo root):
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PYTHONPATH="src"; .venv\Scripts\python -m gif_editor [file.gif]
```

## Build the .exe

Nuitka compiles to C and cannot cross-compile, so `GifEditor.exe` is built **on Windows**: on your PC, or by GitHub Actions.

**On your Windows PC** (PowerShell, from the repo root; the first build takes a long time: Nuitka compiles Python, the Qt bindings, Pillow and numpy to C, and may download a C compiler on first use):
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt -r packaging/build-requirements.txt
.venv\Scripts\python scripts\build.py
.venv\Scripts\python scripts\smoke_build.py out\dist\GifEditor.exe
```
The result is `out\dist\GifEditor.exe`, one file with everything inside. The smoke test must end with `OK: …`. If you changed `scripts\build.py`, run `.venv\Scripts\python scripts\check_build_flags.py` first (one second instead of a failed build).

**From GitHub Actions** (once the repo is on GitHub): Actions → **Build GifEditor.exe** → **Run workflow** (or push a tag like `v0.1.0`). The job tests, builds and smoke-tests the `.exe`; when it is green, download the artifact **`GifEditor-windows`** (a zip with `GifEditor.exe`) from the run's page. Artifacts are kept for 30 days.

The `.exe` unpacks itself into your temp folder when it starts and never writes next to itself, so it can run from any folder or a USB stick. It is not code-signed, so Windows SmartScreen may warn the first time.

**Hidden headless mode** (for the smoke test and scripting; no window, no Qt):
```powershell
GifEditor.exe --edit-spec in.gif "trim=0:400,delete=0:3,crop=8:6:40:30,size=32x24,colors=64,out=out.gif"
```
Items are comma-separated `key=value`; lists use colons (`delete=0:3:5`); whole numbers are milliseconds, decimals are seconds (`trim=0.5:1.5`). It prints one `RESULT …` or `ERROR …` line and exits 0 or 1. Full grammar: [headless page](docs/codebase/src/gif_editor/headless.md).

## Check

Windows:
```powershell
.venv\Scripts\ruff check . ; .venv\Scripts\ruff format --check .
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python -m pytest -q
```

Linux dev container (headless; fetches a project-local `libEGL` on first run):
```bash
scripts/test.sh                    # ruff format check + ruff lint + all tests
scripts/test.sh tests/ui -k trim   # extra arguments go to pytest
scripts/test-hidpi.sh              # the UI tests at 150 % and 200 % scaling
PYTHONPATH=src:tests .venv/bin/python scripts/stress_probe.py    # GUI-thread stalls on big/broken GIFs
PYTHONPATH=src:tests .venv/bin/python scripts/fuzz_decoder.py    # damaged-file fuzz (loads or refuses cleanly)
.venv/bin/python scripts/check_build_flags.py   # every Nuitka flag in scripts/build.py is real (~1 s)
.venv/bin/python scripts/make_icon.py --check  # committed icons match the generator (pixels)
```

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+O | Open GIF |
| Ctrl+G | Generate |
| Ctrl+Shift+S | Save current frame as PNG |
| Ctrl+W | Close the GIF |
| Ctrl+Q | Quit |
| Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) | Undo / redo |
| Del | Delete selected frame(s) (or the current frame) |
| Ctrl+Shift+Del | Restore selected frame(s) (Insert also works in the filmstrip) |
| I / O | Set trim start / end at the playhead |
| Space | Play / pause (a tap on the canvas; hold and drag to pan the frame view) |
| P | Preview edits: output timing **and** crop/resize on the canvas |
| C | Crop tool: show/hide the crop rectangle (creates a 10% inset crop if there is none) |
| Ctrl+Left / Right / Up / Down | Move the crop by 1 px (crop tool on) |
| Ctrl+Shift+Left / Right / Up / Down | Narrow / widen / shorten / lengthen the crop by 1 px (crop tool on) |
| Shift while dragging a crop handle | Keep the crop's aspect ratio |
| Left / Right | Previous / next frame |
| Shift+Left / Shift+Right | Back / forward 10 frames |
| Home / End | First / last frame |
| Ctrl+0 / Ctrl+1 | Zoom to fit / actual size |
| Ctrl++ / Ctrl+- | Zoom in / out |
| Ctrl+wheel, middle-drag, Space+drag | Zoom at the mouse, pan (canvas) |
| Alt while dragging a trim handle | Don't snap to frame boundaries |

Crop → Remove crop clears the crop (crop tool on). Single-letter and arrow keys go to a spin box while one has focus, so you can type in it. Click the canvas or the filmstrip to use them as shortcuts again.

## Documentation

Start at **[docs/README.md](docs/README.md)**: product brief, plan, architecture, development log, GIF primer, testing guide, and one page per source file under [docs/codebase/](docs/codebase/INDEX.md).
