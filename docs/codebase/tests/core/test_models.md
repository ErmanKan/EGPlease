# `tests/core/test_models.py`

> Unit tests for `core/models.py`: defaults, immutability, field validation, source validation, presets.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/models.py`.

## Public API
| Test | Verifies |
|---|---|
| `test_defaults_are_identity` | `EditState()` has speed 1, no fps/crop/deletes and validates against any source. |
| `test_with_returns_new_and_coerces_deleted` | `with_` returns a new object, leaves the old one unchanged, turns a `set` into a `frozenset`. |
| `test_invalid_fields` (9 params) | speed 0.1 / 5, fps 0 / 60, negative trim start, duration 0, negative deleted index, `OutputSize(0, 10)`, `Quality(1)` → `ValueError`. |
| `test_unknown_field` | Unknown keyword → `TypeError`. |
| `test_validate_against_source` | The crop must fit the canvas; deleted indices must be < frame count. |
| `test_quality_presets` | `Quality.preset("low") == Quality(64, False)`. |

## How it works
Plain asserts; one parametrized table of invalid values.

## Invariants & gotchas
- 14 test cases in total.

## Tests
- **Gaps:** boundary values (speed exactly 0.25/4.0, fps 50, size 8192/8193, colours 2/256); the `high`/`medium` presets; `CropRect` with zero/negative size directly.

## History
- `7a7b418`: written with the model.
