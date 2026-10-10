# `tests/core/__init__.py`

> Empty package marker for the core (Qt-free) tests.

## Where it sits
- **Layer:** tests
- **Used by:** pytest module naming (`tests.core.test_decoder`, …).
- **Uses:** nothing.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| (none) | | |

## How it works
Every core module `core/<m>.py` has `tests/core/test_<m>.py` (AGENTS.md). In addition there are two corpus test files: `test_corpus.py` (the corpus vs raw Pillow) and `test_decoder_corpus.py` (the corpus vs our decoder).

## Invariants & gotchas
- Nothing under `tests/core/` may import Qt.

## Tests
- n/a

## History
- `7a7b418`: scaffold.
