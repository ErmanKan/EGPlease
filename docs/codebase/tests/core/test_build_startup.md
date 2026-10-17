# `tests/core/test_build_startup.py`

> Pins the onefile start-up cache: the build's unpack folder must stay static, and the smoke test's helpers must find the cache and temp leftovers.

## What it covers (3 test functions, 4 cases)
| Test | Checks |
|---|---|
| `test_unpack_folder_is_static_so_nuitka_caches` (Windows and Linux command lines) | exactly one `--onefile-tempdir-spec`; it starts with `{CACHE_DIR}/`, contains `{VERSION}`, and has no per-run part (`{PID}`, `{TIME…}`, `{RANDOM}`) and no `{TEMP}` |
| `test_unpack_cache_dirs_finds_the_version_folder` | `smoke_build.unpack_cache_dirs` returns the `<work>/cache/Erman K/GIF Editor/<version>` folder on Linux, ignores files |
| `test_temp_leftovers_lists_only_onefile_folders` | `smoke_build.temp_leftovers` lists `onefile_*` folders only |

## Why
A per-run part in the spec silently brings back unpacking 150–230 MB on every start, the cause of the slow and failing starts reported on 2026-10-17 ([dev log](../../../04-development-log.md#slow-start-up-unpack-once-instead-of-on-every-start)).

## Gaps
- The Windows branch of `unpack_cache_dirs` (`%LOCALAPPDATA%`) runs only in the Windows smoke test.
