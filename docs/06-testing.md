# 06 — Testing

How the tests are organised, how to run them here and on Windows, how GIF fixtures are generated, how headless Qt works in the dev container, the manual hardening tools (HiDPI pass, decoder fuzzer, stress probe, soak runs), and the packaging checks (flag check, icon check, build + smoke test).

Current state (Milestone 5, in progress): **711 tests, 709 passed, 2 xfailed** (`scripts/test.sh`, about 37–40 s); M5 added 30 core tests (`test_headless.py` 19, `test_resources.py` 5, `test_check_build_flags.py` 6). The 278 UI tests also pass at 150 % and 200 % scaling (`scripts/test-hidpi.sh`, measured at the end of M4). Soak result (M4): see [the soak section](#soak-test-repeated-full-runs). Packaging checks: see [below](#packaging-checks-m5).

## Running the tests

| Where | Command |
|---|---|
| Linux dev container (always use this) | `scripts/test.sh` runs ruff format check + ruff lint + all tests |
| … a subset | `scripts/test.sh tests/core/test_timeline.py -k fps` (extra args go to pytest) |
| … core only, without Qt | `scripts/test.sh tests/core -p no:pytest-qt` |
| … the UI tests at 150 % and 200 % (HiDPI pass) | `scripts/test-hidpi.sh` (extra args go to pytest, e.g. `-k canvas`) |
| … one scale by hand | `QT_SCALE_FACTOR=2 scripts/test.sh tests/ui` |
| Windows / CI | `QT_QPA_PLATFORM=offscreen python -m pytest -q` (CI sets the variable for the job) |
| Windows PowerShell, locally | `$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python -m pytest -q` |

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml), see [config-files](codebase/config-files.md#githubworkflowsciyml)) runs `ruff check`, `ruff format --check` and `python -m pytest -q` on `windows-latest` with Python 3.13, on every push and PR.

Manual tools (not part of the suite; run them after changing the decoder, the canvas, the preview service or the workers):

| Tool | Command (repo root, in the container) | Writes to |
|---|---|---|
| Decoder fuzzer ([page](codebase/scripts/fuzz_decoder.md)) | `PYTHONPATH=src:tests .venv/bin/python scripts/fuzz_decoder.py [cases-per-file=200] [seed=1]` | `out/fuzz/` |
| Stress probe ([page](codebase/scripts/stress_probe.md)) | `LD_LIBRARY_PATH=$PWD/.devlibs/root/usr/lib/x86_64-linux-gnu QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tests .venv/bin/python scripts/stress_probe.py` (prefix `PROBE_ONLY=huge` for one case) | `out/stress/` |
| Soak (repeated full runs) | see [below](#soak-test-repeated-full-runs) | `out/` |

The fuzzer exits 1 if any damaged file raised something other than `GifLoadError` or hung for 10 s (it keeps such files as `out/fuzz/bug-*.gif` / `hang-*.gif`). The stress probe prints the worst GUI-thread stall per phase; compare before/after on the same machine.

`pyproject.toml` sets `pythonpath = ["src", "tests"]` (no install needed; helper modules import as `corpus`/`gifgen`), `testpaths = ["tests"]` and `addopts = "-ra"`, which prints the reason for every xfail and skip.

## Packaging checks (M5)

Three checks protect the `.exe` build. The first two are fast and run in the container; the build itself is slow (about 20 minutes from scratch in the container, mostly Nuitka's `ldd`-based dependency scan; see the [dev log](04-development-log.md#two-wrong-claims-about-why-the-build-was-slow)).

| Check | Command (repo root) | What it proves | Page |
|---|---|---|---|
| Nuitka flags | `.venv/bin/python scripts/check_build_flags.py` | Every flag `scripts/build.py` passes is a real Nuitka 4.3 option, for the Linux **and** the Windows command line; `--cache-dir`/`--no-console` never come back; the version reaches the file metadata. ~1 s. **Run it after every change to `build.py`.** | [check_build_flags](codebase/scripts/check_build_flags.md) |
| Icons current | `.venv/bin/python scripts/make_icon.py --check` | The committed icon PNGs have exactly the pixels `make_icon.py` draws now, and `icon.ico` has the 7 sizes. Compares pixels, not bytes (zlib output differs per OS). | [make_icon](codebase/scripts/make_icon.md) |
| Build + smoke test | `.venv/bin/python scripts/build.py`, then `.venv/bin/python scripts/smoke_build.py [binary]` | The binary fails cleanly on a missing file (exit 1, no traceback), performs a real edit and writes a 32×24 GIF (exit 0), and opens a GIF in its real window offscreen and quits (`--smoke-gui`, exit 0). | [build](codebase/scripts/build.md), [smoke_build](codebase/scripts/smoke_build.md) |

The unit tests `test_check_build_flags.py` (the checker catches each historical mistake), `test_headless.py` (the `--edit-spec` grammar the smoke test relies on) and `test_resources.py` (the icon is found) run in the normal suite.

**On Windows / in CI** the build workflow [`build-exe.yml`](codebase/config-files.md#githubworkflowsbuild-exeyml) runs, in order: lint + tests, `make_icon.py --check`, `check_build_flags.py`, `build.py`, `smoke_build.py out/dist/GifEditor.exe`, then uploads the `.exe`. Locally on Windows:
```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt -r packaging/build-requirements.txt
.venv\Scripts\python scripts\check_build_flags.py
.venv\Scripts\python scripts\build.py
.venv\Scripts\python scripts\smoke_build.py out\dist\GifEditor.exe
```

**In the Linux container** (proves the recipe with a Linux binary; it cannot make a `.exe`):
```bash
PATH=$PWD/.venv/bin:$PATH .venv/bin/python scripts/build.py      # patchelf comes from the venv
mkdir -p "$HOME/smoke-tmp"
TMPDIR="$HOME/smoke-tmp" .venv/bin/python scripts/smoke_build.py out/dist/GifEditor
```
*The `TMPDIR` note:* a onefile binary unpacks itself into `TMPDIR` and executes the unpacked program. In this container `/tmp`, `/dev/shm`, `/var/tmp` and the project drive are mounted `noexec`, so with the default `TMPDIR` the binary cannot start. Point `TMPDIR` at an executable folder under `$HOME` (outside the repo, so delete it when done). This is a container quirk; Windows and CI need nothing. Do not start a build while another one is running in `out/`, and never delete `out/dist/` during a build.

LINUX BINARY SMOKE RESULT: pending (filled in by the orchestrator)

**Not covered by any automated check yet:** the M5 exit criterion, i.e. the `.exe` running on a clean Windows 11 machine without Python, from any folder and from a USB stick. That is a manual test on a VM.

### A timing test that is flaky under load
`tests/core/test_timeline.py::test_performance_10k_frames` asserts that planning 10,000 frames takes under **50 ms** of wall-clock time. In one full run made *during* a Nuitka build (load average 4.7 instead of about 1.7) it failed; alone, and in every other run, it passes. If it fails, check whether the machine (or CI runner) was busy before suspecting `core/timeline.py`. Avoid running the suite while a build is running.

## Test layout

```
tests/
├─ conftest.py            session fixtures: corpus, corpus_dir (NO Qt imports)
├─ gifgen.py              simple GIFs via Pillow (make_gif, solid_frames)
├─ corpus.py              raw GIF89a writer + reference compositor + 13 entries
├─ core/                  one file per core module, no Qt
│  ├─ test_models.py        14   EditState validation
│  ├─ test_decoder.py       27   GifSource on ordinary GIFs, cache, threads, frames_to_decode
│  ├─ test_decoder_corpus.py 56  GifSource vs reference compositor, DoS guards
│  ├─ test_corpus.py        51   the corpus vs raw Pillow (2 strict xfails)
│  ├─ test_timeline.py     112   plan_output tables + random properties
│  ├─ test_render.py        44   crop/resize/palette/quantize
│  ├─ test_encoder.py       62   writer structure, lossless diffs, atomicity
│  ├─ test_pipeline.py      24   end to end, size and flicker
│  ├─ test_estimate.py       7   size estimate, write_stream
│  ├─ test_selftest.py       6   Pillow-internals self-test
│  ├─ test_headless.py      19   --edit-spec grammar + a real headless run      ┐
│  ├─ test_resources.py      5   icon/resource lookup, onefile env var        │ M5 packaging
│  └─ test_check_build_flags.py 6 Nuitka flags valid; historical mistakes caught ┘
└─ ui/                    pytest-qt, needs offscreen Qt
   ├─ conftest.py            _drain_workers (autouse), gif_path, doc
   ├─ test_document.py      11   Document + undo                  ┐
   ├─ test_workers.py        3   run_async threading, relay life  │ foundation
   ├─ test_qt_image.py       2   PIL→QImage, checkerboard         │
   ├─ test_smoke.py          2   Qt headless; self-test dialog    │
   ├─ test_messages.py      22   error → plain explanation        ┘
   ├─ test_settings_panel.py 19  controls → EditState, tooltips   ┐
   ├─ test_canvas.py        16   zoom, overlay, pan, async frames │
   ├─ test_timebar.py       19   seek, trim handles, snapping     │ one file per widget
   ├─ test_filmstrip.py     16   thumbnails, selection, keys      │
   ├─ test_player.py        22   timing, looping, preview         │
   ├─ test_transport.py     10   buttons, label, bindings         │
   ├─ test_crop_panel.py    32   crop fields, aspect, merge keys  │
   ├─ test_crop_item.py     35   canvas crop drags, handles       │
   ├─ test_preview.py       27   preview frames, size estimate    ┘
   ├─ test_main_window.py   24   whole-window integration, M4 errors/close/fit/Space
   └─ test_m3_integration.py 18  M3 wiring: geometry preview, crop tool, real drag
```
Numbers are collected test cases (parametrizations counted).

Each test file has its own page under [`codebase/tests/`](codebase/tests/) listing what each group verifies and the notable gaps.

## The UI test layer

UI tests come in three tiers. All of them use pytest-qt and run on the `offscreen` platform.

| Tier | Files | Builds | Checks |
|---|---|---|---|
| Foundation | `test_document.py`, `test_workers.py`, `test_qt_image.py`, `test_smoke.py`, `test_messages.py` | `Document`, `run_async`, helpers | the contract every widget relies on (undo, merging, signals, cross-thread delivery) |
| Widget | `test_settings_panel.py`, `test_canvas.py`, `test_timebar.py`, `test_filmstrip.py`, `test_player.py`, `test_transport.py`, `test_crop_panel.py`, `test_crop_item.py`, `test_preview.py` | **one widget** + the `doc` fixture | the widget's input → `Document` call, and `Document` signal → what the widget shows; empty/closed states; painting doesn't crash |
| Integration | `test_main_window.py`, `test_m3_integration.py` | the whole `MainWindow` (or a widget + `PreviewService`) | wiring: actions and a real shortcut, async open/drop, Generate + cancel end to end, PNG export, `app.main`; M3: geometry preview, Size line, crop tool rules, a real canvas drag, Generate applies the crop |

**Widget tests** construct the widget alone with `Widget(doc)` (the transport also gets a `Player`). Because widgets talk only to `Document`, no other widget is needed. They drive input with simulated mouse/keys, or hand-built `QMouseEvent`s when modifiers matter (e.g. Alt on the timebar). They assert on `doc.state`, `doc.current_index` and signals, and they check that undo moves the widget back. Timing-sensitive code is tested without real time: `Player(clock=fake, time_scale=...)` injects a fake monotonic clock.

**Integration tests** use a shown `MainWindow` (fixture `win`) and the non-dialog entry points (`open_file`, `generate_to`, `save_frame_to`). Errors are asserted on `win.last_error` (headline + body) and `win.last_dialog` (icon, `detailedText()`), which works because the window shows errors with the non-blocking `QMessageBox.open()`. A `QMessageBox.exec()` or a file dialog would block a headless test forever. Background work is awaited with `qtbot.waitUntil(lambda: not win.is_busy)`. Generate is real: the test reads the output back with `encoder.read_back`. Details: [test_main_window page](codebase/tests/ui/test_main_window.md).

### The drain fixture: no background task outlives its test
`tests/ui/conftest.py` has an **autouse** fixture, `_drain_workers`, that runs after every UI test: it waits for `QThreadPool.globalInstance()` (10 s) and processes events, up to 10 times, until no pool thread is active (a delivered callback may start a follow-up task). It requests `qtbot`, so pytest tears it down **before** `qtbot` closes the test's widgets: every pending callback runs while its objects still exist.

*Why (M4):* without it a worker started by one test could still be running and calling back while the next test set up, an ordering that never happens in the app. It was one of three changes made after a rare crash and a rare hang in full-suite runs ([dev log](04-development-log.md#stability-one-crash-and-one-hang-in-the-test-suite-c4b9329-9ab961f)). You do not need to call anything yourself; just never start background work in a way that bypasses `run_async` and the global pool.

### The deleteLater teardown trap
pytest-qt's teardown hook `close()`s and `deleteLater()`s every widget registered with `qtbot.addWidget` **before** your fixture's code after `yield` runs. Anything there that spins the event loop (`qtbot.waitUntil`, `waitSignal`, `processEvents`) lets Qt process the `DeferredDelete`, and the widget (and children such as the filmstrip's model) is destroyed. A worker that finishes after that delivers its result to nothing.

This bit the filmstrip: its fixture polled `w.frame_model.is_loading` after `yield`, the model died mid-poll, the last thumbnail batch was never delivered, and the test flaked with a timeout. The fix:
```python
@pytest.fixture
def strip(qtbot, doc):
    w = Filmstrip(doc)
    qtbot.addWidget(w)
    w.show()
    yield w
    # Widget already closed + deleteLater()ed: don't touch it. Just let pool jobs finish
    # before the doc fixture closes the source.
    QThreadPool.globalInstance().waitForDone(5000)
```
Rules:
- In teardown, never touch a widget registered with `addWidget`. Wait for the **thread pool** (`QThreadPool.globalInstance().waitForDone(ms)`), not for the widget.
- Better still, finish background work **inside the test**. The `win` fixture's teardown `waitUntil(lambda: not w.is_busy)` only reads plain Python flags, and every test already waits for its open/Generate to complete before returning.
- Fixture order matters: `doc` closes the source in its own teardown, so workers must be finished first, or they hit `ValueError("GifSource is closed")` (which the filmstrip tolerates and records as a failed thumbnail).

## Temp files: only under `out/`
Project rule: nothing is written outside the repo, so tests and tools never use the container's `/tmp`.
- `scripts/test.sh` passes **`--basetemp=out/pytest-tmp/run-<pid>`**, so `tmp_path` lives in the gitignored `out/`. Each run gets **its own folder**, because pytest empties `--basetemp` when it starts: with one shared folder, a second run wiped the files of a run in progress (40 failures in one parallel run). Folders of runs that have exited are removed when the next run starts. Several test runs (two terminals, a soak loop) can therefore run at the same time.
- It also passes **`--capture=sys`**. pytest's default `fd` capture redirects the output file descriptors into temp files that are deleted while still open; the project lives on a Windows `F:` drive mounted into the container, and that mount rejects such files. So `TMPDIR` cannot point into the project, and output is captured in memory instead (C-level output, e.g. Qt warnings, is then not captured).
- The cost: the suite takes about **38–40 s** instead of about 15 s, because temp files are on the mounted drive.
- The fuzzer and the stress probe write to `out/fuzz/` and `out/stress/`. Throwaway probes must also write under `out/`, never `/tmp`.
- Plain `python -m pytest` (as on Windows/CI) uses the system temp folder; that is fine on Windows, where the rule is about this container.

## Soak test (repeated full runs)
A rare failure (M4 saw one crash and one hang in about 20 full runs) needs many runs to show up. The procedure used at the end of M4:
1. **Freeze the code** in a git worktree under `out/`, so you can keep working in the main checkout while the soak runs and every run tests the same commit:
   ```bash
   git worktree add out/soak-wt HEAD
   ln -s "$PWD/.venv" out/soak-wt/.venv          # reuse the venv and the project-local libEGL
   ln -s "$PWD/.devlibs" out/soak-wt/.devlibs
   ```
2. **Loop with a per-run timeout**, so a hang shows up as exit code **124** instead of blocking the loop forever:
   ```bash
   cd out/soak-wt
   for i in $(seq 1 30); do
     timeout 300 scripts/test.sh > "../soak-$i.log" 2>&1
     echo "run $i: exit $?"
   done
   ```
   Exit 0 = passed, 1 = test failures, 124 = timed out (a hang), 139 = segmentation fault.
3. For a hang, get the stack of every thread before the timeout hits: `kill -ABRT <pytest pid>`; pytest's built-in `faulthandler` prints all thread stacks to the log.
4. **Don't disturb it:** do not delete or modify anything in the worktree while it runs, and stop it by PID, not with `pkill -f <pattern>` (a pattern can match your own shell; that happened in M4). When it is done: `git worktree remove out/soak-wt`.

**30 of 30 runs exited 0** (679 passed + 2 xfailed each, 36-49 s per run); no exit 1, no 124 (timeout/hang), no 139 (segmentation fault). Root cause of the two pre-fix failures remains unidentified, but nothing reproduced in 30 consecutive full runs on the fixed code (plus the 18 runs during development: 48 clean runs in total since `9ab961f`/`c4b9329`).

## gifgen vs the corpus

No binary fixtures are committed (AGENTS.md). Every test GIF is generated in code, in one of two ways:

| | `tests/gifgen.py` | `tests/corpus.py` |
|---|---|---|
| Writes with | Pillow `save_all` | its own byte-level GIF89a writer (`encode_gif`, literal-only `lzw_encode`) |
| Can express | full frames, delays, loop, one disposal per frame, a transparency index | **anything**: partial frames at offsets, frames bigger than or off the canvas, local tables only, no global table, interlacing, 0/1 cs delays, no GCE, no loop block, no trailer, truncation, out-of-table indices, exact LZW data to corrupt |
| Expected result from | the test's own knowledge (solid colours), or Pillow for opaque full-canvas frames | `compose()`, an independent pure-Python **reference compositor** with browser semantics |
| Use for | metadata, caching, pipeline, UI fixtures | decoder correctness on edge cases |

The corpus has 13 named entries (10 valid, plus `truncated`, `not_a_gif`, `large_canvas_header`), written once per session by the `corpus` fixture. Tests also build ad-hoc `GifSpec`s (e.g. a random 60-frame mix in `test_decoder_corpus.py`). Details: [corpus page](codebase/tests/corpus.md).

**Two-sided validation:**
- `test_corpus.py` checks the *corpus* against raw Pillow, so a bug in our writer or compositor shows up.
- `test_decoder_corpus.py` checks *our decoder* against the corpus.

Where Pillow and browsers genuinely disagree, the first file has an xfail and the second file asserts the browser result.

## The xfails and why

| Test | Reason |
|---|---|
| `test_corpus.py::test_valid_entry_pixels[disposal_background-2]` | Frame 0 has no transparency index, so Pillow composites on an RGB canvas. Disposal 2 then fills the frame-1 rect with the **opaque** background colour (index 3, yellow) instead of clearing it to transparent. |
| `test_corpus.py::test_valid_entry_pixels[disposal_background-3]` | Same cause; the frame-2 rect (which has transparent index 6) is filled with `palette[6]` (white). |

Both are `xfail(strict=True)`: if Pillow ever fixes this, the tests XPASS, which counts as a failure, so we notice and can reconsider. Our decoder's correct behaviour on the same frames is asserted in `test_decoder_corpus.py::test_disposal_background_is_browser_like`. This finding is why the decoder has its own compositor ([primer: disposal](05-gif-primer.md#disposal-methods)).

There are no skips in the container. `test_decoder_corpus.py::test_descriptor_bomb_peak_rss_in_subprocess` is skipped on Windows (it uses the POSIX `resource` module).

## Headless Qt and the project-local libEGL

PySide6's QtGui links against `libEGL.so.1`. The Linux dev container does not have it, so `import PySide6.QtGui` fails, and no system packages may be installed. The fix, approved by the user:

1. [`scripts/fetch-devlibs.sh`](codebase/scripts/fetch-devlibs.md) downloads Debian's `libegl1_1.7.0-1+b2_amd64.deb` into `.devlibs/debs/`, **verifies its SHA-256** against the pinned value, and unpacks it with `dpkg-deb -x` into `.devlibs/root/`. No maintainer scripts run, nothing outside the repo changes, and `.devlibs/` is gitignored.
   - **Trust chain:** Debian archive keyring → signed `InRelease` → `Packages` index → package SHA-256. The script checks **only the pinned SHA-256**, on every run, so the pin is the trust anchor. The rest of the chain was verified **once, by hand, when the hash was pinned**: `sqv --message` on `InRelease` with the Debian archive keyring, then the `Packages.xz` hash against the authenticated `Release`, then the package's SHA-256 from that index. The commands are on the [fetch-devlibs page](codebase/scripts/fetch-devlibs.md#trust-chain).
2. [`scripts/test.sh`](codebase/scripts/test.md) runs the fetch script if the library is missing, prepends `.devlibs/root/usr/lib/x86_64-linux-gnu` to `LD_LIBRARY_PATH`, and sets `QT_QPA_PLATFORM=offscreen`.

The `offscreen` platform plugin renders into memory with no display, so widgets can be shown, grabbed and painted in tests. `tests/ui/test_smoke.py` is the canary: if it fails, the environment is broken, not the code.

`scripts/test.sh` actually sets `QT_QPA_PLATFORM=offscreen:configfile=scripts/offscreen-screen.json`: a virtual **3840×2160** screen instead of the default 800×600. At `QT_SCALE_FACTOR=2` the default screen is only 400×400 logical pixels, smaller than the test windows, and Qt does not deliver mouse events outside the screen (one timebar test failed for that reason only). See [config-files](codebase/config-files.md#scriptsoffscreen-screenjson).

On Windows (CI, or the user's machine) none of this is needed. Qt wheels bring their own DLLs; only `QT_QPA_PLATFORM=offscreen` is set, to avoid windows popping up.

## pytest-qt basics used here

pytest-qt provides the `qtbot` fixture. Requesting it ensures a `QApplication` exists. Any test that creates a QObject, QPixmap or widget must request `qtbot`, directly or via a fixture like `doc`.

| Tool | Used for | Example |
|---|---|---|
| `qtbot.addWidget(w)` | close/delete the widget after the test | `test_smoke.py` |
| `qtbot.waitExposed(w)` | wait until a shown widget is actually exposed | `test_smoke.py` |
| `with qtbot.waitSignal(sig) as blocker:` | assert a signal fires inside the block; `blocker.args` are its arguments | `test_document.py::test_current_index_clamped_and_signalled` |
| `qtbot.waitUntil(cond, timeout=ms)` | spin the event loop until `cond()` is true; needed for queued cross-thread signals | `test_workers.py` |
| Direct `signal.connect(list.append)` | record emissions synchronously (same-thread signals are delivered immediately) | `test_document.py::test_apply_undo_redo` |

The widget tests also use `qtbot.mouseClick`/`mousePress`/`mouseMove`/`keyClick` and `widget.grab()` to check painting.

Rules:
- Keep Qt imports out of `tests/conftest.py` and `tests/core/`, so core tests run with `-p no:pytest-qt`.
- Never block waiting for a worker with `time.sleep`; use `waitUntil` or `waitSignal`, which process events.

## How to add a test

1. **Pick the file.** Core module `core/<m>.py` → `tests/core/test_<m>.py`; widget `ui/…/<w>.py` → `tests/ui/test_<w>.py` (AGENTS.md).
2. **Make a fixture GIF in code:**
   - simple: `make_gif(tmp_path / "a.gif", solid_frames(5), [100, 50, ...], disposal=..., loop=...)`;
   - exotic: build a `corpus.GifSpec` with `FrameSpec`s, write `corpus.encode_gif(spec)[0]`, and compare frames with `corpus.normalize_rgba(...)` against `corpus.compose(spec)`;
   - an existing corpus entry: request the `corpus` fixture and use `corpus["name"]`.
3. **For UI tests**, request `doc` (a `Document` with an 8-frame 40×30 GIF open) and `qtbot`. Construct widgets as `Widget(doc)` and `qtbot.addWidget(w)`. Drive them through `Document` methods or simulated input, and assert on `doc.state` and signals. If the widget starts background work, wait for the pool in teardown (see [the deleteLater trap](#the-deletelater-teardown-trap)). For a behaviour that needs several widgets or a menu action, add a case to `test_main_window.py`.
4. **Prefer tables and properties.** `pytest.mark.parametrize` for edge-case tables. For algorithms, a seeded random loop that checks invariants against an independent model (see `test_timeline.py::test_random_invariants`).
5. **Known Pillow differences:** add an `xfail(strict=True)` with the exact reason, never a loose xfail.
6. Run `scripts/test.sh`. It must be lint-clean and green. If you touched anything that maps screen to image pixels (canvas, crop item, timebar, filmstrip, layout), also run `scripts/test-hidpi.sh`. Update the test file's page under `docs/codebase/tests/` in the same commit.
