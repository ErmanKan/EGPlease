# `scripts/check_build_flags.py`

> Checks, in about a second, that every flag `scripts/build.py` passes to Nuitka is an option Nuitka really accepts, for both the Linux and the Windows command line (M5).

## Where it sits
- **Layer:** tooling (plain Python; imports Nuitka's option parser, compiles nothing)
- **Used by:** contributors after touching `scripts/build.py` (AGENTS.md rule); [`.github/workflows/build-exe.yml`](../config-files.md#githubworkflowsbuild-exeyml) (step "Check every Nuitka flag…", before the build); `tests/core/test_check_build_flags.py` (imports it as `check_build_flags`).
- **Uses:** [`scripts/build.py`](build.md) (`build_command`), `nuitka.options.OptionParsing` from the venv (`nuitka==4.3`, see [build requirements](../config-files.md#packagingbuild-requirementstxt)).

## Public API
```bash
.venv/bin/python scripts/check_build_flags.py      # exit 0 = all flags valid, 1 = problems listed
```
Typical output:
```
Nuitka unknown accepts 216 long options
Linux    22 args -> ok
Windows  22 args -> ok

All flags are valid for both platforms.
```

| Name | Kind | Purpose |
|---|---|---|
| `PLUGIN_FLAGS` | tuple | `enable-plugin`, `enable-plugins`, `plugin-enable`: the spellings that switch on a plugin. |
| `PLUGIN_DEPENDENT` | tuple | `noinclude-pytest-mode`, `noinclude-setuptools-mode`: options that are not in the static option table (see below). |
| `WINDOWS_ONLY` | tuple | `windows-icon-from-ico`, `windows-company-name`, `windows-product-name`: must never appear in the Linux command. |
| `known_options() -> set[str]` | function | Every option name in `OptionParsing.parser` and its option groups (long and short names, without dashes). |
| `flag_name(arg) -> str \| None` | function | `"--foo=bar"` → `"foo"`; `None` for an argument that is not a `--` option (the Python path, `-m`, the script path). |
| `check(platform_name, *, windows, known) -> list[str]` | function | Builds `build.build_command("0.1.0", windows=windows)` and returns a list of problems (empty = fine); prints one summary line. |
| `main() -> int` | function | Runs `check` for Linux and Windows plus the regression and version checks; prints the problems; returns 0 or 1. |

## How it works
1. **Imports.** It puts `src/` and `scripts/` on `sys.path` and imports `build` as a module (the module under test). Importing `nuitka.options.OptionParsing` builds Nuitka's real `optparse` parser with every built-in option registered.
2. **`check` per platform.**
   - Every flag name must be in `known`. Exceptions: the plugin flags and the plugin-dependent `--noinclude-*-mode` options, which are accepted **only if a plugin flag is also present** in the same command.
   - **Windows:** `--windows-icon-from-ico` and `--windows-console-mode` must both be present (the icon of the `.exe`, and stdout reaching a terminal for the smoke test).
   - **Linux:** none of `WINDOWS_ONLY` may appear, and the console flag must be exactly `--windows-console-mode=disable`.
3. **`main` extras.**
   - **Regression guard:** `--cache-dir` and `--no-console` must never come back. Neither is a Nuitka option; each cost a 20-minute build before this script existed. (They would also fail the "unknown option" check; the guard gives a clearer message.)
   - **Version wiring:** `--file-version` and `--product-version` must carry the version passed to `build_command` (`"0.1.0"`); a broken version string is otherwise only noticed late in a build.

### Why the plugin options are special
Two things are not visible in Nuitka's static option table, so a naive "is every flag in the table?" check would reject the committed, working command:

- **`--enable-plugin`** (singular, the form in the docs and in `build.py`) is not a registered name: the table has `--enable-plugins` and `--plugin-enable`. Nuitka accepts `--enable-plugin` because its parser (like `optparse`) accepts an **unambiguous prefix** of a long option, and it also scans `sys.argv` for `--enable-plugin=` to load the named plugin's own options.
- **`--noinclude-pytest-mode` / `--noinclude-setuptools-mode`** belong to Nuitka's **anti-bloat** plugin. Plugin options are added to the parser only while the command line is parsed, by `addStandardPluginCommandLineOptions` (in `nuitka/plugins/Plugins.py`); merely importing `OptionParsing` does not add them.

The script models both by accepting these names only when a plugin flag is present. Its docstring says the `--noinclude-*` options are valid "*because* the plugin flag is passed". Reading Nuitka 4.3's source for this page shows that is **stricter than Nuitka**: anti-bloat is an *always-enabled* plugin (`isAlwaysEnabled()` returns `True`), and `addStandardPluginCommandLineOptions` adds the options of always-enabled plugins on every parse, with or without `--enable-plugin`. So the rule can only produce a false alarm (if the PySide6 plugin flag were dropped, which would break the app anyway), never miss a real error. The code's behaviour is fine; its explanation is slightly inaccurate.

### Why `--windows-console-mode` is allowed on Linux
Nuitka accepts `--windows-console-mode` on every platform; on a non-Windows host it only logs "Using OS specific option … has no effect" (`_warnOSSpecificOption`). What really must not appear in a Linux build is `--windows-icon-from-ico`, which points at a Windows-only resource. An earlier idea, "no `--windows-` flag on Linux", would therefore have been wrong; the script checks the specific flags instead.

## Invariants & gotchas
- **Run it after every change to `scripts/build.py`.** It is the cheap check; the build is the expensive one.
- It validates **names**, not values: a wrong path or a wrong plugin name (`--enable-plugin=pyside7`) passes here and fails in Nuitka. Only the console-mode value and the version values are checked.
- It is stricter than Nuitka for abbreviations: an unambiguous shortened flag (say `--assume-yes`) would be accepted by Nuitka but is reported here as unknown. `--enable-plugin` is the one abbreviation it knows about. Write every other flag in full.
- It needs `nuitka` installed (`packaging/build-requirements.txt`); the test file therefore also needs it, and it is in the project venv.
- **Cosmetic bug:** the first line prints `Nuitka unknown`, because `nuitka` has no `__version__` attribute (Nuitka 4.3 exposes its version through `nuitka.Version.getNuitkaVersion()`). It does not affect the result.

## Tests
- `tests/core/test_check_build_flags.py` ([page](../tests/core/test_check_build_flags.md)): the committed command lines pass for both platforms; each historical mistake injected into the command is caught (`--cache-dir`, `--no-console`, a Windows icon flag in the Linux build, an invented flag); dropping `--enable-plugin` is reported.

## History
- `a2e41d0` (M5): added after four flag mistakes had each cost a full build ([dev log, Milestone 5](../../04-development-log.md#four-wrong-flags-four-lost-builds)).
- `7bac56c` (M5): run in the build workflow before the build.
