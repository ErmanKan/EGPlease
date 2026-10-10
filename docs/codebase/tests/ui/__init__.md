# `tests/ui/__init__.py`

> Empty package marker for the Qt UI tests.

## Where it sits
- **Layer:** tests
- **Used by:** pytest module naming (`tests.ui.test_document`, …).
- **Uses:** nothing.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| (none) | | |

## How it works
UI tests use pytest-qt and need `QT_QPA_PLATFORM=offscreen` (plus the project-local libEGL in the dev container). Run them through `scripts/test.sh`.

## Invariants & gotchas
- See [06-testing.md](../../../06-testing.md#headless-qt-and-the-project-local-libegl).

## Tests
- n/a

## History
- `7a7b418`: scaffold.
