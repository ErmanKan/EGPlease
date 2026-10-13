# `tests/core/test_headless.py`

> Pins down the `--edit-spec` grammar case by case and runs one real headless edit, because this is the code a built `.exe` executes in the packaging smoke test (M5).

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest (`scripts/test.sh`, or plain `pytest` on Windows/CI).
- **Uses:** `gif_editor/headless.py` (`parse_spec`, `run_edit_spec`), `core/models.py` (`CropRect`, `EditState`, `OutputSize`), `tests/gifgen.py` (imported as `tests.gifgen`: `make_gif`, `solid_frames`), Pillow (to read the output), pytest's `tmp_path` and `capsys`.

## Public API
| Test | Verifies |
|---|---|
| `spec(text)` | helper: `parse_spec(text, EditState())`, returning only the state. |
| `test_out_is_required` | A spec without `out=` raises `ValueError` "…out=PATH". |
| `test_unknown_key_is_rejected` | `nonsense=1` → `ValueError` "unknown spec key". |
| `test_item_without_equals_is_rejected` | `delete=0,3,…` (the natural mistake: commas in a list) → `ValueError` "expected key=value", not silently ignored. |
| `test_trim_whole_numbers_are_milliseconds` | `trim=0:400` → start 0, duration 400. |
| `test_trim_decimals_are_seconds` | `trim=0.5:1.5` → start 500, duration 1000. |
| `test_trim_without_end_runs_to_the_end` | `trim=200` → start 200, duration `None`. |
| `test_trim_then_duration_overrides` | `trim=0:400,duration=150` → duration 150. |
| `test_delete_is_colon_separated` | `delete=0:3:5` → `{0, 3, 5}`. |
| `test_delete_accepts_empty_value` | `delete=` → empty set. |
| `test_crop_accepts_colons_or_x` | `crop=8:6:40:30` and `crop=8x6x40x30` → `CropRect(8, 6, 40, 30)`. |
| `test_size_speed_fps_and_quality` | `size=32x24,speed=1.5,fps=12,colors=64,dither=0` → the matching fields. |
| `test_items_apply_in_order` | `duration=500,duration=100` → 100 (later items win). |
| `test_values_are_whitespace_and_case_tolerant` | `" TRIM = 0 : 400 , OUT = o.gif "` parses. |
| `test_keys_are_case_insensitive_but_paths_are_not` | `OUT=Out/MyFile.GIF` keeps the path's case. |
| `test_out_path_is_returned` | The returned path is the `out=` value (a string only; nothing is written). |
| `test_bad_number_reports_value_error` | `speed=fast` → `ValueError`. |
| `test_run_edit_spec_writes_a_gif` | 8 frames × 100 ms, 64×48; `trim=0:400,delete=2,crop=8:6:40:30,size=32x24,colors=64` → exit 0, a `RESULT` line with `size=32x24`, `frames=3` and the path; the file is 32×24. |
| `test_run_edit_spec_reports_failure_without_a_traceback` | Missing input → exit 1, output starts with `ERROR `, no `Traceback`, no output file. |
| `test_run_edit_spec_rejects_a_bad_spec` | `out=o.gif,bogus=1` → exit 1, `ERROR ValueError…`. |

**19 test cases** (19 functions, no parametrization).

## How it works
The grammar tests call `parse_spec` directly and compare `EditState` fields, so they are fast and precise. The three run tests write a real GIF with `make_gif` into `tmp_path` and call `run_edit_spec`, capturing its printed line with `capsys`. The "frames=3" expectation is worked out in the test: 400 ms of 100 ms frames keeps frames 0–3, and deleting frame 2 leaves 3.

*Why the grammar is pinned so tightly:* the packaging smoke test passes or fails on what this parser does inside the built binary. A parser bug would make the smoke test pass or fail for the wrong reason, which is exactly the kind of error that is hard to see from CI output.

## Invariants & gotchas
- Core test: no Qt. It imports `tests.gifgen` (package-style) rather than `gifgen`; both work because `tests/` is a package and the repo root is on `sys.path` under pytest's default import mode.
- `test_out_path_is_returned` uses the string `/tmp/x.gif` only as a value; nothing is written there.

## Tests
- **Gaps:** the `--edit-spec` branch of `app.main` (argument handling, exit code 2) and values out of range (e.g. `colors=1`, which `generate`'s validation would reject at run time).

## History
- `a2e41d0` (M5): added; it is what showed that the grammar cannot express the documented `delete=0,3,5` ([dev log, Milestone 5](../../../04-development-log.md#milestone-5-packaging)).
