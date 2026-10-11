# `tests/ui/test_preview.py`

> pytest-qt tests for `PreviewService`: geometry rendering, asynchronous delivery, staleness, caching, coalescing, and the debounced size estimate.

## Where it sits
- **Layer:** tests
- **Uses:** `ui/inspector/preview.py`, `core/models.py`, `core/pipeline.py` (monkeypatched in the failure tests); fixtures `doc` (8 solid frames, 40×30, 100 ms) and `PALETTE` from `tests/gifgen.py`.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `svc` | fixture | A `PreviewService(doc, debounce_ms=10)`, disposed in teardown. |
| `test_*` | tests | See below. |

## How it works
Solid-colour frames make pixel checks trivial: sampling any pixel tells you which source frame was rendered. The short `debounce_ms` keeps estimate tests fast. Asynchronous results are awaited with `qtbot.waitSignal` / `waitUntil`; `check_params_cb` is used when an earlier queued frame may arrive first.

Some tests replace `preview_mod.run_async` with a function that just records the job, which lets a test run the job at a precise moment. That is how the thread-safety regression test works: it queues a render with crop A, changes the crop to B, *then* runs the job and asserts the image used crop A.

| Group | What is verified |
|---|---|
| Geometry | plain frame is 40×30 with the right colour; crop + size give the output dimensions; a crop change re-renders the current frame |
| Async | `frameReady` carries the index and correct size; stale generations dropped (also after `sourceChanged`); failure → `frameFailed(i, message)` |
| Cache / coalescing | a cache hit starts no worker and returns equal pixels; a burst of requests renders the latest index, not all of them |
| Thread safety | the worker uses the geometry captured at request time |
| Estimate | becomes available after the debounce; `0`/`None` for an empty plan and a closed document; recomputed on edits; not recomputed on frame changes; never raises |
| Lifecycle | `dispose()` is idempotent and leaves no timer running |

## Invariants & gotchas
- **PySide copies a `QImage` that crosses a signal.** Compare images with `==` (contents), never with `is`.
- Turning geometry on immediately requests the *current* frame. A test that then requests another index must wait for that index specifically (`check_params_cb`).
- `qtbot.waitUntil` callbacks must return `bool`/`None`; returning a list raises.
- Run through `scripts/test.sh` (offscreen Qt + project-local libEGL).

## Tests
- This file is the test. Run 3× in a row during verification with no flakes.

## History
- Written by a Milestone 3 worker that was killed before running it; 4 tests were fixed and 1 regression test added during orchestrator verification (commit `e904982`).
