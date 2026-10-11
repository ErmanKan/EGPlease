# `scripts/test.sh`

> Runs lint and the full test suite headlessly in the Linux dev container. This is the one command to run before committing.

## Where it sits
- **Layer:** tooling (bash)
- **Used by:** every contributor in the container (AGENTS.md "Commands"); [`scripts/test-hidpi.sh`](test-hidpi.md) calls it once per scale factor.
- **Uses:** `scripts/fetch-devlibs.sh` (if `libEGL.so.1` is missing), `scripts/offscreen-screen.json` (virtual screen), `.venv/bin/ruff`, `.venv/bin/python -m pytest`.

## Public API
| Usage | Effect |
|---|---|
| `scripts/test.sh` | `ruff format --check .`, `ruff check .`, then `pytest -q` over everything. |
| `scripts/test.sh tests/ui -k crop` | Extra arguments are passed straight to pytest. |
| `QT_SCALE_FACTOR=2 scripts/test.sh tests/ui` | Same, at 200 % scaling (what `test-hidpi.sh` does). |

## How it works
1. `set -euo pipefail`; `cd` to the repo root, so it works from any directory.
2. `LIBDIR=.devlibs/root/usr/lib/x86_64-linux-gnu`. If `libEGL.so.1` is not there, run `scripts/fetch-devlibs.sh` (a one-time download).
3. Prepend `LIBDIR` to `LD_LIBRARY_PATH`, so the dynamic loader finds the project-local `libEGL` when PySide6's QtGui loads.
4. **`QT_QPA_PLATFORM=offscreen:configfile=$PWD/scripts/offscreen-screen.json`** (M4). The offscreen platform needs no display. The config file gives it one virtual **3840×2160** screen. *Why:* Qt's default offscreen screen is only 800×600 physical pixels. At `QT_SCALE_FACTOR=2` that is 400×400 **logical** pixels, smaller than the test windows, and Qt does not deliver mouse events outside the screen, so a timebar test that clicked past x=400 failed at 200 %. That was a test-environment problem, not an app bug. See [config-files](../config-files.md#scriptsoffscreen-screenjson).
5. Run the format check first, then lint. Either failing stops the script, because of `-e`.
6. **Per-run temp directory** (M4). `TMPROOT=out/pytest-tmp` (inside the gitignored `out/`). For every existing `run-<pid>` folder whose process is no longer alive (`kill -0` fails), the folder is deleted. Then:
7. `exec` pytest with `-q --capture=sys --basetemp=out/pytest-tmp/run-$$` plus your arguments. `$$` is this script's PID, which `exec` hands to pytest, so the folder name matches the running pytest process. The `-ra` option comes from `pyproject.toml`.

### Why these pytest options
- **`--basetemp` inside the project.** Project rule: files are created only inside the repo. pytest's `tmp_path` normally lives under the system temp dir (`/tmp` in the container); `--basetemp` moves it into `out/`.
- **One folder per run, not one shared folder.** pytest **empties `--basetemp` when it starts**. With a single shared folder, a second test run (another terminal, a parallel worker, a soak loop) wiped the corpus files of the first while it was using them: one parallel run showed **40 failures** this way. With `run-<pid>` folders, runs never share a folder, and folders of finished runs are cleaned up by the next run.
- **`--capture=sys` instead of the default `fd` capture.** `fd` capture redirects file descriptors 1 and 2 into temp files that pytest creates and **deletes while they are still open**. The project folder is a Windows `F:` drive mounted into the container, and that mount rejects deleted-while-open files. So the obvious alternative, pointing `TMPDIR` at the project, breaks pytest itself. `sys` capture keeps the output in memory (it replaces `sys.stdout`/`sys.stderr`), which works anywhere. The trade-off: output written directly to the file descriptors by C code (e.g. Qt warnings) is not captured and appears in the terminal.
- **Cost:** with the temp files on the mounted drive the full suite takes about **38–40 s** instead of about 15 s on the container's `/tmp`.

## Invariants & gotchas
- Plain `.venv/bin/python -m pytest` in the container fails to import PySide6 (missing `libEGL.so.1`), and would also write temp files to `/tmp`. Always use this script there.
- The format check runs **before** the tests. Fix formatting with `.venv/bin/ruff format .`.
- Linux x86-64 only (hard-coded lib path). On Windows/CI use `QT_QPA_PLATFORM=offscreen python -m pytest -q` (see [06-testing.md](../../06-testing.md)).
- The first run downloads a `.deb` from `deb.debian.org` and needs network access.
- Several runs at the same time are safe (each has its own temp folder). Do not delete `out/pytest-tmp/run-*` folders of running processes by hand.

## Tests
- n/a (it *is* the test runner). Current result (end of M4): **679 passed, 2 xfailed** in about 39 s.

## History
- `cc9f0fa`: added with the headless Qt setup ([dev log](../../04-development-log.md#headless-qt-cc9f0fa)).
- `d3f0297` (M4): virtual 4K offscreen screen via `offscreen-screen.json`.
- `c4b9329` (M4): `--basetemp` inside `out/` and `--capture=sys`.
- `9361dd6` (M4): one `run-<pid>` temp folder per run; folders of exited runs removed ([dev log, Milestone 4](../../04-development-log.md#milestone-4-hardening)).
