# Configuration and repo-level files

> One page for the non-Python files: the repo root, `.github/`, `packaging/`, the data file in `scripts/` and the icon files in `src/gif_editor/resources/icons/`: what each one configures and why.

## Where it sits
- **Layer:** tooling
- **Used by:** pip, pytest, ruff, GitHub Actions, git, Nuitka (via `scripts/build.py`), the running app (icons), and every contributor.
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
| [`packaging/build-requirements.txt`](#packagingbuild-requirementstxt) | Pinned build-only dependencies: Nuitka and its helpers (M5). |
| [`.github/workflows/build-exe.yml`](#githubworkflowsbuild-exeyml) | Windows CI job that tests, builds, smoke-tests and uploads `GifEditor.exe` (M5). |
| [`.github/workflows/docker.yml`](#githubworkflowsdockeryml) | Linux CI job that builds the Docker image and checks every mode: tests, headless edit, GUI on X11, GUI over VNC. |
| [`.dockerignore`](#dockerignore) | Keeps local state (git, venv, caches, `out/`, docs) out of the Docker build context. |
| [`src/gif_editor/resources/icons/`](#srcgif_editorresourcesicons) | The generated app icon: PNGs and a multi-size `.ico` (M5). |
| `packaging/licenses/.gitkeep` | Empty placeholder for the third-party licence texts the `.exe` must ship with (M5, still open). |

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
- There is no `[build-system]`: the package is never installed. Tests use `pythonpath`, the app runs with `PYTHONPATH=src`, and the release build runs Nuitka directly on `src/` ([`scripts/build.py`](scripts/build.md)), with its own pins in [`packaging/build-requirements.txt`](#packagingbuild-requirementstxt).

### `requirements.txt`
The three runtime pins, commented as a mirror of `pyproject`. Nothing enforces that the two lists match: update both.

### `requirements-dev.txt`
`-r requirements.txt` plus pytest, pytest-qt, ruff with the same pins as the dev group. The README and CI install from this file.

### `.github/workflows/ci.yml`
- Trigger: every `push` and `pull_request`.
- One job on `windows-latest`, which is the target OS. `QT_QPA_PLATFORM=offscreen` is set for the whole job.
- Steps: checkout → Python 3.13 → `pip install -r requirements-dev.txt` → `ruff check .` → `ruff format --check .` → `python -m pytest -q`.
- No libEGL step is needed: Windows Qt wheels bring their own platform plugins.
- No pip cache. The `.exe` is built by a separate, manually triggered workflow, [`build-exe.yml`](#githubworkflowsbuild-exeyml), not on every push: a build takes far longer than the tests.

### `scripts/offscreen-screen.json`
```json
{"screens": [{"name": "virtual", "x": 0, "y": 0, "width": 3840, "height": 2160, "logicalDpi": 96, "dpr": 1}]}
```
A configuration file for Qt's `offscreen` platform plugin, passed as `QT_QPA_PLATFORM=offscreen:configfile=$PWD/scripts/offscreen-screen.json` by [`scripts/test.sh`](scripts/test.md). It declares one virtual screen of **3840×2160** physical pixels at 96 DPI with a device pixel ratio of 1.

*Why (M4, `d3f0297`):* the default offscreen screen is 800×600 physical pixels. Under `QT_SCALE_FACTOR=2` (the 200 % HiDPI pass, [`scripts/test-hidpi.sh`](scripts/test-hidpi.md)) that is only **400×400 logical** pixels, smaller than the test windows. Qt does not deliver mouse events at positions outside the screen, so a timebar test that clicked beyond x=400 failed at 200 %. That was a limitation of the test environment, not an app bug. A 4K virtual screen is 1920×1080 logical at 200 %, larger than any test window. `dpr` stays 1 here; the scale factor comes from `QT_SCALE_FACTOR`.

Side effect: `MainWindow._fit_to_screen` sees this large screen in tests, so the window opens at its preferred 1300×820. The small-screen behaviour is tested by patching `availableGeometry` instead.

CI (Windows) does not use this file: it runs plain `pytest` with `QT_QPA_PLATFORM=offscreen` at scale 1, where the default screen is large enough.

### `packaging/build-requirements.txt`
```text
nuitka==4.3
ordered-set==4.1.0
zstandard==0.25.0
patchelf==0.19.1.0; sys_platform != "win32"  # Nuitka onefile needs it on Linux/macOS only
```
Build-only dependencies, installed **on top of** `requirements-dev.txt` by the build workflow and by anyone building locally (`python -m pip install -r packaging/build-requirements.txt`). Kept out of `requirements-dev.txt` because running and testing the app does not need a compiler toolchain.
- `nuitka==4.3`: the compiler. Exact pin, because the flags in `scripts/build.py` and the option-table check in `scripts/check_build_flags.py` are tied to this version's options.
- `ordered-set`: an optional Nuitka dependency that speeds up compilation.
- `zstandard`: needed for onefile **compression**; without it the onefile payload is stored uncompressed and the `.exe` is much larger.
- `patchelf` (non-Windows only, via the environment marker): Nuitka's onefile mode on Linux needs the `patchelf` tool to fix up library paths in the bundled `.so` files. It is installed as a pip wheel **into the venv** (the project's no-global-install rule), so for a local Linux build put `.venv/bin` on `PATH`. Windows does not need it, so the marker skips it there.

### `.github/workflows/build-exe.yml`
The only way to get a real `GifEditor.exe` without a Windows PC set up for development: Nuitka cannot cross-compile, so the `.exe` is built on a Windows runner.
- **Triggers:** `workflow_dispatch` (by hand: GitHub → Actions → *Build GifEditor.exe* → *Run workflow*) and any pushed tag matching `v*` (e.g. `v0.1.0`). Not on every push: a build takes tens of minutes.
- **Job:** one job on `windows-latest`, Python 3.13 with pip caching (`actions/setup-python@v5`, `cache: pip`).
- **Steps, in order** (each must pass before the next):
  1. checkout; set up Python;
  2. **install:** upgrade pip, `pip install -r requirements-dev.txt`, `pip install -r packaging/build-requirements.txt`;
  3. **lint and test:** `ruff format --check .`, `ruff check .`, `python -m pytest -q` with `QT_QPA_PLATFORM=offscreen` (no point building a broken app);
  4. **icons current:** `python scripts/make_icon.py --check` (compares pixels, [why](scripts/make_icon.md#checking---check));
  5. **flags valid:** `python scripts/check_build_flags.py` (seconds, before a long build);
  6. **build:** `python scripts/build.py` → `out/dist/GifEditor.exe`;
  7. **smoke test:** `python scripts/smoke_build.py out/dist/GifEditor.exe` (fails cleanly, edits and writes a GIF, opens it in the real window offscreen);
  8. **upload:** `actions/upload-artifact@v4`, artifact name **`GifEditor-windows`**, path `out/dist/GifEditor.exe`, `if-no-files-found: error`, **kept 30 days**.
- **Getting the file:** open the finished run on GitHub's Actions tab, scroll to *Artifacts*, download `GifEditor-windows` (a zip containing `GifEditor.exe`). Artifacts are only visible to people with access to the repository and expire after 30 days.
- **Status:** green since run 38478763559 (commit `94c54fc`, 2026-10-13): all steps including the 3 smoke steps; artifact 33.6 MB. The first two runs failed, see the dev log (*First CI run on GitHub*, *First Windows build*).
- History: `4779648` added it; `7bac56c` replaced "regenerate the icon + `git diff --exit-code`" with `make_icon.py --check` (byte comparison of PNGs can fail across operating systems) and added the flag check.

### `.github/workflows/docker.yml`
Builds and exercises the Linux image ([Dockerfile page](Dockerfile.md)) on `ubuntu-latest`, on every push and PR (and by hand).
- **Build:** `docker build --target runtime -t gif-editor .` and `--target test -t gif-editor-test`.
- **Test suite in the container:** `docker run --rm gif-editor-test`.
- **Headless edit:** a test GIF made by the project's own `tests/gifgen.py` (inside the test image) in a mounted `work/` folder; `--edit-spec in.gif "trim=0:400,size=20x15,colors=16,out=out.gif"` must print `RESULT`; the output is read back with Pillow (20×15, 4 frames); a missing input must exit 1 with an `ERROR` line and no traceback. Containers run with `--user $(id -u):$(id -g)` so they can write to the runner's folder.
- **GUI on X11:** `Xvfb :99` on the runner, the container with `QT_QPA_PLATFORM=xcb`, `DISPLAY=:99` and the X socket mounted, `--smoke-gui in.gif` must print `GUI OK` (proves the X11 plugin and its libraries load).
- **GUI over VNC (the default):** the container started detached with `-p 127.0.0.1:5900:5900`; [`scripts/vnc_probe.py`](scripts/vnc_probe.md) must read a non-blank screen within 60 s.
- Every command was first run locally without Docker (same arguments, same expected output); the workflow is the first place the image itself is built, because the dev container has no Docker.

### `.dockerignore`
Excludes `.git/`, `.github/`, `.venv/`, `.devlibs/`, `out/`, `docs/`, Python caches, build and Nuitka output and editor folders from the build context. It keeps the context small (no venv or test temp files sent to the daemon) and keeps local state out of images. `tests/core/test_dockerfile.py` checks that nothing a `COPY` needs is excluded.

### `src/gif_editor/resources/icons/`
The app icon, **generated** by [`scripts/make_icon.py`](scripts/make_icon.md) (never edited by hand; the script is the source):

| File | Size | Used for |
|---|---|---|
| `icon.ico` | 16, 24, 32, 48, 64, 128, 256 px in one file | Windows: embedded into the `.exe` by `--windows-icon-from-ico` (Explorer), and the running window's icon on Windows (`icon_path()`). |
| `icon-256.png` | 256 px | Non-Windows window icon (`icon_path()`), and `--linux-icon` for a Linux build. |
| `icon.png` | 256 px | Same pixels as `icon-256.png`; a conventional name for other tools. Not used by the code. |
| `icon-16.png` … `icon-64.png` | 16, 24, 32, 48, 64 px | Previews of the small drawings; checked by `--check`. |
| `.gitkeep` | 0 bytes | Leftover placeholder from the scaffold (harmless). |

Sizes ≤ 32 px are a simplified drawing (bold play triangle only), larger ones add the green film sprockets; see the [make_icon page](scripts/make_icon.md#the-drawing). The folder is package data: `scripts/build.py` ships it with `--include-package-data=gif_editor`, and [`gif_editor.resources`](src/gif_editor/resources/__init__.md) finds it at runtime. These are the only binary files in the repo; they are allowed because they are generated and checked against their generator in CI (the "no binary fixtures" rule is about test data).

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
- **Interface blocks** for core and UI (the `Document` hub, helpers, `messages`, and each M2/M3 widget's and service's constructor, signals and public methods, plus the M4 and M5 additions: `build_command`, `check_build_flags`, `make_icon --check`, `resource_path`/`icon_path`, `parse_spec`/`run_edit_spec`, `--smoke-gui`), with widget rules, the worker rules, the merge-key rule and the packaging rules (run `check_build_flags.py` after touching `build.py`; no Qt import before the `--edit-spec` branch).
- **Documentation and test rules**, conventional commits, the definition of done.

Known drift from the code is listed in [`docs/03-architecture.md`](../03-architecture.md#known-drift-between-docs-and-code).

### `README.md`
The front page, written for users (rewritten 2026-10-14): intro and status, where to get the `.exe`, how to use the editor in five steps, features, **the tech stack and why each part was chosen**, the project layout, run from source, run the tests, **build the `.exe`** (Actions or a Windows PC) with the hidden `--edit-spec` mode, **Docker** (GUI over VNC or X11, headless edits, the test target), the keyboard shortcuts, and a link to [docs/README.md](../README.md). Keep its shortcut table in sync with `ui/main_window.py` and its build commands in sync with `scripts/build.py` / `build-exe.yml`.

## Invariants & gotchas
- Pins appear in three places (`pyproject.toml`, `requirements*.txt`, the AGENTS.md "Stack" line). Change all three together. The build pins live only in `packaging/build-requirements.txt` (and Nuitka's version in the AGENTS.md Stack line).
- `ci.yml` and `build-exe.yml` both run lint and tests; keep their commands in step. `docker.yml` runs the tests too (inside the image), and its headless/GUI commands must match the README's Docker section.
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
- `3531ca0` (M5): `src/gif_editor/resources/icons/` (generated icon files).
- `4779648` (M5): `packaging/build-requirements.txt` and `.github/workflows/build-exe.yml`; `7bac56c` changed the workflow's icon step to `make_icon.py --check` and added the flag check.
- M5 documentation pass: this page gained the three M5 sections; README and AGENTS.md describe the M5 state.
