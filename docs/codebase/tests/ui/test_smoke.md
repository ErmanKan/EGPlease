# `tests/ui/test_smoke.py`

> Proves that Qt loads and renders headlessly in this environment.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** pytest.
- **Uses:** PySide6 only (no project code).

## Public API
| Test | Verifies |
|---|---|
| `test_qt_renders_offscreen` | A `QLabel` can be shown, exposed and grabbed into a non-empty image on the `offscreen` platform. |

## How it works
`qtbot.addWidget` registers the widget for cleanup, and `qtbot.waitExposed` waits until Qt considers it visible. `grab()` renders it to a pixmap.

## Invariants & gotchas
- If this fails, every other UI test will fail too. The usual cause is a missing `libEGL.so.1` (run through `scripts/test.sh`) or a missing `QT_QPA_PLATFORM=offscreen`.

## Tests
- **Gaps:** n/a.

## History
- `cc9f0fa`: added with the project-local libEGL.
