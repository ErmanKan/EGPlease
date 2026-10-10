# `tests/ui/test_workers.py`

> pytest-qt tests for `run_async`: the work runs off the GUI thread, and results, errors and progress arrive on it.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** pytest.
- **Uses:** `ui/workers.py`, `qtbot`.

## Public API
| Test | Verifies |
|---|---|
| `test_result_delivered_on_gui_thread` | `fn` ran on a different thread; `on_done(42)` ran on the test (GUI) thread. |
| `test_error_and_progress` | `fn(progress)` reports `(1,2)`, `(2,2)` then raises; `on_progress` got both in order and `on_error` got the message `"boom"`. |

## How it works
`qtbot.waitUntil(cond, timeout=3000)` spins the Qt event loop until the queued signals are delivered. Without an event loop the callbacks would never run.

## Invariants & gotchas
- 2 cases. Thread identity is compared with `threading.get_ident()`.

## Tests
- **Gaps:** `pool=` argument; relay release; a callback that raises; many concurrent tasks.

## History
- `0137178`.
