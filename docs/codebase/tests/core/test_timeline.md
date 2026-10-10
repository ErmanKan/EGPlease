# `tests/core/test_timeline.py`

> Table-driven and randomized property tests for `timeline.plan_output` and its helpers.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/timeline.py`, `core/models.py`.

## Public API
| Group | Tests | Verifies |
|---|---|---|
| Helpers | `test_start_times`, `test_frame_at_time` (×9), `test_frame_at_time_empty_raises`, `test_plan_properties`, `test_invalid_delay_raises`, `test_empty_source` | Cumulative starts; frame lookup at boundaries and clamping; `TimelinePlan` properties; a delay of 0 raises; an empty source gives an empty plan with a warning. |
| Identity | `test_identity_uniform`, `test_identity_mixed_multiples_of_10` | No edits → same frames and delays, no warnings. |
| Trim | `test_trim_table` (×13), `test_trim_tiny_tail_is_folded_into_previous`, `test_trim_start_beyond_end` (×3), `test_trim_keeps_partial_frames_duration_exact`, `test_trim_start_inside_single_long_frame`, `test_trim_duration_is_window_length` (×42) | Partial frames clipped at both ends; a 5 ms tail folded and rounded half up (105 ms → 11 cs); start ≥ total → empty + "beyond"; the output length equals the window length ± 10 ms. |
| Delete | `test_delete_removes_time`, `test_delete_out_of_range_ignored`, `test_delete_after_trim`, `test_all_deleted`, `test_all_kept_frames_deleted_after_trim` | Deleting removes time; deleting after trim works; empty results warn. |
| Speed | `test_speed_2x_halves`, `test_speed_half_doubles`, `test_speed_4x_on_20ms_drops_frames`, `test_speed_4x_on_40ms_drops_every_other`, `test_short_frame_between_long_folds_into_previous`, `test_leading_short_run_folds_into_next_long_frame`, `test_whole_timeline_shorter_than_20ms` | Delays scale; runs below 20 ms are grouped; "N frames dropped" warning; edge folding rules. |
| FPS | `test_fps_10_on_50ms`, `test_fps_higher_than_source_unchanged` (×5), `test_fps_preserves_total_with_partial_tick`, `test_fps_30_to_24_uniform_grid`, `test_fps_cap_uneven_33_34_33`, `test_fps_sole_frame_shorter_than_step`, `test_fps_random_cap_enforced`, `test_fps_after_speed`, `test_fps_order_preserved_no_duplicates` | The grid resample really caps the rate (400 random cases), never slows down a slower source, preserves the total and the order, never duplicates. |
| Max delay | `test_long_delay_split`, `test_long_delay_split_uneven_and_neighbours`, `test_max_delay_not_split` | > 65535 cs is split into equal parts with the same source index and a warning; exactly 65535 is not split. |
| Rounding | `test_thirty_fps_delays_rounding`, `test_rounding_never_accumulates`, `test_rounding_min_2cs_enforced` | 33.3 ms frames become 3/4 cs; 3000 frames drift < 10 ms in total; never below 2 cs. |
| Combined | `test_combined_pipeline` | trim + delete + speed + fps worked example (see the timeline page). |
| Properties | `test_random_invariants` (600 random states), `test_deterministic`, `test_performance_10k_frames` | Against an independent overlap model (`_overlaps`): every delay ≥ 2 cs; indices strictly increasing and a subset of the kept frames; fps cap holds; duration == sum × 10; duration within 10 ms of exact (or a single ≤ 30 ms frame); ≤ 2 warnings. Equal output for equal input. < 50 ms per 10k-frame plan. |

## How it works
`plan(delays, **kw)` is a shortcut for `plan_output(delays, EditState().with_(**kw))`. `D10 = [100] * 10` is the standard source for the trim table. The property test generates random delays (including 1 ms and 5 ms), trim windows, deletions, speeds and fps values.

## Invariants & gotchas
- 112 cases. Random tests use fixed seeds, so they are deterministic. Note that `test_fps_order_preserved_no_duplicates` and `test_random_invariants` call `random.seed`, which changes the global RNG for later tests in the same process.

## Tests
- **Gaps:** the "Delays rounded to 10 ms steps" warning text is never asserted; there is no test that plans fed with *raw* 0 ms delays are rejected at the pipeline level (they can't happen through `SourceMeta.delays_ms`).

## History
- `c06ef17`, extended in `e8bcb7e` (strict grid, partial trim frames, splitting).
