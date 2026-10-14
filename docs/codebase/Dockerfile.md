# `Dockerfile`

> Builds the Linux container image: the editor GUI (over Qt's VNC server by default, or on an X11 display), the headless `--edit-spec` mode, and a separate `test` target that runs the whole suite.

## Where it sits
- **Layer:** tooling
- **Used by:** `docker build`; `.github/workflows/docker.yml` (builds both targets and checks every mode); users following README → *Docker*.
- **Uses:** `requirements.txt`, `src/` (runtime); `requirements-dev.txt`, `packaging/build-requirements.txt`, `pyproject.toml`, `scripts/`, `tests/` (test target). The build context is trimmed by [`.dockerignore`](config-files.md#dockerignore).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| target `runtime` (the default: the last stage) | image | `ENTRYPOINT python -m gif_editor`; arguments are the app's (`[file.gif]`, `--edit-spec IN SPEC`, `--smoke-gui`). Identical to the internal `app` stage. |
| target `test` | image | `ENTRYPOINT python -m pytest -q -p no:cacheprovider`; arguments go to pytest. |
| `/work` | volume path | The working directory: mount your GIFs here. File dialogs open here; relative `--edit-spec` paths resolve here. |
| port `5900` | exposed port | Qt's VNC server (default mode). |
| `QT_QPA_PLATFORM` | env | `vnc:size=1600x1000` (default); `xcb` for an X11 display; `offscreen` for `--smoke-gui`. In the test target: `offscreen` with the 3840×2160 virtual screen. |

## How it works
1. **Base image:** `python:3.13.16-slim-trixie`, pinned by **digest** (the multi-arch index, fetched from Docker Hub's registry API on 2026-10-14). Python 3.13 matches `requires-python`; Debian 13 (trixie) matches the dev container, where every package below was checked to exist (`apt-cache policy`). Tag and digest must be updated together.
2. **System libraries.** The slim image has none of the libraries Qt needs. The list was **measured**, not copied from a guide: `ldd` on `libQt6Core/Gui/Widgets/XcbQpa` and on the `xcb`, `vnc` and `offscreen` platform plugins, each library mapped to its Debian package (`dpkg -S` where installed, by soname otherwise). The eight packages the dev container lacks were downloaded and unpacked into a scratch folder; with them, `ldd` reports nothing missing for any platform, image-format or icon-engine plugin except `libqpdf.so` (needs `libQt6Pdf`, which PySide6-Essentials does not ship; Qt simply skips that plugin). Notable entries:
   - `libegl1`, `libgl1`: Qt Gui links them even for software rendering.
   - `libxcb-*`, `libxkbcommon-x11-0`, `libx11-xcb1`: the X11 platform plugin.
   - `libgssapi-krb5-2`: `libQt6Network`, which the VNC plugin uses.
   - `fonts-dejavu-core`: without any font Qt renders every character as a box.
   - `--no-install-recommends` and the apt lists removed in the same layer keep the image small.
3. **Python packages:** `pip install -r requirements.txt` (the exact runtime pins) before `COPY src/`, so editing code does not invalidate the slow dependency layer. No wheel or install step for the app itself: `PYTHONPATH=/opt/gif-editor/src`, the same way `scripts/build.py` and the dev commands run it.
4. **User:** `app` (uid 1000), with `/work` owned by it. Running as root is unnecessary and would create root-owned output files in mounted folders. On Linux, `--user "$(id -u):$(id -g)"` makes outputs belong to the host user (the image works with any uid: nothing needs a home directory).
5. **Display:** the default `QT_QPA_PLATFORM=vnc:size=1600x1000` makes the app its **own VNC server** (Qt's VNC platform plugin, part of the PySide6 wheel). Why this default: it works on Windows, macOS and Linux hosts with just a VNC viewer, with no X server, no socket mounts and no display permissions. `XDG_RUNTIME_DIR` is set because Qt warns without it; Qt creates the folder.
6. **Stages:** `app` (everything above), then `test` (`FROM app`), then `runtime` (`FROM app`, nothing added). The order matters: a plain `docker build` builds the **last** stage, and `runtime` must be the default. A first draft had `test` last, so the README's `docker build -t gif-editor .` would have produced the test image; it was caught while writing this page.
7. **Test target:** builds on `app`, adds the dev and build pins (`tests/core/test_check_build_flags.py` runs Nuitka's option parser), copies `pyproject.toml` (pytest's `pythonpath`), `scripts/` and `tests/`, and runs pytest as `app` with offscreen Qt on the same virtual 3840×2160 screen as `scripts/test.sh` (Qt's default 800×600 offscreen screen loses mouse events past x=800). `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE` keep pytest from writing into the root-owned source tree.

## Invariants & gotchas
- **The VNC server has no password.** Always publish it as `-p 127.0.0.1:5900:5900`; publishing `5900:5900` exposes an unauthenticated editor with access to `/work` to the network.
- **Keep `runtime` the last stage.** `docker build` without `--target` builds the last stage; anything appended after `runtime` becomes the default image.
- When PySide6 is upgraded, re-run the `ldd` check (see *How it works* 2): a new Qt can need new libraries, and the symptom is a plugin silently failing to load ("could not load the Qt platform plugin").
- No window manager in VNC mode: top-level windows (dialogs) have no title bars and can't be moved.
- The image does not follow the host's light/dark setting (no platform theme inside the container): Fusion's light palette, DejaVu font.
- The Windows `.exe` is not built here: Nuitka cannot cross-compile ([build-exe.yml](config-files.md#githubworkflowsbuild-exeyml)).
- `docker` is not available in the dev container, so the image was first built by the workflow; everything that could run without Docker was checked locally first: the app on the VNC plugin read back with `scripts/vnc_probe.py` (1280×800, 1067 colours), the exact headless-edit and `--smoke-gui` commands of the workflow, and the package list (above).

## Tests
- [`.github/workflows/docker.yml`](config-files.md#githubworkflowsdockeryml): builds both targets, runs the suite in the container, a headless edit read back with Pillow, a clean failure on a missing file, `--smoke-gui` on Xvfb through the X11 plugin, and the default VNC mode checked with [`scripts/vnc_probe.py`](scripts/vnc_probe.md).

## History
- Created 2026-10-14 at the user's request ([dev log](../04-development-log.md#docker-image)).
