# RESUME HERE — mid Milestone 5 (packaging)

**Written:** 2026-10-11, during M5, before a planned PC shutdown.
**Repo:** `/workspace/projects/gif-editor` (host: `F:\Projects\gif-editor`), branch `main`, HEAD `4779648`.

## State: everything is committed

`git status` is clean. Tests: **679 passed + 2 xfailed**, lint clean (measured at the last full run
before the M5 code landed; re-run `scripts/test.sh` to confirm).

| Milestone | Status |
|---|---|
| M1–M4 | ✅ Done |
| M5 Packaging | 🔄 **In progress** — see below |

### M5 done so far (commits `3531ca0`, `4779648`)
- `scripts/make_icon.py` — generates the icon (no binary art is hand-made). Multi-size `.ico`
  (16/24/32/48/64/128/256) plus PNGs in `src/gif_editor/resources/icons/`. **Small sizes are drawn
  separately, not downscaled**: at 16 px the film sprockets vanished, so sizes ≤ 32 px are drawn as a
  bold play triangle on the plate. Regenerating produces a byte-identical file (CI asserts this).
- `src/gif_editor/resources/__init__.py` — `icon_path()` / `resource_path()`, working both from a source
  checkout and inside a Nuitka onefile (which unpacks to a temp dir; checks `__file__` then
  `NUITKA_ONEFILE_DIR`).
- `src/gif_editor/app.py` — sets the window/taskbar icon; the `--edit-spec` branch was moved **above every
  Qt import** (importing Qt needs a platform plugin and libEGL, and the headless path must work on a bare
  server).
- `src/gif_editor/headless.py` — `--edit-spec IN.gif "trim=0:400,delete=2,crop=8:6:40:30,size=32x24,out=OUT.gif"`:
  one complete edit+generate with no window, printing a `RESULT frames=… size=… bytes=… path=…` line.
  Exists so a packaged build can be verified automatically. Verified working from source.
- `scripts/build.py` — the Nuitka onefile recipe (shared by Windows and Linux).
- `scripts/smoke_build.py` — runs a built binary and checks it starts, edits and writes a GIF.
- `packaging/build-requirements.txt` — pinned build deps (`nuitka==4.3`, `ordered-set`, `zstandard`,
  `patchelf` on non-Windows).
- `.github/workflows/build-exe.yml` — **the way to get a real `.exe`**: lint+test, check the icon is
  current, build, smoke-test, upload `GifEditor.exe` as an artifact. Trigger it manually
  (Actions → Build GifEditor.exe → Run workflow) or push a `v*` tag.

### The one thing that is NOT done: the `.exe` itself was never produced

**Nuitka cannot cross-compile.** This container is Linux with no Windows toolchain, no mingw, no wine, and
nothing on the host is executable from inside it (`/mnt/c` does not exist; `C:\` is mounted at `/root` but
only as inert files). So a `.exe` can only be built on Windows, by CI or by the user.

What *was* proven here: the recipe compiles a **Linux onefile binary successfully** (an 11.5 MB self-contained
`out/dist/GifEditor`, first built earlier in the session). The recipe's bugs were found and fixed by doing it:
1. `--include-package=gif_editor` is required — pointed only at `__main__.py`, Nuitka could not see
   `gif_editor.app` and the binary died with `No module named 'gif_editor.app'`.
2. `--include-package` is resolved through the *build* interpreter's path, so `scripts/build.py` sets
   `PYTHONPATH=src` for the Nuitka subprocess; without it Nuitka stops with "failed to locate package".
3. `--cache-dir` and `--no-console` are not real options (a bad build with those exited 2).
4. On Linux, Nuitka onefile needs `patchelf`; it is installed project-locally in the venv (the wheel
   `patchelf==0.19.1.0`), never system-wide.
5. Onefile unpacks into `TMPDIR` and execs from there. The container mounts `/tmp`, `/dev/shm`, `/var/tmp`
   **and the project drive** with `noexec`, so the binary only runs with `TMPDIR` pointed at an executable
   directory (`/root/…`). This is a container quirk, not an app problem, but it is why `smoke_build.py`
   copies the binary into `$HOME`-based temp dir before running it.

### Next step for M5 (start here)
1. Check out the repo on Windows (or push to GitHub and run the `build-exe.yml` workflow).
2. `.venv\Scripts\python -m pip install -r requirements-dev.txt -r packaging/build-requirements.txt`
3. `.venv\Scripts\python scripts\build.py` → `out\dist\GifEditor.exe`
4. `.venv\Scripts\python scripts\smoke_build.py out\dist\GifEditor.exe` → must print "OK".
5. Then the M5 exit criterion from [02-plan.md §6](02-plan.md#6-milestones): it runs on a **clean Windows 11
   VM with no Python**, from any folder or a USB stick. Until that has happened, M5 is *not* done. Also
   still open from the plan: the licence bundle in `packaging/licenses/` (currently only a `.gitkeep`) and
   code signing (explicitly optional, not needed for a personal build).
6. After the first successful `.exe`, the M5 docs pass still has to run (per-file pages for
   `scripts/build.py`, `make_icon.py`, `smoke_build.py`, `headless.py`, `resources/__init__.py`,
   `packaging/build-requirements.txt`, `.github/workflows/build-exe.yml`, a `tests/` page for the new
   headless tests, INDEX rows, README "Download/Build" section, dev-log M5 section, AGENTS.md).

### Also outstanding (small)
- `tests/` has **no tests for the new M5 code yet** (headless spec parsing, `icon_path()` resolution).
  The smoke test proves the path end-to-end but is manual; a `tests/core/test_headless.py` and a
  small `tests/test_resources.py` are the obvious gap.
- A full-suite run under load gave one failure, `tests/core/test_timeline.py::test_performance_10k_frames`
  (a 50 ms budget). It passes alone and passed in every earlier run; the load was the concurrent Nuitka
  build (load average 4.7 vs ~1.7). Worth knowing if CI ever reports it: it is a wall-clock assertion on a
  shared runner.

## Known issues carried from M4 (unchanged)
- The filmstrip has a fixed 140 px height; at 911×512 logical (1366×768 at 150 %) the canvas gets ~184 px.
- The size estimate can be low (~0.67×) on long GIFs whose middle is unrepresentative.
- The crash/deadlock seen in the suite before `9ab961f`/`c4b9329` was never reproduced in 48 runs after the
  fix (30-run soak: 30/30 clean).

## Environment reminders
- Tests: `scripts/test.sh`. HiDPI: `scripts/test-hidpi.sh`. Probe: `PYTHONPATH=src:tests .venv/bin/python scripts/stress_probe.py`
  (and `scripts/fuzz_decoder.py`). All keep their files under `out/` (gitignored) — never `/tmp`.
- Build deps for local Linux builds are in the venv already; `.venv/bin/patchelf` must be on `PATH` for a
  local Nuitka onefile build (`PATH=$PWD/.venv/bin:$PATH scripts/…`).
- Delegation workers are NOT durable and a provider key can be revoked mid-run. Commit early; snapshot
  unfinished work with a clear flag; update this note before shutting down (which is what this file is).
- Container quirks that cost time this session: `pkill -f`/`pgrep -f` inside `bash -lc` matches its own
  shell (kill by PID); the project drive is `noexec`, so binaries must be run from `$HOME`; `python -c`/
  heredoc quoting is fragile — prefer writing a file and running it.

## Full design history
See `docs/04-development-log.md` and `docs/02-plan.md` (with its deviations section).
