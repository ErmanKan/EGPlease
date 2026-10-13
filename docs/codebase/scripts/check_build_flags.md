# `scripts/check_build_flags.py`

> Checks, in about a second, that every flag `scripts/build.py` passes to Nuitka is an option Nuitka really accepts, for both the Linux and the Windows command line (M5).

## Where it sits
- **Layer:** tooling (plain Python; imports Nuitka's option parser, compiles nothing)
- **Used by:** contributors after touching `scripts/build.py` (AGENTS.md rule); [`.github/workflows/build-exe.yml`](../config-files.md#githubworkflowsbuild-exeyml) (step "Check every Nuitka flag…", before the build); `tests/core/test_check_build_flags.py` (imports it as `check_build_flags`).
- **Uses:** [`scripts/build.py`](build.md) (`build_command`), `nuitka.options.OptionParsing` from the venv (`nuitka==4.3`, see [build requirements](../config-files.md#packagingbuild-requirementstxt)).

## Public API
```bash
.venv/bin/python scripts/check_build_flags.py      # exit 0 = all flags accepted, 1 = problems listed
```
Typical output:
```
Nuitka 4.3
Linux    23 args -> ok
Windows  23 args -> ok

All flags are accepted by Nuitka's parser for both platforms.
```

| Name | Kind | Purpose |
|---|---|---|
| `WINDOWS_ONLY` | tuple | `windows-icon-from-ico`, `windows-company-name`, `windows-product-name`: must never appear in the Linux command. |
| `PLUGIN_FLAG_PREFIXES` | tuple | `--enable-plugin=`, `--enable-plugins=`, `--plugin-enable=`: how the command names the plugins whose options must be registered. |
| `fresh_parser(cmd)` | function | A new Nuitka parser set up the way `python -m nuitka` sets it up for `cmd`: built-in options, the always-on plugins' options, and the options of every plugin `cmd` enables. |
| `rejected_flags(cmd) -> list[str]` | function | Parses each `--` flag of `cmd` on its own with that parser; returns those the parser refuses (its error text is swallowed). |
| `flag_name(arg) -> str \| None` | function | `"--foo=bar"` → `"foo"`; `None` for an argument that is not a `--` option. |
| `check(platform_name, *, windows) -> list[str]` | function | Builds `build.build_command("0.1.0", windows=windows)`, returns its problems (empty = fine), prints one summary line. |
| `main() -> int` | function | Runs `check` for Linux and Windows plus the version check; returns 0 or 1. |

## How it works
1. **Imports.** It puts `src/` and `scripts/` on `sys.path` and imports `build` (the module under test).
2. **A parser per command line (`fresh_parser`).** Nuitka's parser is module state, created when `nuitka.options.OptionParsing` is imported, so each check reloads that module to get a clean one. Then, like Nuitka itself:
   - `addStandardPluginCommandLineOptions` adds the options of the always-on plugins (e.g. anti-bloat's `--noinclude-pytest-mode`);
   - `addPluginCommandLineOptions` adds the options of each plugin the command enables (`--enable-plugin=pyside6` brings `--noinclude-qt-plugins`).
3. **Parse each flag (`rejected_flags`).** Every `--` argument is parsed alone, as `parser.parse_args([flag, "main.py"])`. `optparse` exits with code 2 on an unknown option or a bad value for a choice option; that exit is caught and the flag reported. Because the real parser is used, its rules come for free: an unambiguous prefix is accepted (`--enable-plugin` is `--enable-plugins`), and a plugin option is rejected when its plugin is not enabled.
4. **Platform rules (`check`).**
   - **Windows:** `--windows-icon-from-ico` and `--windows-console-mode` must both be present (the `.exe` icon, and stdout reaching a terminal).
   - **Linux:** none of `WINDOWS_ONLY` may appear, and the console flag must be exactly `--windows-console-mode=disable`.
5. **Version wiring (`main`).** `--file-version` and `--product-version` must carry the version given to `build_command`; a broken version string is otherwise only noticed late in a build.

### Why the plugin options are special
Plugin options are not in Nuitka's static option table; they are added to the parser while a command line is processed. The first version of this script modelled that by hand (a list of names "valid only if a plugin flag is present"), which was both stricter than Nuitka (anti-bloat is always on, so its options need no plugin flag) and blind to new plugin options. Parsing with a parser set up exactly as Nuitka sets it up replaced that model.

One trap had to be handled: Nuitka remembers, in the module-level dict `nuitka.plugins.Plugins.plugin_options`, every plugin whose options it has registered, and skips it next time. The second fresh parser (the Windows check, run after the Linux one) therefore received **no** plugin options and "rejected" three valid flags. `fresh_parser` clears that dict first; the test `test_committed_command_lines_are_valid` runs Linux, Windows, Linux to keep it fixed.

### Why `--windows-console-mode` is allowed on Linux
Nuitka accepts `--windows-console-mode` on every platform; on a non-Windows host it only logs that the option has no effect. What must not appear in a Linux build is `--windows-icon-from-ico`, which points at a Windows-only resource, so the script checks specific flags rather than banning every `--windows-` flag.

## Invariants & gotchas
- **Run it after every change to `scripts/build.py`.** It is the cheap check; the build is the expensive one.
- It checks that Nuitka's **parser** accepts each flag, not that the value makes sense: a wrong path passes here and fails in the build. A misspelt plugin name (`--enable-plugin=pyside7`) is caught, because registering that plugin's options fails.
- Each flag is parsed alone, so a flag that is only invalid in combination with another (two conflicting modes) is not detected.
- It needs `nuitka` installed (`packaging/build-requirements.txt`); so does its test file. Both are in the project venv.
- The version line comes from `nuitka.Version.getNuitkaVersion()`; `nuitka` has no `__version__` attribute.

## Tests
- `tests/core/test_check_build_flags.py` ([page](../tests/core/test_check_build_flags.md)): the committed command lines pass for both platforms, in the order Linux, Windows, Linux (guards the stale plugin registry); four bad flags injected into the command are rejected on both platforms (`--cache-dir`, `--no-console`, a misspelt option, an invented one); a Windows icon flag in the Linux command is reported; dropping `--enable-plugin` makes `--noinclude-qt-plugins` invalid; `--enable-plugin` is accepted as a prefix.

## History
- `a2e41d0` (M5): added after four flag mistakes had each cost a full build ([dev log, Milestone 5](../../04-development-log.md#four-wrong-flags-four-lost-builds)).
- `7bac56c` (M5): run in the build workflow before the build.
- `bb955b2` (M5): version line fixed (`Nuitka unknown`).
- `866533e` (M5): rewritten to parse with Nuitka's own parser (plugin options included) instead of a hand-made list of option names; fixed the stale `plugin_options` registry that made the second check reject valid flags.
