# `scripts/build.py`

> The Nuitka recipe that turns the source tree into one self-contained executable: `out/dist/GifEditor.exe` on Windows, `out/dist/GifEditor` on Linux (M5).

## Where it sits
- **Layer:** tooling (plain Python; runs Nuitka as a child process)
- **Used by:** contributors building by hand; [`.github/workflows/build-exe.yml`](../config-files.md#githubworkflowsbuild-exeyml) (the "Build the single-file executable" step); [`scripts/check_build_flags.py`](check_build_flags.md) imports it and calls `build_command` to validate the flags.
- **Uses:** `src/gif_editor/__init__.py` (reads `__version__` as text), `src/gif_editor/__main__.py` (the entry script it compiles), `src/gif_editor/resources/icons/icon.ico` / `icon-256.png` (made by [`make_icon.py`](make_icon.md)); the build dependencies in [`packaging/build-requirements.txt`](../config-files.md#packagingbuild-requirementstxt) (`nuitka==4.3`, plus `patchelf` on Linux).

## Public API
```bash
.venv/bin/python scripts/build.py          # Linux (container): proves the recipe, makes a Linux binary
.venv\Scripts\python scripts\build.py      # Windows: makes GifEditor.exe
```
No arguments. Exit code 0 on success; Nuitka's own exit code if it failed; 1 if Nuitka "succeeded" but no `GifEditor*` file appeared in `out/dist/`.

| Name | Kind | Purpose |
|---|---|---|
| `ROOT`, `SRC`, `OUT`, `DIST`, `ICONS` | constants | Repo root, `src/`, `out/`, `out/dist/`, `src/gif_editor/resources/icons/`. |
| `APP_NAME = "GifEditor"` | constant | Output file name (Nuitka appends `.exe` on Windows by itself). |
| `version() -> str` | function | Reads the `__version__ = "..."` line of `src/gif_editor/__init__.py` as text (no import, so it works without the app's dependencies); `"0.0.0"` if the line is missing. |
| `build_command(ver, *, windows=None) -> list[str]` | function | The full Nuitka command line. `windows=None` means "the platform this runs on"; `True`/`False` force one, so the **Windows** command can be built and checked on Linux. |
| `main() -> int` | function | Checks the inputs, prints and runs the command with `PYTHONPATH=src`, reports what was produced. |

## How it works
1. **Version.** `version()` reads `__init__.py` line by line. The version ends up in the file properties of the `.exe` (`--file-version`, `--product-version`). `__init__.py` is the single source of truth; `pyproject.toml` has the same number and must be kept in sync by hand.
2. **Pre-checks.** `main()` stops with a message if `src/gif_editor/__main__.py` is missing (wrong working directory) or, on Windows, if `icon.ico` is missing (run `make_icon.py`). It creates `out/dist/`.
3. **The command** (`build_command`). Every flag is commented in the code with the reason it is there; several are there because leaving them out, or getting them wrong, cost a ~20-minute compile ([dev log](../../04-development-log.md#four-wrong-flags-four-lost-builds)):

| Flag | Why |
|---|---|
| `--include-package=gif_editor` | Pointed only at `__main__.py`, Nuitka followed that script's imports but did not resolve `gif_editor.app`; the first binary died at start with `No module named 'gif_editor.app'`. Including the whole package fixes it. |
| `--include-package-data=gif_editor` | Packs the non-code files of the package (the icons in `resources/icons/`) into the executable, so the running window can load its icon. |
| `src/gif_editor/__main__.py` | The entry point (the same as `python -m gif_editor`). |
| `--onefile` | One self-contained file (Gate 1 decision: a literal single `.exe`). |
| `--output-dir=out/dist`, `--output-filename=GifEditor` | Where the result goes and its name. Nuitka adds `.exe` on Windows. Its working folders (`__main__.build/`, `__main__.dist/`) also land in `out/dist/`; they are gitignored. |
| `--report=out/nuitka-report.xml` | Nuitka's compilation report (which modules and DLLs were included); useful when the binary misses something. |
| `--enable-plugin=pyside6` | Ships Qt's plugins (platform plugin, image formats) and PySide6's support files. Without it the GUI cannot start. |
| `--windows-console-mode=attach` (Windows) / `=disable` (Linux) | `attach`: when started from a terminal, stdout/stderr go to that terminal (crash text, the `RESULT`/`GUI OK` lines of the smoke test); started from Explorer, no console window appears. On Linux the console concept does not apply, so `disable`. The first version used `--no-console`, which is **not a Nuitka option**. |
| `--assume-yes-for-downloads` | Lets Nuitka download its helper tools (e.g. its dependency walker or a C compiler on Windows) on the first build instead of stopping at an interactive question, which would hang CI. |
| `--noinclude-qt-plugins=…` (`UNUSED_QT_PLUGINS`) | Drops 10 of Nuitka's "sensible" Qt plugin families the app never uses (iconengines, mediaservice, printsupport, platformthemes, tls, egldeviceintegrations, xcbglintegrations, three wayland-*). Kept: `platforms`, `imageformats` (QIcon reads the `.ico` window icon through it on Windows), `styles`. Smaller exe; on Linux each bundled library costs a slow `ldd` scan (the dropped families kept one build in that scan for 30+ minutes). Nuitka discards the names from a set, so names that do not exist on the build platform are ignored and one list serves both. |
| `--noinclude-pytest-mode=nofollow`, `--noinclude-setuptools-mode=nofollow` | Don't follow imports into pytest and setuptools: both are in the venv (dev tools) but never used at runtime, and they would bloat the binary. |
| `--company-name`, `--product-name`, `--file-version`, `--product-version`, `--file-description`, `--copyright` | The text Windows shows in the file's Properties → Details. `--copyright=MIT` states the licence, not a copyright holder. |
| `--windows-icon-from-ico=…/icon.ico` (Windows only) | The icon of the `.exe` file in Explorer and in the taskbar before the window sets its own. This flag is Windows-only, so it is never added to the Linux command. |
| `--linux-icon=…/icon-256.png` (Linux only) | The Linux counterpart. |

4. **`PYTHONPATH=src` for the Nuitka subprocess.** The app is not installed; it runs from `src/`. `--include-package=gif_editor` is resolved through the *build* interpreter's import path, which does not contain `src/`, so the second failed build stopped with "failed to locate package 'gif_editor'". `main()` copies the environment and prepends `src` to `PYTHONPATH` (keeping any existing value) before `subprocess.run(cmd, cwd=ROOT, env=env)`.
5. **Result.** On a non-zero exit it prints "Nuitka failed" and returns that code. Otherwise it lists every `out/dist/GifEditor*` **file** with its size, and fails if there is none.

## Invariants & gotchas
- **No cross-compiling.** Nuitka compiles to C and builds with the platform's C compiler, so a Windows `.exe` can only be built on Windows (CI or the user's PC). The Linux build in the container proves the recipe (flags, includes, data files, onefile packing), not the Windows binary.
- **After editing this file, run** `.venv/bin/python scripts/check_build_flags.py` ([page](check_build_flags.md)). It validates every flag for both platforms against Nuitka's own parser in about a second, instead of finding a typo after a 20-minute compile. CI runs it before the build.
- **Linux builds need `patchelf`.** Nuitka's onefile mode on Linux calls `patchelf`. It is pinned in `packaging/build-requirements.txt` (`patchelf==0.19.1.0`, non-Windows only) and installed as a wheel **inside the venv** (no system install). Put the venv's `bin/` on `PATH` for a local Linux build: `PATH=$PWD/.venv/bin:$PATH .venv/bin/python scripts/build.py`.
- **Build time.** A from-scratch Linux build takes about 20 minutes in the container. Profiling showed that is **not** the C compile: most of it is Nuitka's Linux dependency scan, which runs `ldd` once per bundled `.so` (269 in PySide6) with a 104-directory `LD_LIBRARY_PATH`, and failed file lookups are slow on this container's overlay filesystem ([dev log](../../04-development-log.md#two-wrong-claims-about-why-the-build-was-slow)). On Windows Nuitka uses its own DLL dependency walker instead of `ldd`, so that cost does not apply there. The module docstring says "A rebuild reuses Nuitka's cache under `out/nuitka-build/`": **that is wrong**. No flag points Nuitka at `out/nuitka-build/` (and `--cache-dir` does not exist). Nuitka keeps its cross-build cache (compiled-object cache, downloaded tools) in the user cache folder (`~/.cache/Nuitka` on Linux, `%LOCALAPPDATA%\Nuitka\Nuitka\Cache` on Windows), or wherever the `NUITKA_CACHE_DIR` environment variable points; the per-build C sources are in `out/dist/__main__.build/`. The code is the truth; the docstring should be corrected in a code commit.
- **Where the onefile unpacks.** At start, the onefile binary unpacks itself into a folder under the user's temp directory (Nuitka's default) and runs from there. So the `.exe` never writes next to itself and works from a read-only folder or a USB stick. An earlier draft set `--onefile-tempdir-spec` with `{TEMP_DIR}`; that variable does not exist (it is `{TEMP}`), and since the default already does the right thing, the flag was dropped.
- **Do not run two builds at once** and do not delete `out/dist/` while a build runs: Nuitka writes its working folders there.
- `version()` parses text, so `__version__` must stay a simple `__version__ = "x.y.z"` line at the start of a line.

## Tests
- `tests/core/test_check_build_flags.py` ([page](../tests/core/test_check_build_flags.md)): the command lines `build_command` produces for Linux and Windows contain only real Nuitka options; injected historical mistakes are caught.
- [`scripts/smoke_build.py`](smoke_build.md) checks the built binary (manual in the container, automatic in the build workflow).
- **Gaps:** `main()` itself is not tested (it needs a full build, about 20 minutes in the container); `version()` is only exercised indirectly through `check_build_flags.py` (it checks that the version string reaches `--file-version`/`--product-version`).

## History
- `3531ca0` (M5): added, after four failed builds had fixed the flags ([dev log, Milestone 5](../../04-development-log.md#milestone-5-packaging)).
- `a2e41d0` (M5): `build_command` gained the keyword-only `windows` parameter so `check_build_flags.py` can validate the Windows command on Linux.
