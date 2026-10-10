# `tests/__init__.py`

> Empty file that makes `tests` a package, so `from tests.gifgen import …` works.

## Where it sits
- **Layer:** tests
- **Used by:** pytest's module naming (`tests.core.test_x`), and `tests/core/test_decoder.py` (`from tests.gifgen import …`).
- **Uses:** nothing.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| (none) | | |

## How it works
The packages `tests`, `tests.core` and `tests.ui` give every test module a unique dotted name, so files with the same basename in different folders (e.g. two `conftest.py`) do not clash.

## Invariants & gotchas
- Helper modules are also importable top-level (`import corpus`, `import gifgen`) because `pyproject.toml` puts `tests` on `pythonpath`.

## Tests
- n/a

## History
- `7a7b418`: scaffold.
