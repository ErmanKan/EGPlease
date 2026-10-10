# GIF Editor

Offline Windows desktop GIF editor (Python 3.13 + PySide6). Load a GIF, scrub it frame by frame, trim, delete frames, crop with a draggable rectangle, change speed / FPS / size / quality, then **Generate** a new GIF. Ships as a single portable `GifEditor.exe` (Nuitka onefile).

Status: **Milestone 1 — core engine** (see `docs/02-plan.md`).

## Develop

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PYTHONPATH="src"; .venv\Scripts\python -m gif_editor
```

## Check

```powershell
.venv\Scripts\ruff check . ; .venv\Scripts\ruff format --check .
.venv\Scripts\python -m pytest
```

Docs: `docs/00-brief.md`, `docs/01-research.md`, `docs/02-plan.md`.
