# `scripts/smoke_build.py`

> Runs a built `GifEditor` binary three times and decides from exit codes and the written file whether the bundle works: it fails cleanly, edits and writes a GIF, and opens a GIF in its real window (M5).

## Where it sits
- **Layer:** tooling (plain Python; runs the binary as a child process)
- **Used by:** contributors after [`scripts/build.py`](build.md); [`.github/workflows/build-exe.yml`](../config-files.md#githubworkflowsbuild-exeyml) (step "Smoke-test the built executable", before the upload).
- **Uses:** the built binary; `tests/gifgen.py` (`make_gif`, `solid_frames`) for the input GIF; Pillow to read the output's size. Inside the binary it exercises [`gif_editor.headless`](../src/gif_editor/headless.md) (`--edit-spec`) and [`gif_editor.app`](../src/gif_editor/app.md) (`--smoke-gui`).

## Public API
```bash
.venv/bin/python scripts/smoke_build.py [path/to/binary]
# default: out/dist/GifEditor.exe if it exists, else out/dist/GifEditor
```
Exit 0 and `OK: the built binary starts, edits and writes a GIF, and opens one in its window.`; or exit 1 and a `FAILED:` block with the last 30 output lines of each failed step.

| Name | Kind | Purpose |
|---|---|---|
| `default_binary()` | function | First existing of `out/dist/GifEditor.exe`, `out/dist/GifEditor`; exits with a message if neither exists. |
| `make_fixture(path, frames=8)` | function | Writes an 8-frame 64×48 solid-colour GIF, 100 ms per frame, with `tests/gifgen.py`. |
| `run(binary, args, workdir, timeout=120)` | function | Runs the binary with `QT_QPA_PLATFORM=offscreen` and `TMPDIR=workdir`, in `workdir`, capturing output; raises `TimeoutExpired` after 120 s. |
| `main()` | function | The three steps below. |

## How it works
A onefile binary cannot be imported, only run, so every check is a child process.

0. **Set-up.** Create a fresh temp folder (`tempfile.mkdtemp(prefix="gifedit-smoke-")`), copy the binary into it and make it executable, write the fixture GIF `in.gif` there. Each run gets `TMPDIR` = that folder, because the onefile bootstrap unpacks the app into `TMPDIR` and executes it from there.
1. **Missing file, cleanly.** `--edit-spec <work>/missing.gif out=<work>/x.gif`. Pass: exit code **1** and no `Traceback` on stderr. Proves the frozen interpreter starts, the core imports, and an error is reported as one `ERROR …` line rather than a crash.
2. **A real edit.** `--edit-spec in.gif "trim=0:400,delete=2,crop=8:6:40:30,size=32x24,colors=64,out=<work>/out.gif"`. Pass: exit **0** and `out.gif` exists and is **32×24**. Proves Pillow, numpy and the whole pipeline (decode, timeline, crop, resize, palette, encode, verify) are bundled. This path never imports Qt.
3. **The real window.** `--smoke-gui in.gif`. Pass: exit **0**. The app starts its `QApplication` on the offscreen platform, shows `MainWindow`, opens and decodes the GIF, then quits by itself ([app page](../src/gif_editor/app.md#how-it-works)). Proves the Qt half: PySide6, the platform plugin and the window code.
4. Each step prints one line: step name, exit code, `ok`/`FAILED`, and the first `RESULT`/`ERROR`/`GUI` line of the output if there is one. A `TimeoutExpired` in any step is recorded as a failure (and skips the remaining steps). The temp folder is always deleted.

*Why exit codes and the file only:* the printed lines are diagnostics, not evidence. A Windows GUI executable built with console mode `attach` may not deliver its stdout to a pipe (it attaches to a parent console if there is one, and a pipe is not a console), so a check that waited for `RESULT` could fail on a working `.exe`. Exit codes and the output file are reliable on every platform.

### Two bugs found by reading it before it ever ran
The first version (`3531ca0`) was written while no binary existed. Reading it again before the first real run found two serious faults, fixed in `7bac56c`:
1. **It would have hung.** Step 1 started the binary with just a missing path, i.e. the **GUI**, and expected exit code 1. But a missing file is not a startup failure for the GUI: the window opens, shows its "can't open file" dialog, and the event loop keeps running until a user closes the window. Nobody would, so the step would sit until the 120 s timeout (and, since that version did not catch `TimeoutExpired`, end the script with a traceback). Step 1 now uses `--edit-spec`, which never opens a window.
2. **It never tested Qt.** Both steps used `--edit-spec`, which returns before anything imports Qt. A binary without its Qt platform plugin, the most likely packaging mistake, would have passed. Step 3 (`--smoke-gui`) was added for that.

It also required a `RESULT` line on stdout, which is unreliable on Windows (see above); that requirement was dropped.

## Invariants & gotchas
- **Linux dev container: set `TMPDIR` before running it.** `/tmp`, `/dev/shm`, `/var/tmp` and the project drive are mounted `noexec`, and the onefile bootstrap must execute the unpacked program. `mkdtemp` uses the caller's `TMPDIR`, so point it at an executable folder under `$HOME`:
  ```bash
  mkdir -p "$HOME/smoke-tmp" && TMPDIR="$HOME/smoke-tmp" .venv/bin/python scripts/smoke_build.py out/dist/GifEditor
  ```
  This is a container quirk, not an app problem; on Windows and in CI no setting is needed. (An earlier docstring said the script copies the binary "under `$HOME`" by itself; it does not, it uses whatever `TMPDIR` says.)
- The script needs Pillow and `tests/gifgen.py`, i.e. a checkout with the dev venv. It tests a binary; it is not shipped.
- Step 3 fails fast if the bundled self-test fails: under `--smoke-gui`, `app.main` prints `GUI FAIL startup self-test: ...` and exits 1 instead of showing its blocking dialog (an earlier version would only have failed at the 120 s timeout).
- `QT_QPA_PLATFORM=offscreen` is set for all steps; steps 1–2 do not need it.

## Tests
- n/a (it is itself the test of a built binary). Its building blocks are unit-tested from source: `tests/core/test_headless.py` covers `--edit-spec`.
- **Gaps:** `--smoke-gui` / `_arm_smoke_exit` have no pytest test; they are only exercised through this script on a built binary.

## History
- `3531ca0` (M5): first version (missing path via the GUI, plus `--edit-spec`).
- `7bac56c` (M5): rewritten: three steps, `--smoke-gui`, pass/fail by exit code and file only ([dev log, Milestone 5](../../04-development-log.md#the-smoke-test-would-have-hung)).
