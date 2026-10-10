# `tests/core/test_encoder.py`

> Tests for the GIF writer: correctness of the bytes, lossless differencing, transparency handling, atomicity, progress/cancel, verify hook.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/encoder.py`, `core/decoder.py` (as a browser-semantics reader for the lossless checks), Pillow (as a second reader).

## Public API
| Group | Tests | Verifies |
|---|---|---|
| Basics | `test_basic_write_and_read_back`, `test_accepts_str_path_and_returns_path`, `test_loop_parameter_respected` (×3), `test_invalid_loop_rejected`, `test_identical_frames_total_duration_exact` | Count, durations, loop, full-canvas rects and disposal 1 for opaque content, no leftover `.tmp`; identical frames are **not** merged (unlike Pillow). |
| Transparency | `test_transparency_round_trip_first_frame`, `test_transparency_only_in_later_frames`, `test_opaque_border_matching_first_transparent_colour_survives` | Disposal sequence `[1, 2, 2]` (clear before an opaque→transparent change, and at the loop end when frame 0 is transparent) and `[1,1,2,1,1]`; the disposal-2 frame covers the full canvas; frame 0 declares an unused transparency index so Pillow decodes RGBA; **the Pillow save_all border bug does not happen**. |
| Progress / cancel | `test_progress_reports_each_frame_with_total`, `test_progress_total_none_by_default`, `test_frames_consumed_lazily`, `test_cancel_mid_way`, `test_cancel_after_last_frame_still_cancels` | `(done, total)` after each frame; frames pulled one at a time; cancel stops pulling, keeps the old destination, leaves no temp file. |
| Atomicity | `test_generator_exception_cleans_up`, `test_new_destination_not_created_on_error`, `test_overwrites_existing_destination_on_success` | Errors leave the destination unchanged or absent; success replaces it. |
| Validation | `test_invalid_delay_rejected` (×6), `test_mismatched_sizes_rejected`, `test_non_p_mode_rejected`, `test_empty_rejected` | Delays 1, 0, -5, 70000, 2.5, `True`; sizes; mode; empty input → `ValueError`, nothing left behind. |
| Misc | `test_non_ascii_filename`, `test_full_256_colour_palette`, `test_read_back_static_gif`, `test_estimate_size_within_tolerance`, `test_estimate_size_edge_cases` | Turkish file name; random 256-colour frames are exact; a static GIF reads as `(1, [0])`; the estimate is within 35 % on noise; empty/zero → 0. |
| Loop / verify | `test_loop_none_writes_no_netscape_block`, `test_verify_success_runs_on_temp_before_replace`, `test_verify_failure_keeps_destination` | `loop=None` has no NETSCAPE block; `verify` sees the temp file while the destination still has the old bytes; a failing `verify` aborts cleanly. |
| Differencing | `test_diff_frames_write_only_changed_rect`, `test_differing_palettes_keep_local_tables`, `test_random_animation_lossless` (×24), `test_full_palette_partial_change_lossless` | Exact changed rects (`(3,5,9,4)`); an identical frame becomes a 1×1 rect; a shared palette → global table only; differing palettes → local tables; a frame that decodes the same but has a different palette → 1×1 rect; random animations with appearing/disappearing transparency are **lossless** with shared and per-frame permuted palettes, looping or not; all 256 indices used still lossless. |

## How it works
- `gif_frames(path)` is a minimal block parser written for the tests. It returns each frame's rect, disposal, transparency index, delay and local-table flag, so tests can assert on the file *structure*, not just on decoded pixels.
- `assert_lossless` decodes with **our** `GifSource` (browser semantics) and compares with the input frames' palette colours, transparent pixels normalised to 0.
- `rgba_frames` decodes with Pillow, as a second, independent reader.

## Invariants & gotchas
- 62 cases.

## Tests
- **Gaps:** `fsync` behaviour; a Windows lock on the destination; `estimate_size` on realistic content; a cancel *during* `verify`.

## History
- `cca60c1`, extended in `8e7d34c` (differencing) and `f7056d9` (verify, `loop=None`).
