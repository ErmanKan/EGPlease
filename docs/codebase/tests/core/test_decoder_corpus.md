# `tests/core/test_decoder_corpus.py`

> Checks `GifSource` against the generated corpus and the browser-semantics reference compositor, plus generated edge cases and memory-DoS guards.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/decoder.py`, `tests/corpus.py`, the `corpus` fixture from `tests/conftest.py`.

## Public API
| Group | Tests | Verifies |
|---|---|---|
| Corpus entries | `test_valid_entry_matches_reference` (×10), `test_valid_entry_backward_with_tiny_cache` (×10) | Metadata, raw and effective delays, loop, `has_transparency`, no warnings, and every frame equal to `compose()`. The same again when scrubbing backwards and randomly with a 2-frame budget and keyframe interval 2. |
| Pillow's bug, fixed | `test_disposal_background_is_browser_like` | The exact frames Pillow gets wrong (see `test_corpus.py` xfails) come out right here: rects cleared to **transparent**. |
| Bad files | `test_truncated_entry`, `test_not_a_gif_entry`, `test_large_canvas_header_entry`, `test_bomb_guard_follows_max_image_pixels` | 2 of 3 frames + one "truncated" warning; "Not a GIF"; "too large" even with a huge side limit; the guard follows `Image.MAX_IMAGE_PIXELS` (500 → reject, `None` → accept). |
| Generated edge cases | `test_mixed_random_access_matches_reference` | 60 random partial frames (all disposals, changing transparency, local palettes, interlacing, off-canvas rects, 0-3 cs delays), checked with a full cache, a 3-frame budget (checkpoints squeezed, interval doubled), and budget 0. |
| | `test_checkpoints_spread_when_budget_is_small` | Checkpoints stay within ¼ budget yet reach past frame 32 (interval doubling). |
| | `test_frame_bigger_than_canvas_is_clipped`, `test_frame_larger_than_canvas_matches_reference` (×2) | Oversized and off-canvas frames are clipped like the reference, interlaced or not. |
| | `test_no_global_palette_and_out_of_table_index` | Indices beyond a 2-entry table decode as opaque black. |
| | `test_missing_trailer_warns`, `test_unknown_block_stops_with_warning`, `test_gif87a_without_extensions` | Warnings; GIF87a with no GCE → delay 0, disposal 0, loop `None`. |
| Short LZW | `test_short_lzw_stream_keeps_decoded_pixels`, `test_short_lzw_partially_off_canvas` (×12) | Exactly the decoded prefix is painted (also when it ends in index-0 pixels, exercising the 0/255 refill), for interlaced and non-interlaced frames larger than the canvas; a warning appears only when visible pixels are missing. |
| Memory DoS | `test_huge_frame_descriptor_rejected_fast_and_small` (×4), `test_huge_frame_after_good_frames_still_rejected`, `test_frame_within_slack_is_accepted`, `test_descriptor_bomb_peak_rss_in_subprocess` | Files under 64 bytes that *declare* huge frames are rejected with the right message, in < 1 s, with < 100 MiB peak `tracemalloc`. The same holds after a good frame. 40×40 on 10×10 is allowed (within slack). Real RSS growth < 100 MiB, measured in a subprocess (POSIX only). |
| Off-canvas | `test_off_canvas_frame_is_not_decoded` | An off-canvas frame with **corrupt** LZW still counts, keeps its delay, and causes no warning, because it is never decoded. |
| Performance | `test_open_performance_500x500x200` | Opening (full index pass) takes < 6 s (target < 2 s, measured about 0.3 s). |

## How it works
`_write` serialises a `GifSpec`; `_assert_frames` compares `normalize_rgba` bytes frame by frame. Corrupting a frame's LZW uses `encode_gif`'s returned data offsets and walks the sub-block chain to splice in new blocks. `_descriptor_bomb` hand-assembles a tiny file whose second descriptor declares an arbitrary size.

## Invariants & gotchas
- 56 cases. The RSS test uses `resource` and is skipped on Windows. It needs `PYTHONPATH` pointing at `src` in the subprocess, which the test sets itself.
- The time bounds are generous so they pass on slow CI; they catch only pathological regressions.

## Tests
- **Gaps:** no `ANIMEXTS1.0` loop entry; no comment or plain-text extension in the corpus (the parser skips them, but that is untested); no corrupt colour-table sizes mid-file.

## History
- `212b23f` (decoder rewrite), DoS cases added in `5a464d8`.
