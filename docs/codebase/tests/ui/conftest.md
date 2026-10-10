# `tests/ui/conftest.py`

> pytest fixtures for UI tests: a small solid-colour GIF, and a `Document` with that GIF open.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** every test in `tests/ui/` that asks for `gif_path` or `doc`, including the M2 widget tests.
- **Uses:** `core/decoder.py` (`GifSource`), `ui/document.py` (`Document`), `tests/gifgen.py`.

## Public API
| Fixture | Scope | Value |
|---|---|---|
| `gif_path` | function | `tmp_path / "in.gif"`: 8 solid-colour frames (`gifgen.PALETTE` order), 40×30, 100 ms each, looping. |
| `doc` | function | A `Document` with `gif_path` open; closed on teardown. Depends on `qtbot`, so a `QApplication` exists. |

## How it works
`doc` opens the source synchronously, which is fine for 8 tiny frames, calls `set_source`, yields, then `close()`s.

## Invariants & gotchas
- The fixture opens on the test thread. Real code opens in a worker (`run_async`).
- Requesting `qtbot` creates the `QApplication` before any QObject. Constructing a `Document` without it would fail.
- The module has no docstring (AGENTS.md asks for one on every module; tests are commonly exempted).

## Tests
- n/a (fixtures)

## History
- `0137178`: added with the M2 foundation.
