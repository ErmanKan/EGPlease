"""End-to-end glue: source + EditState -> output GIF (and single-frame PNG export).

Order (see AGENTS.md): ``timeline.plan_output`` decides which source frames are
emitted and their delays; each emitted frame is then rendered
(crop -> resize), quantized onto one shared palette, and streamed into ``encoder.write_gif``.
The UI's summary, the live preview and Generate all use the same functions here,
so what the user sees is what gets written.
"""

from __future__ import annotations

import io
import os
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from gif_editor.core.decoder import GifSource, SourceMeta
from gif_editor.core.encoder import read_back, write_gif, write_stream
from gif_editor.core.models import EditState
from gif_editor.core.render import (
    Palette,
    build_palette,
    output_dimensions,
    quantize,
    render_frame,
    sample_indices,
)
from gif_editor.core.timeline import TimelinePlan, plan_output

ESTIMATE_SAMPLES = 5

ProgressFn = Callable[[int, int | None], None]


@dataclass(frozen=True, slots=True)
class Summary:
    """What Generate would produce (exact except for file size)."""

    frame_count: int
    duration_ms: int
    width: int
    height: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GenerateResult:
    path: Path
    frame_count: int
    duration_ms: int
    width: int
    height: int
    size_bytes: int
    warnings: tuple[str, ...]


def plan(meta: SourceMeta, state: EditState) -> TimelinePlan:
    """Validate ``state`` against the source and return the output timeline."""
    state.validate(meta.width, meta.height, meta.frame_count)
    return plan_output(meta.delays_ms, state)


def summarize(meta: SourceMeta, state: EditState) -> Summary:
    p = plan(meta, state)
    w, h = output_dimensions(meta.width, meta.height, state.crop, state.size)
    return Summary(p.frame_count, p.duration_ms, w, h, p.warnings)


def render_output_frame(source: GifSource, src_index: int, state: EditState) -> Image.Image:
    """Composited source frame with crop + resize applied (RGBA). Used by preview too."""
    return render_frame(source.frame(src_index), state.crop, state.size)


def output_palette(source: GifSource, state: EditState, timeline: TimelinePlan) -> Palette:
    """One shared palette for the whole output, from up to 16 evenly spaced output frames.

    A transparent index is reserved whenever the source has any transparency, so every
    output frame can be mapped onto this palette.
    """
    frames = timeline.frames
    if not frames:
        raise ValueError("cannot build a palette for an empty timeline")
    samples = [
        render_output_frame(source, frames[i].src_index, state) for i in sample_indices(len(frames))
    ]
    return build_palette(samples, state.quality, transparent=source.meta.has_transparency)


def iter_output_frames(
    source: GifSource,
    state: EditState,
    timeline: TimelinePlan,
    palette: Palette | None = None,
) -> Iterator[tuple[Image.Image, int]]:
    """Lazily yield ``(P-mode frame, delay_cs)`` for every planned output frame.

    Every frame is mapped onto one shared palette (``palette`` or, if omitted, the
    result of `output_palette`), and with dithering the previous frame's index is kept
    wherever the rendered pixel did not change, so static areas never shimmer.
    """
    if palette is None:
        palette = output_palette(source, state, timeline)
    prev: tuple[Image.Image, Image.Image] | None = None
    for out in timeline.frames:
        rgba = render_output_frame(source, out.src_index, state)
        p = quantize(rgba, state.quality, palette, prev)
        prev = (rgba, p)
        yield p, out.delay_cs


def estimate_size(
    source: GifSource,
    state: EditState,
    timeline: TimelinePlan,
    *,
    samples: int = ESTIMATE_SAMPLES,
) -> int:
    """Rough output size in bytes, from encoding a few real output frames in memory.

    Generates the first frame plus ``samples - 1`` evenly spaced frames with the real
    pipeline (shared palette, cropping, differencing) and extrapolates linearly:
    ``first + average_per_frame * (count - 1)``. Returns 0 for an empty plan.

    The frames sampled are a CONTIGUOUS run from the middle of the timeline, and they are
    encoded TOGETHER as one stream. Both details matter: GIF stores every frame as the
    difference from the previous one, so measuring frames one at a time (or sampling frames
    far apart) wildly overestimates. The run's total size minus the cost of its first frame
    is the real per-frame cost of an additional frame.

    It is still an ESTIMATE (the UI shows it with a "~"): scenes that change a lot cost
    more, and quantisation noise varies across the source. It encodes a handful of frames
    (well under 100 ms for typical GIFs), so for a very large source call it off the GUI
    thread.
    """
    n = timeline.frame_count
    if n == 0:
        return 0
    count = max(1, min(int(samples), n))
    start = max(0, min(n - count, (n - count) // 2))
    palette = output_palette(source, state, timeline)
    frames = iter_output_frames(source, state, timeline, palette)
    window: list[tuple[Image.Image, int]] = []
    for i, frame in enumerate(frames):
        if i >= start:
            window.append(frame)
        if i >= start + count - 1:
            break
    if not window:
        return 0
    # Measure the run as ONE stream, then the first frame of the run on its own: the
    # difference is the real cost of each additional frame (which GIF stores as a diff).
    run_bytes = _encoded_size(window)
    first_bytes = _encoded_size(window[:1])
    if len(window) == 1:
        per_frame = first_bytes
    else:
        per_frame = max(0.0, (run_bytes - first_bytes) / (len(window) - 1))
    return max(0, int(first_bytes + per_frame * (n - 1)))


def _encoded_size(frames: list[tuple[Image.Image, int]]) -> int:
    """Bytes the real encoder produces for these frames, in memory (no files touched)."""
    buf = io.BytesIO()
    write_stream(buf, frames, loop=0)
    return buf.getbuffer().nbytes


def _verifier(timeline: TimelinePlan) -> Callable[[Path], None]:
    expected = [f.delay_cs * 10 for f in timeline.frames]

    def verify(path: Path) -> None:
        count, durations = read_back(path)
        if count != len(expected) or durations != expected:
            raise RuntimeError(
                f"written GIF failed verification: {count} frames / durations "
                f"{durations[:8]}... expected {len(expected)} frames / {expected[:8]}..."
            )

    return verify


def generate(
    source: GifSource,
    state: EditState,
    out_path: str | os.PathLike[str],
    *,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> GenerateResult:
    """Write the edited GIF atomically. Raises ``ValueError`` if nothing would be output
    and ``encoder.Cancelled`` if ``cancel`` is set.

    The source's loop setting is kept as is (no loop extension -> none written).  The
    temporary file is read back before it replaces ``out_path``; a frame count or
    duration mismatch raises ``RuntimeError`` and leaves ``out_path`` untouched."""
    meta = source.meta
    timeline = plan(meta, state)
    if timeline.frame_count == 0:
        reason = "; ".join(timeline.warnings) or "no frames left"
        raise ValueError(f"nothing to generate: {reason}")
    path = write_gif(
        iter_output_frames(source, state, timeline),
        out_path,
        loop=meta.loop,  # None (no loop block: plays once) stays None
        total=timeline.frame_count,
        progress=progress,
        cancel=cancel,
        verify=_verifier(timeline),
    )
    w, h = output_dimensions(meta.width, meta.height, state.crop, state.size)
    return GenerateResult(
        path=Path(path),
        frame_count=timeline.frame_count,
        duration_ms=timeline.duration_ms,
        width=w,
        height=h,
        size_bytes=Path(path).stat().st_size,
        warnings=timeline.warnings,
    )


def export_frame_png(
    source: GifSource,
    index: int,
    out_path: str | os.PathLike[str],
    state: EditState | None = None,
) -> Path:
    """Save one composited source frame as PNG (RGBA, full colour).

    With ``state`` the crop and resize are applied; without it the original frame
    is saved. Written atomically (temp file + ``os.replace``).
    """
    img = source.frame(index)
    if state is not None:
        state.validate(source.meta.width, source.meta.height, source.meta.frame_count)
        img = render_frame(img, state.crop, state.size)
    dest = Path(out_path)
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
    try:
        img.save(tmp, format="PNG")
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return dest
