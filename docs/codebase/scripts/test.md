# `scripts/test.sh`

> Runs lint and the full test suite headlessly in the Linux dev container. This is the one command to run before committing.

## Where it sits
- **Layer:** tooling (bash)
- **Used by:** every contributor in the container (AGENTS.md "Commands").
- **Uses:** `scripts/fetch-devlibs.sh` (if `libEGL.so.1` is missing), `.venv/bin/ruff`, `.venv/bin/python -m pytest`.

## Public API
| Usage | Effect |
|---|---|
| `scripts/test.sh` | `ruff format --check .`, `ruff check .`, then `pytest -q` over everything. |
| `scripts/test.sh tests/ui -k crop` | Extra arguments are passed straight to pytest. |

## How it works
1. `set -euo pipefail`; `cd` to the repo root, so it works from any directory.
2. `LIBDIR=.devlibs/root/usr/lib/x86_64-linux-gnu`. If `libEGL.so.1` is not there, run `scripts/fetch-devlibs.sh` (a one-time download).
3. Prepend `LIBDIR` to `LD_LIBRARY_PATH`, so the dynamic loader finds the project-local `libEGL` when PySide6's QtGui loads. Set `QT_QPA_PLATFORM=offscreen` (no display needed).
4. Run the format check first, then lint. Either failing stops the script, because of `-e`.
5. `exec` pytest with `-q` plus your arguments. The `-ra` option comes from `pyproject.toml`.

## Invariants & gotchas
- Plain `.venv/bin/python -m pytest` in the container fails to import PySide6 (missing `libEGL.so.1`). Always use this script there.
- The format check runs **before** the tests. Fix formatting with `.venv/bin/ruff format .`.
- Linux x86-64 only (hard-coded lib path). On Windows/CI use `QT_QPA_PLATFORM=offscreen python -m pytest -q` (see [06-testing.md](../../06-testing.md)).
- The first run downloads a `.deb` from `deb.debian.org` and needs network access.

## Tests
- n/a (it *is* the test runner). Current result: 408 passed, 2 xfailed.

## History
- `cc9f0fa`: added with the headless Qt setup ([dev log](../../04-development-log.md#headless-qt-cc9f0fa)).
