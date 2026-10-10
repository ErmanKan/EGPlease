# GIF Editor

Offline Windows desktop GIF editor (Python 3.13 + PySide6). Load a GIF, scrub it frame by frame, trim, delete frames, crop with a draggable rectangle, change speed / FPS / size / quality, then **Generate** a new GIF. Ships as a single portable `GifEditor.exe` (Nuitka onefile).

Status: **Milestones 1–2 done** (core engine; window and inspector). Next: **M3, crop + live preview** (see [docs/02-plan.md](docs/02-plan.md#6-milestones)).

## Features (working today)
- **Open** a GIF from File → Open, the command line, or by dragging it onto the window. Decoding runs in the background, with browser-correct disposal and transparency; damaged files load as far as possible, with a warning.
- **Frame inspector:**
  - a zoomable canvas (Fit, 100 %, Ctrl+wheel, middle-drag pan) on a checkerboard;
  - a timebar with playhead and green/red trim handles that snap to frame boundaries (Alt = free);
  - a thumbnail filmstrip with multi-select;
  - play/pause and frame stepping, optionally previewing the edited timing.
- **Edit** (all undoable, Ctrl+Z / Ctrl+Y):
  - trim by handles, by Start/Duration fields, or at the playhead (I / O);
  - delete and restore frames (deleting removes their time);
  - speed 0.25×–4×; FPS limit ≤ 50;
  - output size with aspect lock or scale %;
  - quality presets, or 2–256 colours with dithering on/off.
- **Live summary:** output frame count, duration, size and warnings, updated on every edit (the file-size estimate comes in M3).
- **Generate** in the background with progress and Cancel. Output uses a shared palette and lossless frame differencing, keeps the source's transparency and loop setting, is verified after writing, and replaces the destination atomically (a cancelled or failed run leaves it untouched).
- **Save the current frame as PNG**, as in the source or with crop/size applied.
- Not yet: the interactive crop rectangle and crop/resize preview (M3), the size estimate (M3), the `.exe` build (M5).

## Run

Windows (PowerShell, from the repo root):
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PYTHONPATH="src"; .venv\Scripts\python -m gif_editor [file.gif]
```

## Check

Windows:
```powershell
.venv\Scripts\ruff check . ; .venv\Scripts\ruff format --check .
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python -m pytest -q
```

Linux dev container (headless; fetches a project-local `libEGL` on first run):
```bash
scripts/test.sh                 # ruff format check + ruff lint + all tests
scripts/test.sh tests/ui -k trim  # extra arguments go to pytest
```

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+O | Open GIF |
| Ctrl+G | Generate |
| Ctrl+Shift+S | Save current frame as PNG |
| Ctrl+F4 | Close the GIF |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Del | Delete selected frame(s) (or the current frame) |
| Ctrl+Shift+Del | Restore selected frame(s) (Insert also works in the filmstrip) |
| I / O | Set trim start / end at the playhead |
| Space | Play / pause |
| P | Preview edits (play the edited timing) |
| Left / Right | Previous / next frame |
| Shift+Left / Shift+Right | Back / forward 10 frames |
| Home / End | First / last frame |
| Ctrl+0 / Ctrl+1 | Zoom to fit / actual size |
| Ctrl++ / Ctrl+- | Zoom in / out |
| Ctrl+wheel, middle-drag | Zoom at the mouse, pan (canvas) |
| Alt while dragging a trim handle | Don't snap to frame boundaries |

Single-letter and arrow keys go to a spin box while one has focus, so you can type in it. Click the canvas or the filmstrip to use them as shortcuts again.

## Documentation

Start at **[docs/README.md](docs/README.md)**: product brief, plan, architecture, development log, GIF primer, testing guide, and one page per source file under [docs/codebase/](docs/codebase/INDEX.md).
