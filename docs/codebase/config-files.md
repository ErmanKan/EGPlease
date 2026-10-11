# Configuration and repo-level files

> One page for the non-Python files at the repo root, in `.github/` and the one data file in `scripts/`: what each one configures and why.

## Where it sits
- **Layer:** tooling
- **Used by:** pip, pytest, ruff, GitHub Actions, git, and every contributor.
- **Uses:** n/a

## Public API
| File | Purpose |
|---|---|
| [`pyproject.toml`](#pyprojecttoml) | Project metadata, pinned runtime deps, the dev dependency group, pytest and ruff config. |
| [`requirements.txt`](#requirementstxt) | Runtime pins for `pip install -r` (mirror of `pyproject` dependencies). |
| [`requirements-dev.txt`](#requirements-devtxt) | Runtime + test/lint pins. |
| [`.github/workflows/ci.yml`](#githubworkflowsciyml) | Windows CI: lint + tests on every push/PR. |
| [`.gitignore`](#gitignore) | Keeps venvs, caches, build output, `.devlibs/` and scratch files out of git. |
| [`AGENTS.md`](#agentsmd) | The contributor contract: rules, commands, architecture rules, interfaces, definition of done. |
| [`README.md`](#readmemd) | Project intro, status, features, run/check commands, keyboard shortcuts, link to the docs. |
| [`scripts/offscreen-screen.json`](#scriptsoffscreen-screenjson) | The virtual 3840×2160 screen for Qt's offscreen platform in `scripts/test.sh` (M4). |

## How it works

### `pyproject.toml`
- `[project]`: name `gif-editor`, version `0.1.0` (keep in sync with `gif_editor.__version__`), `requires-python = ">=3.13,<3.14"`. Dependencies pinned **exactly**: `PySide6-Essentials==6.12.0`, `pillow==12.3.0`, `numpy==2.5.3`.
  - *Why exact pins:* the decoder and encoder rely on undocumented Pillow internals (see `core/selftest.py`). PySide6-Essentials (not full PySide6) avoids WebEngine/3D and keeps the onefile exe small.
- `[dependency-groups].dev`: `pytest==9.1.1`, `pytest-qt==4.5.0`, `ruff==0.17.0` (PEP 735 groups; pip users use `requirements-dev.txt`).
- `[tool.pytest.ini_options]`:
  - `pythonpath = ["src", "tests"]`: makes `gif_editor` importable without installing it, and makes the helpers importable as `corpus` and `gifgen`;
  - `testpaths = ["tests"]`;
  - `addopts = "-ra"`: prints a summary of skips and xfails with their reasons.
- `[tool.ruff]`: line length 100, target py313, `src = ["src", "tests"]` (for import sorting). Lint rules `E, F, W, I, UP, B, SIM, RUF`. The formatter uses double quotes.
- There is no `[build-system]`: the package is not installed; the release build will use Nuitka directly (M5).

### `requirements.txt`
The three runtime pins, commented as a mirror of `pyproject`. Nothing enforces that the two lists match: update both.

### `requirements-dev.txt`
`-r requirements.txt` plus pytest, pytest-qt, ruff with the same pins as the dev group. The README and CI install from this file.

### `.github/workflows/ci.yml`
- Trigger: every `push` and `pull_request`.
- One job on `windows-latest`, which is the target OS. `QT_QPA_PLATFORM=offscreen` is set for the whole job.
- Steps: checkout → Python 3.13 → `pip install -r requirements-dev.txt` → `ruff check .` → `ruff format --check .` → `python -m pytest -q`.
- No libEGL step is needed: Windows Qt wheels bring their own platform plugins.
- Not yet: the Nuitka build artifact from the plan (M5); a pip cache.

### `scripts/offscreen-screen.json`
```json
{"screens": [{"name": "virtual", "x": 0, "y": 0, "width": 3840, "height": 2160, "logicalDpi": 96, "dpr": 1}]}
```
A configuration file for Qt's `offscreen` platform plugin, passed as `QT_QPA_PLATFORM=offscreen:configfile=$PWD/scripts/offscreen-screen.json` by [`scripts/test.sh`](scripts/test.md). It declares one virtual screen of **3840×2160** physical pixels at 96 DPI with a device pixel ratio of 1.

*Why (M4, `d3f0297`):* the default offscreen screen is 800×600 physical pixels. Under `QT_SCALE_FACTOR=2` (the 200 % HiDPI pass, [`scripts/test-hidpi.sh`](scripts/test-hidpi.md)) that is only **400×400 logical** pixels, smaller than the test windows. Qt does not deliver mouse events at positions outside the screen, so a timebar test that clicked beyond x=400 failed at 200 %. That was a limitation of the test environment, not an app bug. A 4K virtual screen is 1920×1080 logical at 200 %, larger than any test window. `dpr` stays 1 here; the scale factor comes from `QT_SCALE_FACTOR`.

Side effect: `MainWindow._fit_to_screen` sees this large screen in tests, so the window opens at its preferred 1300×820. The small-screen behaviour is tested by patching `availableGeometry` instead.

CI (Windows) does not use this file: it runs plain `pytest` with `QT_QPA_PLATFORM=offscreen` at scale 1, where the default screen is large enough.

### `.gitignore`
Python caches and venvs (`__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `*.egg-info/`, `build/`, `dist/`), Nuitka output (`*.build/`, `*.dist/`, `*.onefile-build/`), editor/OS files (`.vscode/`, `.idea/`, `Thumbs.db`, `desktop.ini`), the project-local Linux libs `.devlibs/`, and scratch output (`*.tmp.gif`, `/out/`). Since M4 `/out/` also holds every test and tool temp file: `out/pytest-tmp/run-<pid>/` (pytest's `tmp_path`, per run), `out/fuzz/`, `out/stress/`, and soak worktrees; nothing is written to the container's `/tmp`.

Note: the encoder's temporary files are named `.<name>.<uuid>.tmp` and are not ignored. They only exist while a write is in progress and are always deleted.

### `AGENTS.md`
The contract every contributor (human or agent) follows:
- **Hard rules:** stay in the repo; no global installs; workers request packages instead of installing; only touch owned files; shared interfaces are a contract.
- **Stack and commands:** `scripts/test.sh`, ruff, the Windows test command, how to run the app.
- **Environment note:** the libEGL setup.
- **Architecture rules:** no Qt in core; immutable `EditState` changed only via undo commands; `plan_output` is the only planner; pipeline order; QPixmap only on the GUI thread.
- **Gate 1 product decisions.**
- **Interface blocks** for core and UI (the `Document` hub, helpers, `messages`, and each M2/M3 widget's and service's constructor, signals and public methods, plus the M4 additions), with widget rules, the worker rules and the merge-key rule.
- **Documentation and test rules**, conventional commits, the definition of done.

Known drift from the code is listed in [`docs/03-architecture.md`](../03-architecture.md#known-drift-between-docs-and-code).

### `README.md`
The front page: a short intro, the status (Milestones 1–4 done, M5 next), a list of what works today, how to run the app on Windows (`python -m gif_editor [file.gif]`) and how to check it (Windows and `scripts/test.sh` in the container), the keyboard shortcuts, and a link to [docs/README.md](../README.md). Keep its shortcut table in sync with `ui/main_window.py`.

## Invariants & gotchas
- Pins appear in three places (`pyproject.toml`, `requirements*.txt`, the AGENTS.md "Stack" line). Change all three together.
- CI runs ruff in the opposite order to `scripts/test.sh` (lint first, then format). The result is the same.

## Tests
- CI itself; locally `scripts/test.sh`.

## History
- `7a7b418`: scaffold (pyproject, requirements, CI, .gitignore, AGENTS.md, README).
- `cc9f0fa`: `.devlibs/` added to `.gitignore`.
- `0137178`: AGENTS.md gained the UI interfaces and documentation rules.
- End of M2 (docs pass): AGENTS.md gained the per-widget interfaces, `run_async(pool=)`, the full pipeline API and the corrected libEGL trust statement; README rewritten for the M2 status.
- `d3f0297` (M4): `scripts/offscreen-screen.json`.
- End of M4 (docs pass): AGENTS.md gained the M4 interfaces (messages, `show_explanation`, `spaceTapped`, `frames_to_decode`) and the worker and test-temp rules; README status M1–M4.
