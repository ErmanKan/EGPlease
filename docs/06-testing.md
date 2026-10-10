# 06 — Testing

How the tests are organised, how to run them here and on Windows, how GIF fixtures are generated, and how headless Qt works in the dev container.

Current state: **410 tests, 408 passed, 2 xfailed** (`scripts/test.sh`, about 8 s).

## Running the tests

| Where | Command |
|---|---|
| Linux dev container (always use this) | `scripts/test.sh` runs ruff format check + ruff lint + all tests |
| … a subset | `scripts/test.sh tests/core/test_timeline.py -k fps` (extra args go to pytest) |
| … core only, without Qt | `scripts/test.sh tests/core -p no:pytest-qt` |
| Windows / CI | `QT_QPA_PLATFORM=offscreen python -m pytest -q` (CI sets the variable for the job) |
| Windows PowerShell, locally | `$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python -m pytest -q` |

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml), see [config-files](codebase/config-files.md#githubworkflowsciyml)) runs `ruff check`, `ruff format --check` and `python -m pytest -q` on `windows-latest` with Python 3.13, on every push and PR.

`pyproject.toml` sets `pythonpath = ["src", "tests"]` (no install needed; helper modules import as `corpus`/`gifgen`), `testpaths = ["tests"]` and `addopts = "-ra"`, which prints the reason for every xfail and skip.

## Test layout

```
tests/
├─ conftest.py            session fixtures: corpus, corpus_dir (NO Qt imports)
├─ gifgen.py              simple GIFs via Pillow (make_gif, solid_frames)
├─ corpus.py              raw GIF89a writer + reference compositor + 13 entries
├─ core/                  one file per core module, no Qt
│  ├─ test_models.py        14   EditState validation
│  ├─ test_decoder.py       25   GifSource on ordinary GIFs, cache, threads
│  ├─ test_decoder_corpus.py 56  GifSource vs reference compositor, DoS guards
│  ├─ test_corpus.py        51   the corpus vs raw Pillow (2 strict xfails)
│  ├─ test_timeline.py     112   plan_output tables + random properties
│  ├─ test_render.py        44   crop/resize/palette/quantize
│  ├─ test_encoder.py       62   writer structure, lossless diffs, atomicity
│  ├─ test_pipeline.py      24   end to end, size and flicker
│  └─ test_selftest.py       6   Pillow-internals self-test
└─ ui/                    pytest-qt, needs offscreen Qt
   ├─ conftest.py            gif_path, doc fixtures
   ├─ test_document.py      11   Document + undo
   ├─ test_workers.py        2   run_async threading
   ├─ test_qt_image.py       2   PIL→QImage, checkerboard
   └─ test_smoke.py          1   Qt renders headlessly
```
Numbers are collected test cases (parametrizations counted). The M2 widget tests (`test_settings_panel.py`, `test_canvas.py`, `test_timebar.py`, `test_filmstrip.py`, `test_player.py`, `test_transport.py`) are being added by their owners; see the [INDEX](codebase/INDEX.md).

Each test file has its own page under [`codebase/tests/`](codebase/tests/) listing what each group verifies and the notable gaps.

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
   - **Trust chain:** Debian archive keyring → signed `InRelease` → `Packages` index → package SHA-256. The first three links were verified **once, by hand, when the hash was pinned**. The script re-checks only the pinned SHA-256 on every run, so the pin is the trust anchor.
2. [`scripts/test.sh`](codebase/scripts/test.md) runs the fetch script if the library is missing, prepends `.devlibs/root/usr/lib/x86_64-linux-gnu` to `LD_LIBRARY_PATH`, and sets `QT_QPA_PLATFORM=offscreen`.

The `offscreen` platform plugin renders into memory with no display, so widgets can be shown, grabbed and painted in tests. `tests/ui/test_smoke.py` is the canary: if it fails, the environment is broken, not the code.

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

Widget tests that the M2 workers add typically also use `qtbot.mouseClick`/`mousePress`/`mouseMove`/`keyClick` and `widget.grab()` to check painting.

Rules:
- Keep Qt imports out of `tests/conftest.py` and `tests/core/`, so core tests run with `-p no:pytest-qt`.
- Never block waiting for a worker with `time.sleep`; use `waitUntil` or `waitSignal`, which process events.

## How to add a test

1. **Pick the file.** Core module `core/<m>.py` → `tests/core/test_<m>.py`; widget `ui/…/<w>.py` → `tests/ui/test_<w>.py` (AGENTS.md).
2. **Make a fixture GIF in code:**
   - simple: `make_gif(tmp_path / "a.gif", solid_frames(5), [100, 50, ...], disposal=..., loop=...)`;
   - exotic: build a `corpus.GifSpec` with `FrameSpec`s, write `corpus.encode_gif(spec)[0]`, and compare frames with `corpus.normalize_rgba(...)` against `corpus.compose(spec)`;
   - an existing corpus entry: request the `corpus` fixture and use `corpus["name"]`.
3. **For UI tests**, request `doc` (a `Document` with an 8-frame 40×30 GIF open) and `qtbot`. Construct widgets as `Widget(doc)` and `qtbot.addWidget(w)`. Drive them through `Document` methods or simulated input, and assert on `doc.state` and signals.
4. **Prefer tables and properties.** `pytest.mark.parametrize` for edge-case tables. For algorithms, a seeded random loop that checks invariants against an independent model (see `test_timeline.py::test_random_invariants`).
5. **Known Pillow differences:** add an `xfail(strict=True)` with the exact reason, never a loose xfail.
6. Run `scripts/test.sh`. It must be lint-clean and green. Update the test file's page under `docs/codebase/tests/` in the same commit.
