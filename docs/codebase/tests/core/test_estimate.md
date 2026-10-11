# `tests/core/test_estimate.py`

> Tests for the output size estimate (`pipeline.estimate_size`) and for the file-free encoder entry point it uses (`encoder.write_stream`).

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest (`scripts/test.sh`, or plain `pytest` on Windows/CI; no Qt needed).
- **Uses:** `core/pipeline.py` (`estimate_size`, `generate`, `plan`, `summarize`), `core/encoder.py` (`write_stream`, `read_back`), `core/decoder.py` (`GifSource`), `core/models.py` (`EditState`, `CropRect`, `OutputSize`, `Quality`), `tests/gifgen.py` (`make_gif`), pytest's `tmp_path`.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `_noisy_gif(path, n=20, size=(120, 90))` | helper | Writes an `n`-frame GIF (50 ms per frame) whose rows are a colour gradient that shifts with the frame number, plus a white ellipse moving 3 px per frame. Every frame differs from the previous one, so the difference frames are not trivially empty, and the gradient forces real quantisation. |
| `test_estimate_close_to_real[dither=True/False]` | test (2 cases) | Estimate vs the real `generate` size for 128 colours, with and without dithering: `0.5 × real ≤ estimate ≤ 2.0 × real`. |
| `test_estimate_respects_edits` | test | Edits move the estimate the right way: a 30×30 crop resized to 20×20 at 8 colours is smaller than the unedited estimate; trimming to 0.5 s is smaller; deleting every frame gives exactly `0` (and `summarize` agrees: 0 frames). |
| `test_estimate_is_fast_and_matches_generate` | test | A 60-frame 200×150 GIF: one estimate takes under 1.5 s, and lands within `0.4 × … 1.6 ×` of the real size. |
| `test_estimate_renders_only_its_sample` | test | Counts `render_output_frame` calls on a 200-frame GIF: at most 16 palette samples + 5 run frames, so the cost does not grow with the GIF's length. |
| `test_estimate_never_writes_files` | test | The directory listing is unchanged after an estimate: it encodes in memory only. |
| `test_write_stream_writes_to_a_buffer` | test | `write_stream` into a `BytesIO` returns the frame count (3); the bytes, saved and read back, are 3 frames of 100 ms; zero frames raise `ValueError`. |

7 collected cases (6 functions, one parametrized twice).

## How it works
Each test builds its GIF in `tmp_path` with `make_gif` (AGENTS.md: no binary fixtures in the repo), opens it with `GifSource.open` in a `with` block, and calls `estimate_size(source, state, plan(source.meta, state))`, which is exactly how `PreviewService` calls it.

The accuracy bounds are deliberately **wide** (×0.5–×2, ×0.4–×1.6). The estimate is shown with a "≈" in the UI and only has to give the right order of magnitude. A tight bound would make the test fragile against harmless changes in quantisation or LZW. The bounds still catch the bug that motivated the current algorithm: the first version, which measured frames one at a time, overestimated a static-background GIF by 3.4× (see [pipeline page](../../src/gif_editor/core/pipeline.md#estimate_size-and-_encoded_size)).

The timing test uses `time.perf_counter()` around one call. Its 1.5 s limit is generous on purpose so the test does not flake on a slow CI runner; the typical cost is 4–80 ms.

## Invariants & gotchas
- `test_estimate_respects_edits` compares estimates with each other, not with real files, so it checks direction only.
- The "never writes files" test only checks `tmp_path`. It relies on `estimate_size` taking no output path at all; the real guarantee is that `_encoded_size` writes to a `BytesIO`.
- `read_back` returns delays in **milliseconds**, so 10 cs frames read back as `100`.

## Tests
- This file is the test.
- **Gaps:** no test pins the measured accuracy on realistic content (photo-like, flat, cropped long GIFs); those numbers were measured by hand during M3 (see the [dev log](../../../04-development-log.md#milestone-3-crop-and-live-preview)). No test of a source with transparency, or of the contiguous-run choice itself (e.g. a GIF whose middle differs from its ends, where the estimate can be low).

## History
- `b9021ca` (M3): written together with `pipeline.estimate_size` and `encoder.write_stream`.
