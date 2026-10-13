# `tests/core/test_check_build_flags.py`

> Tests that the Nuitka flag checker accepts the committed build command and catches each flag mistake that was actually made during M5.

## Where it sits
- **Layer:** tests (tooling, no Qt)
- **Used by:** pytest.
- **Uses:** `scripts/check_build_flags.py` (imported as `check_build_flags` after putting `scripts/` on `sys.path`), and through it `scripts/build.py` and Nuitka's option parser (`nuitka==4.3` must be in the venv).

## Public API
| Test | Verifies |
|---|---|
| `test_committed_command_lines_are_valid` | `check()` returns no problems for the Linux and the Windows command `build.py` really produces, run as Linux, Windows, Linux: each check builds a fresh Nuitka parser, and the repeat proves the second and third still get the plugin options (they did not, before `plugin_options` was cleared). |
| `test_injected_bad_flag_is_rejected[--cache-dir=out/cache]` | Not a Nuitka option (cost one full build). Rejected on both platforms. |
| `test_injected_bad_flag_is_rejected[--no-console]` | Not a Nuitka option (cost another). |
| `test_injected_bad_flag_is_rejected[--onefile-tempdir-spec-typo={TEMP}]` | A misspelt real option. |
| `test_injected_bad_flag_is_rejected[--invented-flag=1]` | A made-up flag. |
| `test_windows_only_flag_must_not_reach_a_linux_build` | `--windows-icon-from-ico` added to the Linux command only is reported. Nuitka would accept it (on Linux it only warns), so this is the checker's own platform rule. |
| `test_plugin_options_need_their_plugin` | With `--enable-plugin=pyside6` removed, Nuitka's parser rejects `--noinclude-qt-plugins` (it belongs to the pyside6 plugin): real Nuitka behaviour, not a rule of the checker. |
| `test_rejected_flags_uses_prefix_matching` | `--enable-plugin` (a prefix of `--enable-plugins`) is accepted, as by Nuitka. |

**8 test cases** (5 functions, one parametrized 4 ways).

## How it works
`monkeypatch` replaces `build.build_command` (on the `build` module the checker imported) with a wrapper around the real one that appends or removes flags; the checker then runs on the result. Flag values such as `out/cache` and `x.ico` are strings only; nothing is written.

## Invariants & gotchas
- The bad-flag cases are the project's real history: if a new flag mistake costs a build, add it here.
- These tests run Nuitka's parser, so they also pin Nuitka 4.3 behaviour the build relies on (plugin options exist only with their plugin; prefixes are accepted). A Nuitka upgrade that changes either shows up here first.

## Tests
- **Gaps:** combinations of flags (two conflicting modes) are not checked, because each flag is parsed alone.

## History
- `a2e41d0` (M5): added with the checker ([dev log, Milestone 5](../../../04-development-log.md#four-wrong-flags-four-lost-builds)).
- `866533e` (M5): rewritten for the parser-based checker (prefix matching, real plugin-option rule, stale-registry guard).
