# `tests/core/test_check_build_flags.py`

> Tests that the Nuitka flag checker accepts the committed build command and catches each flag mistake that was actually made during M5.

## Where it sits
- **Layer:** tests (tooling, no Qt)
- **Used by:** pytest.
- **Uses:** `scripts/check_build_flags.py` (imported as `check_build_flags` after putting `scripts/` on `sys.path`), and through it `scripts/build.py` and Nuitka's option parser (`nuitka==4.3` must be in the venv).

## Public API
| Test | Verifies |
|---|---|
| `known` | module-scoped fixture: `known_options()` once (importing Nuitka's parser takes a moment). |
| `test_committed_command_lines_are_valid` | `check()` returns no problems for the Linux and the Windows command line `build.py` really produces. |
| `test_injected_bad_flag_is_caught[--cache-dir={TMP}]` | Not a Nuitka option (cost one 20-minute build). |
| `test_injected_bad_flag_is_caught[--no-console]` | Not a Nuitka option (cost another). |
| `test_injected_bad_flag_is_caught[--windows-icon-from-ico=/tmp/x.ico]` | Windows-only flag leaking into the Linux build. |
| `test_injected_bad_flag_is_caught[--invented-flag=1]` | Any made-up flag. |
| `test_missing_plugin_flag_is_caught` | With `--enable-plugin=…` removed, the `--noinclude-*-mode` options are reported. |

**6 test cases** (3 functions, one parametrized 4 ways).

## How it works
`monkeypatch` replaces `build.build_command` (on the `build` module the checker imported) with a wrapper around the real one:
- **Injected flag:** the bad flag is inserted before the last argument. The Windows-icon flag is inserted only into the Linux command, because on Windows it is correct. Both platforms are then checked, and the test requires at least one problem that names the flag.
- **Missing plugin flag:** every argument starting with `--enable-plugin` is removed, and the Linux check must report a problem mentioning `noinclude`.

The `/tmp/x.ico` and `{TMP}` strings are flag *values* only; nothing is written.

## Invariants & gotchas
- The parametrized cases are the project's real history: if a new flag mistake costs a build, add it here.
- `test_missing_plugin_flag_is_caught` tests the checker's own rule ("`--noinclude-*-mode` only alongside a plugin flag"). That rule is stricter than Nuitka itself, which registers those anti-bloat options even without `--enable-plugin` ([checker page](../../scripts/check_build_flags.md#why-the-plugin-options-are-special)). Dropping the PySide6 plugin would break the app anyway, so being told is useful; just don't read the test as "Nuitka rejects this".

## Tests
- **Gaps:** flag *values* (paths, plugin names) are not checked by the checker, so not here either.

## History
- `a2e41d0` (M5): added with the checker ([dev log, Milestone 5](../../../04-development-log.md#four-wrong-flags-four-lost-builds)).
