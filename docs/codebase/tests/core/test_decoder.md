# `tests/core/test_decoder.py`

> Tests for `GifSource` on ordinary Pillow-written GIFs: metadata, pixels, caching, limits, thread safety, file-handle release.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/decoder.py`, `tests/gifgen.py` (imported as `tests.gifgen`), `tests/corpus.py` (`normalize_rgba`).

## Public API
| Group | Tests | Verifies |
|---|---|---|
| Metadata | `test_metadata`, `test_loop_absent_is_none`, `test_loop_count`, `test_disposal_recorded` | size, frame count, loop (0 / `None` / 3), raw vs effective delays (`[0,10,50,200,100]` → `(100,100,50,200,100)`), disposal list, no warnings. |
| Pixels | `test_frame_colours`, `test_frames_match_pillow`, `test_transparency_detected` | Colours equal the generator's. Pixels equal Pillow's on opaque full-canvas GIFs, where Pillow and browsers agree (12 frames, disposal 1/2/0). With a transparency index, alpha matches Pillow too. |
| API contract | `test_frame_returns_copy`, `test_out_of_range`, `test_thumbnail_size_and_aspect`, `test_thumbnail_small_image_not_upscaled` | Copies are independent; `IndexError` for -1/5/100; thumbnail 200×100 → 96×48 and 40×20; no upscaling; thumbnail copies independent. |
| Load errors | `test_not_a_gif`, `test_garbage_file`, `test_missing_file`, `test_too_many_frames`, `test_canvas_too_large`, `test_truncated_file_partial_load`, `test_truncated_file_nothing_decodes` | `GifLoadError` for each; truncated files load a prefix with a warning, or fail if nothing decodes. |
| Cache | `test_lru_path_identical_pixels`, `test_zero_budget_still_correct` | With a 4-frame budget and keyframe interval 8, 40 frames accessed backwards then randomly are pixel-identical and the budget is never exceeded; with budget 0 everything still decodes correctly. |
| Concurrency | `test_thread_safety` | 6 threads × 60 random `frame()`/`thumbnail()` calls with a 3-frame budget: no errors, no mismatches. |
| Hygiene | `test_loading_strategy_restored`, `test_close_and_context_manager`, `test_source_file_released_after_open`, `test_frame_after_close_raises` | Pillow globals untouched; `close` idempotent; no fd left open (checked via `/proc/self/fd` where available); the source can be replaced and deleted while open and frames still decode from memory; closed source → `ValueError`. |

## How it works
`_reference(path, i)` uses Pillow's own compositing as the oracle. It is valid **only** for opaque full-canvas frames, as the docstring warns; everything subtler is covered by the corpus tests. `_moving_frames` adds a moving square so that frames differ structurally, not just in colour.

## Invariants & gotchas
- 25 cases. The fd check is skipped silently on Windows (there is no `/proc`). On Windows, the `os.replace` over the open source is itself the real check.

## Tests
- **Gaps:** `Limits.keyframe_interval` behaviour is tested only indirectly here (directly in `test_decoder_corpus.py`); there are no tests for the `ANIMEXTS1.0` loop or for thumbnail cache growth.

## History
- `f7a81ac`, extended in `212b23f` and `5a464d8`.
