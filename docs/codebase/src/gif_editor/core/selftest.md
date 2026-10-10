# `src/gif_editor/core/selftest.py`

> A fast round-trip check that the undocumented Pillow internals the core depends on still behave as expected.

## Where it sits
- **Layer:** core (no Qt)
- **Used by:** `app.py` (`main` calls `run_selftest()` before creating the window; on `SelfTestError` it shows the message and exits with code 1), `tests/core/test_selftest.py`.
- **Uses:** `core/encoder.write_gif`, `core/decoder.GifSource` (imported lazily inside the function).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `SelfTestError(RuntimeError)` | exception | The round trip failed. The message names the installed Pillow version. |
| `run_selftest()` | function | Encode and decode a tiny GIF; raise `SelfTestError` on any mismatch or exception. A few milliseconds. |

## How it works
1. `_frames()` builds two 5×3 `"P"` frames on a 4-colour palette.
   - Frame 0 uses index 3 as its transparency index.
   - Frame 1 is fully opaque (indices mod 3).
   - The expected RGBA of every pixel is computed independently.
2. `write_gif(..., loop=0)` writes them to a temporary directory with delays 7 and 23 cs. This exercises `GifImagePlugin.getdata`.
3. `GifSource.open` decodes the result. This exercises `Image.Image.frombytes(..., "gif", ...)`.
4. It checks the geometry and frame count, the raw delays (70 and 230 ms), and **every pixel** (fully transparent pixels compared as `(0,0,0,0)`).
5. Any exception is wrapped as `SelfTestError("GIF self-test failed with Pillow X (expected a compatible Pillow 12.x…): detail")`.

*Why:* Pillow is pinned (12.3.0), but the decoder and encoder call internals that Pillow does not promise to keep. If a future upgrade changes them, the editor should refuse to run with a clear message instead of silently writing corrupt GIFs.

## Invariants & gotchas
- Imports of `decoder`/`encoder` are inside the `try`, so even an import-time failure becomes `SelfTestError`.
- It writes to the OS temp dir. That dir must be writable.
- `test_selftest_passes_quickly` requires < 0.2 s after warm-up.

## Tests
- `tests/core/test_selftest.py`: speed; the exception type; broken decoder internals (`Image.Image.frombytes` patched); broken encoder internals (`GifImagePlugin.getdata` patched); wrong pixels (`decoder._decode_indices` patched); wrong delays (`encoder.write_gif` patched).
- `tests/ui/test_main_window.py::test_app_main_runs_selftest_and_window` runs the real self-test through `app.main`.
- **Gaps:** the startup failure branch (dialog + exit code 1) is not tested.

## History
- `c0dbd20`: added after the decoder rewrite made us depend on Pillow internals ([dev log](../../../../04-development-log.md#independent-review--fixes)).
