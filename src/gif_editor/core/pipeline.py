"""End-to-end glue: source + EditState -> output GIF (and single-frame PNG export).

Order (see AGENTS.md): ``timeline.plan_output`` decides which source frames are
emitted and their delays; each emitted frame is then rendered
(crop -> resize) and quantized, and streamed into ``encoder.write_gif``.
The UI's summary, the live preview and Generate all use the same functions here,
so what the user sees is what gets written.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from gif_editor.core.decoder import GifSource, SourceMeta
from gif_editor.core.encoder import write_gif
from gif_editor.core.models import EditState
from gif_editor.core.render import output_dimensions, quantize, render_frame
from gif_editor.core.timeline import TimelinePlan, plan_output

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


def iter_output_frames(
    source: GifSource, state: EditState, timeline: TimelinePlan
) -> Iterator[tuple[Image.Image, int]]:
    """Lazily yield ``(P-mode frame, delay_cs)`` for every planned output frame."""
    for out in timeline.frames:
        rgba = render_output_frame(source, out.src_index, state)
        yield quantize(rgba, state.quality), out.delay_cs


def generate(
    source: GifSource,
    state: EditState,
    out_path: str | os.PathLike[str],
    *,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> GenerateResult:
    """Write the edited GIF atomically. Raises ``ValueError`` if nothing would be output
    and ``encoder.Cancelled`` if ``cancel`` is set."""
    meta = source.meta
    timeline = plan(meta, state)
    if timeline.frame_count == 0:
        reason = "; ".join(timeline.warnings) or "no frames left"
        raise ValueError(f"nothing to generate: {reason}")
    loop = meta.loop if meta.loop is not None else 0
    path = write_gif(
        iter_output_frames(source, state, timeline),
        out_path,
        loop=loop,
        total=timeline.frame_count,
        progress=progress,
        cancel=cancel,
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
