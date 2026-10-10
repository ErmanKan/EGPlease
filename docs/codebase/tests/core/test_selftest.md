# `tests/core/test_selftest.py`

> Tests that `run_selftest` passes quickly on the pinned Pillow, and catches each kind of breakage in the internals it guards.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/selftest.py`, and monkeypatches `core/decoder.py`, `core/encoder.py`, Pillow.

## Public API
| Test | Verifies |
|---|---|
| `test_selftest_passes_quickly` | Passes; the second run takes < 0.2 s. |
| `test_selftest_error_is_runtime_error` | `SelfTestError` subclasses `RuntimeError`. |
| `test_decoder_internals_broken` | `Image.Image.frombytes` raising → `SelfTestError` naming the Pillow version and the cause. |
| `test_encoder_internals_broken` | `GifImagePlugin.getdata` raising → `SelfTestError`. |
| `test_wrong_pixels_detected` | Corrupted indices from `decoder._decode_indices` → "frame 0 pixels differ". |
| `test_wrong_delays_detected` | Delays off by one from `encoder.write_gif` → "delays". |

## How it works
Each failure mode is simulated with `monkeypatch`. `run_selftest` imports `GifSource`/`write_gif` *inside* the function, so patching the module attributes takes effect.

## Invariants & gotchas
- 6 cases.

## Tests
- **Gaps:** a wrong geometry/frame count path; a failure to create the temp dir.

## History
- `c0dbd20`.
