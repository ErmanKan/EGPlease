# `tests/ui/test_qt_image.py`

> pytest-qt tests for `pil_to_qimage` and `checkerboard_brush`.

## Where it sits
- **Layer:** tests (Qt)
- **Used by:** pytest.
- **Uses:** `ui/qt_image.py`, `qtbot` (only to ensure a `QApplication` exists, which `QPixmap` needs).

## Public API
| Test | Verifies |
|---|---|
| `test_pil_to_qimage_pixels` | Size, an exact opaque pixel, alpha 128 preserved (not premultiplied), and the QImage still valid after the PIL image is deleted (it owns its buffer). |
| `test_p_mode_and_brush` | A `"P"` image converts; the checkerboard brush has a non-null texture. |

## How it works
Straight pixel reads with `QImage.pixelColor`.

## Invariants & gotchas
- 2 cases.

## Tests
- **Gaps:** brush geometry and colours; large images; modes like `LA`, `I;16`.

## History
- `0137178`.
