# `tests/ui/test_workers.py`

> pytest-qt tests for `run_async`: the work runs off the GUI thread, results, errors and progress arrive on it, and every relay object is freed afterwards.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** pytest.
- **Uses:** `ui/workers.py`, `qtbot`.

## Public API
| Test | Verifies |
|---|---|
| `test_result_delivered_on_gui_thread` | `fn` ran on a different thread; `on_done(42)` ran on the test (GUI) thread. |
| `test_error_and_progress` | `fn(progress)` reports `(1,2)`, `(2,2)` then raises; `on_progress` got both in order and `on_error` got the message `"boom"`. |
| `test_relays_released_only_after_worker_exit` (M4) | 300 tasks started at once all call back (results `0..299`, any order); after the pool is done, `workers._live` becomes empty, i.e. the delayed release (`exited` flag + `QTimer.singleShot` retry) still frees every relay and nothing leaks. |

## How it works
`qtbot.waitUntil(cond, timeout=...)` spins the Qt event loop until the queued signals are delivered. Without an event loop the callbacks would never run. The third test waits three times: for all 300 callbacks, for the pool (`waitForDone`), then for `_live` to empty (the release may need one more event-loop turn).

## Invariants & gotchas
- 3 cases. Thread identity is compared with `threading.get_ident()`.
- The relay test cannot force the race it guards against (the GUI thread running the callback while the worker is still inside `emit()`); 300 tasks make it likely that the retry path runs at least sometimes. It mainly proves the retry never leaks.

## Tests
- **Gaps:** `pool=` argument; a callback that raises; the `print_errors` switch (traceback printed only when there is no `on_error`).

## History
- `0137178`: first two tests.
- `c4b9329` (M4): `test_relays_released_only_after_worker_exit`.
