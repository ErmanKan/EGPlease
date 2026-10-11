# `tests/ui/conftest.py`

> pytest fixtures for UI tests: an autouse fixture that drains the thread pool after every UI test, a small solid-colour GIF, and a `Document` with that GIF open.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** every test in `tests/ui/` (`_drain_workers` is autouse); `gif_path` and `doc` by the tests that ask for them.
- **Uses:** `core/decoder.py` (`GifSource`), `ui/document.py` (`Document`), `tests/gifgen.py`; `QThreadPool`, `QApplication`.

## Public API
| Fixture | Scope | Value |
|---|---|---|
| `_drain_workers` | function, **autouse** | No value. After each UI test, waits for the global thread pool and processes events (see below). |
| `gif_path` | function | `tmp_path / "in.gif"`: 8 solid-colour frames (`gifgen.PALETTE` order), 40×30, 100 ms each, looping. |
| `doc` | function | A `Document` with `gif_path` open; closed on teardown. Depends on `qtbot`, so a `QApplication` exists. |

## How it works
**`_drain_workers`** (M4, `c4b9329`) yields, then in its teardown, up to 10 times: `QThreadPool.globalInstance().waitForDone(10_000)`, `QApplication.processEvents()`, and stop as soon as `activeThreadCount() == 0`. The loop exists because a callback delivered by `processEvents` may start a follow-up task (the preview service starts the next pending render, the filmstrip the next thumbnail batch).

*Why it exists:* without it, a worker started by one test could still be running, and calling back into the GUI thread, while the next test was setting up. That ordering never happens in the app, and during M4 it was one of the suspects for a segmentation fault in a pool thread ([dev log, Milestone 4](../../../04-development-log.md#milestone-4-hardening)). Draining after every test makes each UI test self-contained.

*Why it depends on `qtbot`:* pytest tears fixtures down in reverse order of setup. Requesting `qtbot` makes `_drain_workers` set up **after** `qtbot` and therefore tear down **before** it, i.e. before pytest-qt closes and `deleteLater()`s the test's widgets. So every pending callback runs while the objects it touches still exist ([the deleteLater trap](../../../06-testing.md#the-deletelater-teardown-trap)).

**`doc`** opens the source synchronously, which is fine for 8 tiny frames, calls `set_source`, yields, then `close()`s.

## Invariants & gotchas
- The `doc` fixture opens on the test thread. Real code opens in a worker (`run_async`).
- Requesting `qtbot` creates the `QApplication` before any QObject. Constructing a `Document` without it would fail.
- Because `_drain_workers` is autouse, **every** UI test requests `qtbot` and thus a `QApplication`, even one that only tests pure functions (e.g. `test_messages.py`). That is harmless.
- A test that leaves an endless chain of background tasks would make the teardown wait up to 10 × 10 s; none does.
- The module has no docstring (AGENTS.md asks for one on every module; tests are commonly exempted).

## Tests
- n/a (fixtures)

## History
- `0137178`: `gif_path` and `doc`, added with the M2 foundation.
- `c4b9329` (M4): autouse `_drain_workers`.
