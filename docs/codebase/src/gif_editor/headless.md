# `src/gif_editor/headless.py`

> The hidden `--edit-spec` mode: one complete edit + Generate with no window, described by a short text spec, printing one `RESULT …` or `ERROR …` line and returning an exit code. It exists so a packaged build can be verified automatically (M5).

## Where it sits
- **Layer:** core-side glue (no Qt; imports only `core`)
- **Used by:** `gif_editor/app.py` (`main` calls `run_edit_spec` when `--edit-spec` is on the command line, **before any Qt import**); [`scripts/smoke_build.py`](../../scripts/smoke_build.md) (steps 1 and 2, through the built binary); `tests/core/test_headless.py`.
- **Uses:** `core/decoder.py` (`GifSource`), `core/models.py` (`EditState`, `CropRect`, `OutputSize`), `core/pipeline.py` (`generate`).

## Public API
```text
GifEditor --edit-spec IN.gif "trim=0:400,delete=2,crop=8:6:40:30,size=32x24,out=OUT.gif"
python -m gif_editor --edit-spec IN.gif "SPEC"          (from source, with PYTHONPATH=src)
```

| Name | Kind | Purpose |
|---|---|---|
| `parse_spec(spec, state) -> (EditState, Path)` | function | Apply every item of `spec` to `state` in order; return the new state and the `out=` path. Raises `ValueError` for a bad item, an unknown key, a bad number, or a missing `out=`. |
| `run_edit_spec(source_path, spec) -> int` | function | Parse, open the GIF, `generate`; print one line; return `0` (written) or `1` (any error). |
| `_ms(value) -> int` | helper | A spec time: a whole number is milliseconds, a number with a `.` is seconds (`"400"` → 400, `"0.5"` → 500). Rounds to the nearest ms. |

### The spec grammar
A spec is **comma-separated `key=value` items**, applied left to right (a later item overrides an earlier one). Keys are case-insensitive and spaces around keys and values are ignored; values (in particular paths) keep their case. Because the comma separates items, **a list inside a value uses colons**.

| Item | Meaning | Becomes |
|---|---|---|
| `trim=START:END` | Keep source time `[START, END)`. Whole numbers are ms, decimals are seconds (`trim=0.5:1.5` = 500–1500 ms). `END` optional: `trim=200` keeps from 200 ms to the end. | `trim_start_ms=START`, `trim_duration_ms=END-START` (or `None`) |
| `duration=MS` | Length kept from the trim start; **integer ms only** (no seconds form). | `trim_duration_ms` |
| `delete=0:3:5` | Delete these source frame indexes. `delete=` (empty) clears the set. | `deleted=frozenset(...)` |
| `crop=X:Y:W:H` or `crop=XxYxWxH` | Crop in source pixels (colons and `x` both work). | `crop=CropRect(...)` |
| `speed=1.5` | Playback speed factor. | `speed` |
| `fps=12` | FPS limit. | `fps` |
| `size=WxH` | Output size in px. | `size=OutputSize(W, H)` |
| `colors=N` | Palette size (2–256). | `quality.colors` |
| `dither=0\|1` | Dithering off/on. | `quality.dither` |
| `out=PATH` | Output file. **Required.** | the returned path |

Output lines:
```text
RESULT frames=3 size=32x24 bytes=1234 ms=300 path=/…/out.gif
ERROR GifLoadError: File not found: missing.gif
```

## How it works
1. **Parse.** Split on `,`, drop empty items, require `=` in each, split at the first `=`, lowercase the key, dispatch. Each branch calls `EditState.with_(...)` (or `dataclasses.replace` on the frozen `Quality`). Values are not range-checked here.
2. **Run.** `run_edit_spec` wraps everything in one `try`: `parse_spec`, `GifSource.open` (as a context manager, so the file is closed), and `pipeline.generate(source, state, out)`. `generate` validates the state against the source (`EditState.validate`), plans with `plan_output`, renders, encodes to a temp file, verifies it and renames it into place: **exactly the GUI's Generate**, so a passing run proves the same code the window uses.
3. **Report.** Any exception becomes one line, `ERROR <ExceptionType>: <message>`, and exit code 1, with no traceback. Success prints the `RESULT` line from the `GenerateResult` and returns 0. Because `generate` writes atomically, a failure leaves no output file.

*Why a text spec and not argparse options:* the whole edit travels as **one argument**, so `app.main` can recognise `--edit-spec` with a plain `in` test and hand over the next two arguments, without an argument parser and without touching the GUI's own command-line handling (the GUI only takes "the first non-flag argument is a file").

*Why `--edit-spec` returns before Qt:* importing PySide6's GUI modules loads `libEGL` and needs a platform plugin. The headless path must work on a machine with no display at all (a CI runner, a server), and a missing Qt plugin must not mask a working core. So `app.main` handles this branch first ([app page](app.md)).

## Invariants & gotchas
- **No Qt imports in this module**, ever: it is imported on the path that must work without Qt (checked for this page: after `app.main([... "--edit-spec" ...])`, no `PySide6` module is loaded).
- **Lists use colons.** `delete=0,3,5` is *not* "delete 0, 3 and 5": the commas split it into `delete=0`, `3`, `5`, and `3` has no `=`, so it is rejected with "expected key=value" (tested). The first docstring documented `delete=0,3,5`, which this grammar cannot express; it was corrected in `a2e41d0`.
- **`trim` end is an end time, `duration` is a length.** `trim=200:600` and `trim=200,duration=400` mean the same.
- **Seconds only with a decimal point.** `trim=1:2` is 1–2 **ms**; write `trim=1.0:2.0` for seconds. `duration` has no seconds form at all.
- `_ms` rounds (`round(float(v) * 1000)`); the first version truncated with `int(...)`, which turns `1.001` s into 1000 ms because `1.001 * 1000` is `1000.9999…` in binary floating point.
- Exit codes: `0` written, `1` any error here, `2` from `app.main` if `--edit-spec` is not followed by two arguments (`usage: GifEditor --edit-spec IN.gif SPEC`).
- It is a hidden developer/packaging feature: not in the GUI, not in `--help` (there is none). The README mentions it briefly.

## Tests
- `tests/core/test_headless.py` ([page](../../tests/core/test_headless.md)), 19 cases: every key, ms vs seconds, the colon list (and the comma mistake rejected), order of application, whitespace/case, path case preserved, errors; a real run writing a 32×24 GIF with 3 frames; a missing file giving `ERROR` and exit 1 with no file written.
- Through a built binary: [`scripts/smoke_build.py`](../../scripts/smoke_build.md) steps 1–2.
- **Gaps:** the `app.main` branch itself (argument extraction, exit code 2) is not unit-tested; it was checked by hand for this page.

## History
- `3531ca0` (M5): added together with the build smoke test.
- `a2e41d0` (M5): docstring corrected (`delete=0:3:5`, not `0,3,5`); `_ms` helper with rounding; seconds/ms rule documented ([dev log, Milestone 5](../../../04-development-log.md#milestone-5-packaging)).
