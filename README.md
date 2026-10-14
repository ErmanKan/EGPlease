# GIF Editor

An offline Windows desktop tool for reshaping existing GIFs. Open a GIF, scrub through it frame by frame, then trim it,
delete frames, crop it, change its speed, frame rate, size or colours, and click **Generate** to write a new GIF. Every
edit is non-destructive and undoable until you generate; the original file is never touched.

It ships as **one portable file, `GifEditor.exe`**: no installer, no Python, runs from any folder or a USB stick.
A [Docker image](#docker) runs it on Linux and macOS too, and runs scripted edits.

**Status:** version 0.1.0. The editor itself is complete (milestones 1–4). Packaging (milestone 5) is almost done:
GitHub Actions builds `GifEditor.exe` and it passes the automated smoke test on Windows. Still open: a test on a clean
Windows 11 machine without Python, and the bundled licence texts. Details: [docs/RESUME-HERE.md](docs/RESUME-HERE.md).

## Get it

- **Download:** GitHub → **Actions** → **Build GifEditor.exe** → the latest green run → artifact **`GifEditor-windows`**
  (a zip with `GifEditor.exe`). Artifacts are kept for 30 days; start a new run with **Run workflow** if they have expired.
- **Build it yourself:** see [Build the .exe](#build-the-exe).

The `.exe` is not code-signed, so Windows SmartScreen may warn the first time: **More info → Run anyway**.

## How to use it

1. **Open a GIF:** File → Open (Ctrl+O), drag it onto the window, or pass it on the command line
   (`GifEditor.exe file.gif`).
2. **Look through it:** press Space to play, Left/Right to step a frame, or drag the playhead on the timebar.
3. **Edit:**
   - **Trim:** drag the green and red handles on the timebar, or press **I** / **O** to set the start / end at the playhead.
   - **Delete frames:** select thumbnails in the filmstrip and press **Del** (Ctrl+Shift+Del restores them).
   - **Crop:** press **C** and drag the rectangle on the canvas, or type exact values in the Crop fields.
   - **Speed, FPS, size, quality:** set them in the panel on the right.
4. **Check the result:** the summary shows the output frame count, duration, dimensions and estimated file size.
   Press **P** to preview the exact output timing, crop and size on the canvas.
5. **Generate** (Ctrl+G): choose where to save. It runs in the background with a progress bar and a Cancel button.

Undo and redo with Ctrl+Z / Ctrl+Y. Hover over any field for its allowed range and why (for example, FPS stops at 50
because browsers slow down GIFs with faster frame delays).

## Features

- **Faithful decoding:** frames are composited the way browsers show them (disposal, transparency). Damaged files load
  as far as possible, with a warning saying how many frames could be read.
- **Frame inspector:** zoomable canvas (Fit, 100 %, Ctrl+wheel, pan), timebar with snapping trim handles, thumbnail
  filmstrip with multi-select, play/pause and frame stepping.
- **Edits:** trim, delete and restore frames, speed 0.25×–4×, FPS limit up to 50, crop (drag with 8 handles or type values,
  with aspect presets such as 1:1 and 16:9), output size by pixels or %, and quality presets or 2–256 colours with dithering on or off.
- **Live summary and size estimate:** updated on every edit; the size is estimated from a few real output frames.
- **Safe output:** uses a shared palette and lossless frame differencing, keeps transparency and the loop setting, reads
  the file back to verify it, and replaces the destination only at the end. A cancelled or failed run leaves the file unchanged.
- **Save the current frame as PNG**, as in the source or with the crop and size applied.
- **Plain-language errors** ("that file is open in another program"), with the technical details behind **Show Details...**.
- **Stays responsive on large GIFs:** loading, playback, preview and Generate all run off the GUI thread.
- **Fits small screens:** usable on a 1080p laptop at 150 % scaling.
- **Light and dark mode:** follows the Windows setting, switches live, and keeps buttons and icons clearly visible in both.

## Tech stack, and why

| Part | Choice | Why |
|---|---|---|
| Language | **Python 3.13** | Fast to write and test; the whole stack has mature, pinned wheels for it. |
| User interface | **PySide6-Essentials 6.12** (Qt Widgets) | Native-looking, high-DPI aware desktop UI. Qt provides the building blocks this app needs: `QGraphicsView` for the zoomable canvas and crop rectangle, `QUndoStack` for undo/redo, and `QThreadPool` for background work. PySide6 is the official Qt binding and is LGPL, so it can be shipped freely. "Essentials" leaves out WebEngine and 3D, which keeps the `.exe` small. |
| GIF decoding and image processing | **Pillow 12.3** | Decompresses GIF frames, reduces colours (quantisation) and resizes. Permissively licensed. FFmpeg (+50–100 MB) and gifski / libimagequant (GPL/AGPL) were rejected on size and licence. |
| GIF writing | **Own encoder** (`core/encoder.py`, using Pillow for compression) | Pillow's own GIF saving crops pixels and mishandles transparency in some cases, so the app writes the GIF structure itself and verifies the result. |
| Pixel arrays | **numpy 2.5** | Fast pixel work (frame differencing, alpha handling) and quick hand-off of images to Qt. |
| Packaging | **Nuitka 4.3**, `--onefile` | Compiles Python to C and produces a true single `.exe`. Compared with PyInstaller's single-file mode it starts faster and triggers fewer antivirus false alarms, and its official PySide6 plugin drops unused parts of Qt. |
| Tests | **pytest 9.1** + **pytest-qt 4.5** | pytest-qt drives real widgets (clicks, keys, signals) without a visible window. |
| Lint and format | **ruff 0.17** | One fast tool for both. |
| CI | **GitHub Actions** (`windows-latest`) | Nuitka cannot cross-compile, so the Windows build runs on a Windows machine; every run tests, builds and smoke-tests the `.exe`. |
| Container | **Docker**, Debian 13 + Python 3.13 slim, pinned by digest | Runs the editor on Linux and macOS, runs scripted edits without installing Python, and runs the tests in a clean environment. The GUI uses Qt's built-in **VNC** server, which PySide6 already ships, so any VNC viewer can show it and no X server is needed. |

All versions are pinned exactly in `pyproject.toml` and `requirements*.txt` so builds can be reproduced.

**Design in one paragraph:** the code has two layers. `core/` is a GIF engine with **no Qt imports**: decode, plan the
output timing, crop, resize, reduce colours, encode. It is fully unit-testable and also drives a hidden command-line mode.
`ui/` is the PySide6 application: widgets talk only to a central `Document` (source GIF, edit settings, undo history),
and any slow work goes to a thread pool. More detail: [docs/03-architecture.md](docs/03-architecture.md).

## Project layout

```
src/gif_editor/
  core/        GIF engine (no Qt): decoder, timeline, render, encoder, pipeline, selftest
  ui/          PySide6 application: main window, Document, panels, inspector widgets
  resources/   app icons
  app.py       entry point: python -m gif_editor
  headless.py  hidden --edit-spec command-line mode
tests/         pytest suite (core + ui), with generated test GIFs
scripts/       build, smoke test, icon generator, test helpers
packaging/     build requirements, licence bundle
docs/          brief, plan, architecture, dev log, GIF primer, testing guide, one page per source file
Dockerfile     Linux image: GUI over VNC or X11, headless edits, and a test target
```

## Run from source

Windows PowerShell, from the repo root (Python 3.13 64-bit needed):
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PYTHONPATH="src"; .venv\Scripts\python -m gif_editor [file.gif]
```

## Run the tests

```powershell
.venv\Scripts\ruff check . ; .venv\Scripts\ruff format --check .
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python -m pytest -q
```
On Linux (or the dev container) use `scripts/test.sh`. It runs the format check, lint and all tests, and passes any
extra arguments to pytest (`scripts/test.sh tests/ui -k trim`). Other checks are listed in
[docs/06-testing.md](docs/06-testing.md).

## Build the .exe

Nuitka compiles to C and cannot cross-compile, so `GifEditor.exe` must be built **on Windows**.

**With GitHub Actions (easiest):** Actions → **Build GifEditor.exe** → **Run workflow** (pushing a tag such as `v0.1.0`
also starts it). The job lints, tests, builds and smoke-tests the `.exe`, then uploads the artifact `GifEditor-windows`.

**On your PC** (PowerShell, from the repo root). The first build takes a long time and may download a C compiler:
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt -r packaging\build-requirements.txt
.venv\Scripts\python scripts\build.py
.venv\Scripts\python scripts\smoke_build.py out\dist\GifEditor.exe
```
The result is `out\dist\GifEditor.exe`, and the smoke test must end with `OK: …`. Nuitka needs several GB of free space
for its cache and temp files. If C: is nearly full, point `NUITKA_CACHE_DIR`, `TEMP` and `TMP` to another drive. If you
change `scripts\build.py`, run `scripts\check_build_flags.py` first: it checks every flag in about a second instead of
failing a long build.

At startup the `.exe` unpacks itself into the temp folder (about 150 MB). It never writes next to itself.

**Hidden headless mode** (used by the smoke test; no window, no Qt):
```powershell
GifEditor.exe --edit-spec in.gif "trim=0:400,delete=0:3,crop=8:6:40:30,size=32x24,colors=64,out=out.gif"
```
Whole numbers are milliseconds and decimals are seconds. The command prints one `RESULT …` or `ERROR …` line and exits with code 0 or 1.
Full grammar: [headless page](docs/codebase/src/gif_editor/headless.md).

## Docker

The image runs the editor on **Linux** (any host OS with Docker). It does not produce the Windows `.exe`
(see [Build the .exe](#build-the-exe)). It can be used in three ways:

| Use | What you need on the host |
|---|---|
| **GUI over VNC** (default) | a VNC viewer, e.g. TigerVNC (Windows, macOS, Linux) |
| **GUI on an X11 display** | a Linux desktop with X11 (or XWayland) |
| **Headless edits** (`--edit-spec`) | nothing; scripting and batch jobs |

**Build** (from the repo root; the image is roughly 0.5 GB, mostly Qt):
```bash
docker build -t gif-editor .
```

**GUI over VNC.** Mount the folder with your GIFs at `/work`; the file dialogs open there, and results saved there
appear on the host.
```bash
docker run --rm -p 127.0.0.1:5900:5900 -v "${PWD}:/work" gif-editor            # or add a file: ... gif-editor in.gif
```
Then connect your VNC viewer to `localhost:5900`. Closing the editor stops the container.
- The VNC server has **no password**, which is why the port is published on `127.0.0.1` only. Don't publish it on all
  interfaces.
- Screen size: add `-e QT_QPA_PLATFORM=vnc:size=1920x1080` (default 1600×1000).
- There is no window manager: dialogs open as separate windows without title bars, on top of the main window.
- The Docker command works unchanged in PowerShell (`${PWD}` is the current folder).

**GUI on an X11 display (Linux):**
```bash
xhost +local:            # allow local containers to use your display (undo with: xhost -local:)
docker run --rm --user "$(id -u):$(id -g)" -e QT_QPA_PLATFORM=xcb -e DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix -v "$PWD:/work" gif-editor
```

**Headless edits** (no window and no Qt; grammar as in [Build the .exe](#build-the-exe)):
```bash
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" gif-editor \
  --edit-spec in.gif "trim=0:2000,size=320x240,colors=64,out=small.gif"
```
It prints `RESULT …` (exit 0) or `ERROR …` (exit 1). `--user` makes the output file yours on Linux; omit it on
Windows and macOS.

**Tests in a container:**
```bash
docker build --target test -t gif-editor-test .
docker run --rm gif-editor-test                      # the whole suite
docker run --rm gif-editor-test tests/core -k timeline   # extra arguments go to pytest
```

The GitHub workflow **Docker image** builds both targets and checks all of this on every push: the test suite, a
headless edit (read back and checked), the GUI on an X11 display, and the GUI over VNC (`scripts/vnc_probe.py` connects
like a viewer and requires a non-blank screen). In the container the app uses the Linux look (Fusion, DejaVu font,
light colours); it does not follow the Windows light/dark setting.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+O / Ctrl+G / Ctrl+W / Ctrl+Q | Open / Generate / Close GIF / Quit |
| Ctrl+Shift+S | Save current frame as PNG |
| Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) | Undo / redo |
| Space | Play / pause (hold and drag on the canvas to pan) |
| Left / Right, Shift+Left / Right, Home / End | Previous / next frame, ±10 frames, first / last frame |
| I / O | Trim start / end at the playhead |
| Del / Ctrl+Shift+Del | Delete / restore selected frames |
| P | Preview edits (output timing, crop and size) |
| C | Crop tool on/off |
| Ctrl+Arrows / Ctrl+Shift+Arrows | Move / resize the crop by 1 px (crop tool on) |
| Shift while dragging a crop handle | Keep the aspect ratio |
| Alt while dragging a trim handle | Don't snap to frame boundaries |
| Ctrl+0 / Ctrl+1, Ctrl++ / Ctrl+- | Zoom to fit / actual size, zoom in / out |
| Ctrl+wheel, middle-drag | Zoom at the mouse, pan |

While a number field has focus, letters and arrow keys go to the field. Click the canvas or the filmstrip to use the
shortcuts again.

## Documentation

Start at **[docs/README.md](docs/README.md)**. It covers the product brief, research, plan, architecture, development
log, a GIF format primer, the testing guide, and one page per source file under [docs/codebase/](docs/codebase/INDEX.md).
