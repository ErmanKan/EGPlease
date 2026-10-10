"""Tests for core/timeline.py (plan_output timing engine)."""

from __future__ import annotations

import itertools
import random
import time

import pytest

from gif_editor.core.models import EditState
from gif_editor.core.timeline import (
    OutputFrame,
    TimelinePlan,
    frame_at_time,
    plan_output,
    start_times_ms,
)

S = EditState()


def plan(delays, **kw):
    return plan_output(delays, S.with_(**kw) if kw else S)


# --- helpers -----------------------------------------------------------------


def test_start_times():
    assert start_times_ms([]) == []
    assert start_times_ms([100, 50, 30]) == [0, 100, 150]


@pytest.mark.parametrize(
    ("t", "expected"),
    [(-5, 0), (0, 0), (99, 0), (100, 1), (149, 1), (150, 2), (179, 2), (180, 2), (10_000, 2)],
)
def test_frame_at_time(t, expected):
    assert frame_at_time([100, 50, 30], t) == expected


def test_frame_at_time_empty_raises():
    with pytest.raises(ValueError):
        frame_at_time([], 0)


def test_plan_properties():
    p = TimelinePlan((OutputFrame(0, 10), OutputFrame(3, 5)), 150, ())
    assert p.frame_count == 2
    assert p.src_indices == (0, 3)
    assert p.delays_cs == (10, 5)


def test_invalid_delay_raises():
    with pytest.raises(ValueError):
        plan_output([100, 0], S)


def test_empty_source():
    p = plan_output([], S)
    assert p.frames == () and p.duration_ms == 0 and p.warnings


# --- identity ------------------------------------------------------------------


def test_identity_uniform():
    p = plan([100] * 10)
    assert p.src_indices == tuple(range(10))
    assert p.delays_cs == (10,) * 10
    assert p.duration_ms == 1000
    assert p.warnings == ()


def test_identity_mixed_multiples_of_10():
    d = [20, 30, 100, 70, 500]
    p = plan(d)
    assert p.delays_cs == tuple(x // 10 for x in d)
    assert p.warnings == ()


# --- trim ------------------------------------------------------------------------

D10 = [100] * 10  # frames start at 0, 100, ..., 900


@pytest.mark.parametrize(
    ("start", "dur", "indices", "delays"),
    [
        (0, None, tuple(range(10)), (10,) * 10),
        (300, None, tuple(range(3, 10)), (10,) * 7),  # exact frame boundary
        (250, None, tuple(range(2, 10)), (5,) + (10,) * 7),  # frame 2 visible at 250: clipped
        (300, 300, (3, 4, 5), (10, 10, 10)),  # exact window
        (0, 250, (0, 1, 2), (10, 10, 5)),  # last kept frame shortened
        (250, 200, (2, 3, 4), (5, 10, 5)),  # window [250,450): 2 and 4 clipped to 50 ms
        (900, None, (9,), (10,)),  # last frame only
        (899, None, (9,), (10,)),  # frame 8 clipped to 1 ms, folded into frame 9
        (950, None, (9,), (5,)),  # start inside the last frame
        (50, 100, (0, 1), (5, 5)),
        (0, 10_000, tuple(range(10)), (10,) * 10),  # duration past end is harmless
        (0, 100, (0,), (10,)),  # window end exactly at frame boundary
        (0, 120, (0, 1), (10, 2)),  # 20 ms tail survives
    ],
)
def test_trim_table(start, dur, indices, delays):
    p = plan(D10, trim_start_ms=start, trim_duration_ms=dur)
    assert p.src_indices == indices
    assert p.delays_cs == delays


def test_trim_tiny_tail_is_folded_into_previous():
    # window [0, 105): frame 1 is kept (starts at 100) but cut to 5 ms < 20 ms
    p = plan(D10, trim_duration_ms=105)
    assert p.src_indices == (0,)
    assert p.delays_cs == (11,)  # 105 ms rounds half up to 11 cs
    assert any("dropped" in w for w in p.warnings)


@pytest.mark.parametrize("start", [1000, 1001, 50_000])
def test_trim_start_beyond_end(start):
    p = plan(D10, trim_start_ms=start)
    assert p.frames == () and p.duration_ms == 0
    assert len(p.warnings) == 1 and "beyond" in p.warnings[0]


def test_trim_keeps_partial_frames_duration_exact():
    p = plan([1000, 1000], trim_start_ms=500, trim_duration_ms=1000)
    assert p.src_indices == (0, 1)
    assert p.delays_cs == (50, 50)
    assert p.duration_ms == 1000
    assert p.warnings == ()


def test_trim_start_inside_single_long_frame():
    p = plan([5000], trim_start_ms=100)
    assert p.src_indices == (0,)
    assert p.delays_cs == (490,)
    assert p.duration_ms == 4900


@pytest.mark.parametrize("start", [0, 1, 37, 250, 333, 899, 999])
@pytest.mark.parametrize("dur", [None, 1, 20, 150, 333, 5000])
def test_trim_duration_is_window_length(start, dur):
    p = plan(D10, trim_start_ms=start, trim_duration_ms=dur)
    expected = min(1000, start + dur) - start if dur is not None else 1000 - start
    assert abs(p.duration_ms - max(expected, 20)) < 10


# --- delete -------------------------------------------------------------------------


def test_delete_removes_time():
    p = plan(D10, deleted={0, 5, 9})
    assert p.src_indices == (1, 2, 3, 4, 6, 7, 8)
    assert p.duration_ms == 700


def test_delete_out_of_range_ignored():
    assert plan([100] * 3, deleted={7}).src_indices == (0, 1, 2)


def test_delete_after_trim():
    p = plan(D10, trim_start_ms=200, trim_duration_ms=300, deleted={3, 0})
    assert p.src_indices == (2, 4)
    assert p.duration_ms == 200


def test_all_deleted():
    p = plan(D10, deleted=set(range(10)))
    assert p.frames == () and p.duration_ms == 0
    assert len(p.warnings) == 1


def test_all_kept_frames_deleted_after_trim():
    p = plan(D10, trim_start_ms=500, trim_duration_ms=200, deleted={5, 6})
    assert p.frames == () and p.warnings


# --- speed ----------------------------------------------------------------------------


def test_speed_2x_halves():
    p = plan(D10, speed=2.0)
    assert p.src_indices == tuple(range(10))
    assert p.delays_cs == (5,) * 10
    assert p.warnings == ()


def test_speed_half_doubles():
    p = plan(D10, speed=0.5)
    assert p.delays_cs == (20,) * 10


def test_speed_4x_on_20ms_drops_frames():
    p = plan([20] * 40, speed=4.0)  # 5 ms each -> groups of 4
    assert p.src_indices == tuple(range(0, 40, 4))
    assert p.delays_cs == (2,) * 10
    assert p.duration_ms == 200
    assert len(p.warnings) == 1
    assert p.warnings[0].startswith("30 frames dropped")


def test_speed_4x_on_40ms_drops_every_other():
    p = plan([40] * 10, speed=4.0)  # 10 ms each -> pairs
    assert p.src_indices == (0, 2, 4, 6, 8)
    assert p.delays_cs == (2,) * 5


def test_short_frame_between_long_folds_into_previous():
    p = plan([100, 10, 100], speed=1.0)
    assert p.src_indices == (0, 2)
    assert p.delays_cs == (11, 10)
    assert p.warnings[0].startswith("1 frames dropped")


def test_leading_short_run_folds_into_next_long_frame():
    p = plan([5, 5, 100, 100])
    assert p.src_indices == (2, 3)
    assert p.duration_ms == 210


def test_whole_timeline_shorter_than_20ms():
    p = plan([5, 5])
    assert p.src_indices == (0,)
    assert p.delays_cs == (2,)


# --- fps ---------------------------------------------------------------------------------


def test_fps_10_on_50ms():
    p = plan([50] * 20, fps=10)
    assert p.src_indices == tuple(range(0, 20, 2))
    assert p.delays_cs == (10,) * 10
    assert p.duration_ms == 1000


@pytest.mark.parametrize("fps", [10, 12.5, 20, 25, 50])
def test_fps_higher_than_source_unchanged(fps):
    p = plan([100] * 10, fps=fps)
    assert p.src_indices == tuple(range(10))
    assert p.delays_cs == (10,) * 10


def test_fps_preserves_total_with_partial_tick():
    # 210 ms, ticks at 0/100/200 show frames 0, 3, 6; slots are 100, 100, 10 ms.
    # The truncated 10 ms tail is shorter than the 100 ms step -> merged into frame 3.
    p = plan([30] * 7, fps=10)
    assert p.src_indices == (0, 3)
    assert p.delays_cs == (10, 11)
    assert p.duration_ms == 210


def test_fps_30_to_24_uniform_grid():
    p = plan([100] * 30, speed=3.0, fps=24)  # 33.33 ms frames on a 41.67 ms grid
    assert set(p.delays_cs) <= {4, 5}
    assert p.frame_count == 24
    assert abs(p.duration_ms - 1000) < 10


def test_fps_cap_uneven_33_34_33():
    p = plan([33, 34, 33] * 10, fps=24)
    assert set(p.delays_cs) <= {4, 5}
    assert abs(p.duration_ms - 1000) < 10
    assert p.frame_count == 24


def test_fps_sole_frame_shorter_than_step():
    p = plan([30, 30], fps=5)  # 60 ms total < 200 ms step
    assert p.src_indices == (0,)
    assert p.delays_cs == (6,)


def test_fps_random_cap_enforced():
    rng = random.Random(99)
    for _ in range(400):
        n = rng.randint(2, 120)
        d = [rng.choice([10, 20, 33, 34, 40, 50, 70, rng.randint(1, 300)]) for _ in range(n)]
        fps = rng.choice([1, 5, 10, 12.5, 15, 24, 25, 30, 50, rng.uniform(0.5, 50)])
        speed = rng.choice([0.5, 1.0, 1.7, 3.0])
        p = plan(d, fps=fps, speed=speed)
        step = 1000 / fps
        ms = [c * 10 for c in p.delays_cs]
        assert all(x >= step - 10 for x in ms[:-1]), (d, fps, speed, ms)
        if p.frame_count > 1:
            assert p.frame_count / (p.duration_ms / 1000) <= fps * 1.02 + 0.5
        idx = p.src_indices
        assert all(a < b for a, b in itertools.pairwise(idx))
        assert abs(p.duration_ms - max(sum(d) / speed, 20)) < 10


def test_fps_after_speed():
    p = plan([100] * 10, speed=2.0, fps=10)  # 50 ms frames -> every other
    assert p.src_indices == (0, 2, 4, 6, 8)
    assert p.delays_cs == (10,) * 5


def test_fps_order_preserved_no_duplicates():
    random.seed(7)
    d = [random.randint(20, 200) for _ in range(200)]
    for fps in (1, 3, 7.5, 15, 24, 30, 50):
        p = plan(d, fps=fps)
        idx = p.src_indices
        assert list(idx) == sorted(set(idx))
        assert abs(p.duration_ms - sum(d)) < 10


# --- GIF max delay -----------------------------------------------------------------------

SPLIT_WARN = "Long frame split: GIF max delay is 655.35 s"


def test_long_delay_split():
    p = plan([655350], speed=0.25)  # 2621.4 s = 262140 cs
    assert p.delays_cs == (65535,) * 4
    assert p.src_indices == (0,) * 4
    assert p.duration_ms == 2_621_400
    assert SPLIT_WARN in p.warnings


def test_long_delay_split_uneven_and_neighbours():
    p = plan([100, 655360, 100])  # 65536 cs -> 32768 + 32768
    assert p.src_indices == (0, 1, 1, 2)
    assert p.delays_cs == (10, 32768, 32768, 10)
    assert all(c <= 65535 for c in p.delays_cs)
    assert p.duration_ms == 655_560
    assert p.warnings == (SPLIT_WARN,)


def test_max_delay_not_split():
    p = plan([655350])
    assert p.delays_cs == (65535,)
    assert p.warnings == ()


# --- rounding -------------------------------------------------------------------------------


def test_thirty_fps_delays_rounding():
    p = plan([100] * 30, speed=3.0)  # 33.333 ms each
    assert p.frame_count == 30
    assert set(p.delays_cs) <= {3, 4}
    assert abs(p.duration_ms - 1000) < 10


def test_rounding_never_accumulates():
    p = plan([100] * 3000, speed=3.0)
    assert abs(p.duration_ms - 100_000) < 10


def test_rounding_min_2cs_enforced():
    # 25 ms frames with odd phase can round to 1 cs without the min-2cs pass
    for lead in range(20, 40):
        p = plan([lead] + [21] * 50)
        assert all(c >= 2 for c in p.delays_cs)
        assert abs(p.duration_ms - (lead + 21 * 50)) < 10


# --- combined ---------------------------------------------------------------------------------


def test_combined_pipeline():
    d = [50] * 40  # 2000 ms
    p = plan(d, trim_start_ms=200, trim_duration_ms=1000, deleted={4, 5, 6, 7}, speed=2.0, fps=10)
    # trim -> frames 4..23 (1000 ms); delete -> 8..23 (800 ms); speed -> 25 ms each (400 ms)
    # fps 10 -> ticks every 100 ms -> frames 8, 12, 16, 20
    assert p.src_indices == (8, 12, 16, 20)
    assert p.delays_cs == (10,) * 4
    assert p.duration_ms == 400


# --- properties ------------------------------------------------------------------------------


def _overlaps(delays, st: EditState) -> dict[int, int]:
    """Clipped visible time of each non-deleted source frame inside the trim window."""
    total = sum(delays)
    start = st.trim_start_ms
    end = total if st.trim_duration_ms is None else min(total, start + st.trim_duration_ms)
    out = {}
    for i, (s, d) in enumerate(zip(start_times_ms(delays), delays, strict=True)):
        ov = min(s + d, end) - max(s, start)
        if ov > 0 and i not in st.deleted:
            out[i] = ov
    return out


def _exact_ms(delays, st: EditState) -> float:
    return sum(_overlaps(delays, st).values()) / st.speed


def _kept(delays, st: EditState) -> set[int]:
    return set(_overlaps(delays, st))


def test_random_invariants():
    random.seed(12345)
    for _ in range(600):
        n = random.randint(1, 80)
        delays = [
            random.choice([1, 5, 20, 30, 33, 40, 70, 100, 250, random.randint(1, 500)])
            for _ in range(n)
        ]
        total = sum(delays)
        st = S.with_(
            trim_start_ms=random.choice([0, 0, random.randint(0, total + 50)]),
            trim_duration_ms=random.choice([None, random.randint(1, total + 100)]),
            deleted=frozenset(random.sample(range(n), random.randint(0, n // 3))),
            speed=random.choice([0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, random.uniform(0.25, 4.0)]),
            fps=random.choice([None, None, 5, 10, 24, 30, 50, random.uniform(0.5, 50)]),
        )
        p = plan_output(delays, st)
        kept = _kept(delays, st)
        if not kept:
            assert p.frames == () and p.duration_ms == 0 and p.warnings
            continue
        assert p.frames
        assert all(f.delay_cs >= 2 for f in p.frames)
        idx = p.src_indices
        assert all(a < b for a, b in itertools.pairwise(idx))
        assert set(idx) <= kept
        if st.fps is not None:
            step = 1000 / st.fps
            assert all(c * 10 >= step - 10 for c in p.delays_cs[:-1]), (delays, st, p)
        assert p.duration_ms == sum(p.delays_cs) * 10
        exact = _exact_ms(delays, st)
        if exact >= 20:
            assert abs(p.duration_ms - exact) < 10, (delays, st, p)
        else:
            assert p.frame_count == 1 and p.duration_ms <= 30
        assert len(p.warnings) <= 2


def test_deterministic():
    random.seed(3)
    d = [random.randint(1, 300) for _ in range(500)]
    st = S.with_(speed=1.7, fps=23)
    assert plan_output(d, st) == plan_output(d, st)


def test_performance_10k_frames():
    random.seed(1)
    d = [random.randint(1, 300) for _ in range(10_000)]
    st = S.with_(speed=1.3, fps=24, deleted=frozenset(range(0, 10_000, 7)))
    plan_output(d, st)  # warm-up
    t0 = time.perf_counter()
    plan_output(d, st)
    plan_output(d, S)
    assert (time.perf_counter() - t0) / 2 < 0.05
