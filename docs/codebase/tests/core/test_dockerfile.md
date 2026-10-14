# `tests/core/test_dockerfile.py`

> Static checks on `Dockerfile` and `.dockerignore` that need no Docker: the cheap mistakes, caught before the image workflow runs.

## What it covers (6 tests)
| Test | Checks |
|---|---|
| `test_runtime_is_the_last_stage_so_a_plain_build_gives_the_app` | the last `FROM … AS` is `runtime` (a plain `docker build` builds the last stage); a `test` stage exists. This is the mistake the first draft made. |
| `test_base_image_is_pinned_by_digest_and_matches_python_313` | `python:3.13.x-slim-trixie@sha256:<64 hex>` |
| `test_every_copy_source_exists_and_is_in_the_build_context` | each `COPY` source exists in the repo and is not excluded by `.dockerignore` |
| `test_dockerignore_keeps_local_state_out` | `.git`, `.venv`, `.devlibs`, `out`, `__pycache__` excluded; source, tests and requirements kept |
| `test_vnc_default_and_no_root` | VNC is the default platform, port 5900 exposed, the last `USER` is `app` |
| `test_readme_publishes_vnc_on_localhost_only` | every `-p …:5900` in the README binds `127.0.0.1` (the VNC server has no password) |

## Helpers
- `instructions(name)`: the arguments of every Dockerfile instruction `name` (one per line; the file has no line continuations in `FROM`/`COPY`/`USER`).
- `ignored(path)`: a small `.dockerignore` matcher, enough for this file's patterns (`dir/`, `**/name`, `*.ext` globs); not a full implementation of Docker's rules.

## Gotchas
- The whole module **skips** when there is no `Dockerfile` next to `tests/`: the test image copies only `src/`, `scripts/`, `tests/` and the requirement files.

## History
- Created 2026-10-14 with the Docker image ([dev log](../../../04-development-log.md#docker-image)).
