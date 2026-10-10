"""Output timeline planner: the ONLY place that decides output frames and delays.

``plan_output(delays_ms, state)`` turns the effective source delays plus an
``EditState`` into a ``TimelinePlan`` (source frame index + integer centisecond
delay per output frame). Pipeline, in order:

1. **Trim** (source time). The window is ``[trim_start_ms, trim_start_ms +
   trim_duration_ms)`` (``None`` duration = to the end). A frame is kept iff its
   *start time* lies inside the window. Consequently a frame that starts before
   ``trim_start_ms`` is dropped even if it is still visible at that instant
   (trimming never shows a frame that "began" before the cut). The last kept
   frame is shortened so it does not extend past the window end.
2. **Delete**: frames whose source index is in ``state.deleted`` are removed
   together with their time (the GIF gets shorter).
3. **Speed**: each delay is divided by ``state.speed`` (exact floats).
4. **FPS** (``state.fps`` not ``None``): sample the concatenated timeline on a
   uniform grid of step ``1000 / fps`` ms starting at 0. A frame is output iff
   at least one tick falls inside ``[start, end)``; a frame no tick hits is
   dropped and its time is added to the previous output frame. Output frames
   keep their real start times (they are not snapped to the grid), so when the
   source is already slower than ``fps`` the timing is unchanged. Frames are
   only dropped, never duplicated; order and total duration are preserved.
5. **Min delay** (20 ms): consecutive frames shorter than 20 ms are grouped
   left to right until the group reaches 20 ms; the group's first frame is
   emitted with the group's total time. A short run that never reaches 20 ms
   is folded into the previously emitted frame (or, at the very start, into
   the next frame). Total duration is preserved.
6. **Rounding** to centiseconds with error carry: ``delay_cs[k] =
   round(end[k] / 10) - round(end[k-1] / 10)`` (round half up), so the total
   error is < 10 ms. Delays that round below 2 cs are raised to 2 cs and the
   excess is taken from the following (or, at the end, preceding) frames.

All functions are pure and deterministic. Invalid source delays (< 1 ms) raise
``ValueError``; an empty result never raises — it returns an empty plan with a
warning.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from gif_editor.core.models import EditState

MIN_DELAY_MS = 20
MIN_DELAY_CS = 2
ROUNDING_WARN_MS = 5.0
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class OutputFrame:
    src_index: int
    delay_cs: int


@dataclass(frozen=True, slots=True)
class TimelinePlan:
    frames: tuple[OutputFrame, ...]
    duration_ms: int
    warnings: tuple[str, ...] = ()

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def src_indices(self) -> tuple[int, ...]:
        return tuple(f.src_index for f in self.frames)

    @property
    def delays_cs(self) -> tuple[int, ...]:
        return tuple(f.delay_cs for f in self.frames)


def start_times_ms(delays_ms: Sequence[int]) -> list[int]:
    """Cumulative start time (ms) of each source frame."""
    out: list[int] = []
    t = 0
    for d in delays_ms:
        out.append(t)
        t += d
    return out


def frame_at_time(delays_ms: Sequence[int], t_ms: float) -> int:
    """Index of the source frame visible at source time ``t_ms`` (clamped)."""
    if not delays_ms:
        raise ValueError("no frames")
    if t_ms <= 0:
        return 0
    starts = start_times_ms(delays_ms)
    return min(bisect_right(starts, t_ms) - 1, len(delays_ms) - 1)


def _empty(warnings: list[str]) -> TimelinePlan:
    return TimelinePlan((), 0, tuple(warnings))


def _trim(delays: Sequence[int], state: EditState, warnings: list[str]) -> list[tuple[int, int]]:
    total = sum(delays)
    start = state.trim_start_ms
    end = total if state.trim_duration_ms is None else start + state.trim_duration_ms
    if start >= total:
        warnings.append(f"Trim start ({start} ms) is at or beyond the end of the GIF ({total} ms)")
        return []
    kept: list[tuple[int, int]] = []
    t = 0
    for i, d in enumerate(delays):
        if t >= end:
            break
        if t >= start:
            kept.append((i, min(d, end - t)))
        t += d
    if not kept:
        warnings.append("No frame starts inside the trim window")
    return kept


def _resample(frames: list[tuple[int, float]], fps: float) -> list[tuple[int, float]]:
    """Keep frames hit by a tick of the 1000/fps grid; fold the rest into the previous one."""
    step = 1000.0 / fps
    out: list[tuple[int, float]] = []
    t = 0.0
    for src, d in frames:
        a, b = t, t + d
        t = b
        if out and math.ceil(b / step - _EPS) <= math.ceil(a / step - _EPS):
            out[-1] = (out[-1][0], out[-1][1] + d)  # no tick inside: drop, keep its time
        else:
            out.append((src, d))
    return out


def _enforce_min_delay(frames: list[tuple[int, float]]) -> tuple[list[list], int]:
    """Greedy left-to-right folding of frames shorter than MIN_DELAY_MS."""
    thr = MIN_DELAY_MS - _EPS
    out: list[list] = []  # [src, dur]
    group_src: int | None = None
    group_dur = 0.0
    group_n = 0
    dropped = 0
    for src, d in frames:
        if d >= thr:
            if group_src is not None:  # short run that never reached 20 ms
                dropped += group_n
                if out:
                    out[-1][1] += group_dur
                else:
                    d += group_dur
                group_src, group_dur, group_n = None, 0.0, 0
            out.append([src, d])
            continue
        if group_src is None:
            group_src, group_dur, group_n = src, d, 1
        else:
            group_dur += d
            group_n += 1
        if group_dur >= thr:
            out.append([group_src, group_dur])
            dropped += group_n - 1
            group_src, group_dur, group_n = None, 0.0, 0
    if group_src is not None:
        if out:
            out[-1][1] += group_dur
            dropped += group_n
        else:  # whole timeline shorter than 20 ms: keep a single frame
            out.append([group_src, group_dur])
            dropped += group_n - 1
    return out, dropped


def _round_cs(durations: list[float]) -> list[int]:
    cs: list[int] = []
    prev_r = 0
    cum = 0.0
    debt = 0
    for d in durations:
        cum += d
        r = math.floor(cum / 10.0 + 0.5)
        v = r - prev_r - debt
        prev_r = r
        if v < MIN_DELAY_CS:
            debt = MIN_DELAY_CS - v
            v = MIN_DELAY_CS
        else:
            debt = 0
        cs.append(v)
    k = len(cs) - 1
    while debt > 0 and k >= 0:
        take = min(debt, cs[k] - MIN_DELAY_CS)
        if take > 0:
            cs[k] -= take
            debt -= take
        k -= 1
    return cs


def plan_output(delays_ms: Sequence[int], state: EditState) -> TimelinePlan:
    """Plan the output frames and centisecond delays (see module docstring)."""
    warnings: list[str] = []
    if any(d < 1 for d in delays_ms):
        raise ValueError("source delays must be >= 1 ms")
    if not delays_ms:
        return _empty(["The source has no frames"])

    kept = _trim(delays_ms, state, warnings)
    if not kept:
        return _empty(warnings)

    if state.deleted:
        kept = [(i, d) for i, d in kept if i not in state.deleted]
        if not kept:
            warnings.append("All frames in the selection are deleted")
            return _empty(warnings)

    speed = float(state.speed)
    frames: list[tuple[int, float]] = [(i, d / speed) for i, d in kept]

    if state.fps is not None:  # dropping frames here is the user's intent: no warning
        frames = _resample(frames, float(state.fps))

    folded, dropped = _enforce_min_delay(frames)
    if dropped:
        warnings.append(f"{dropped} frames dropped: delays below {MIN_DELAY_MS} ms (50 fps max)")

    durations = [d for _, d in folded]
    cs = _round_cs(durations)
    max_dev = max(abs(c * 10 - d) for c, d in zip(cs, durations, strict=True))
    if max_dev > ROUNDING_WARN_MS:
        warnings.append(f"Delays rounded to 10 ms steps (up to {max_dev:.0f} ms per frame)")

    out = tuple(OutputFrame(src, c) for (src, _), c in zip(folded, cs, strict=True))
    return TimelinePlan(out, sum(cs) * 10, tuple(warnings))
