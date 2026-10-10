"""Tiny helpers to build test GIFs in code (no binary fixtures in git)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

PALETTE = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (0, 255, 255),
    (255, 0, 255),
    (255, 255, 255),
    (0, 0, 0),
]


def solid_frames(n: int, size: tuple[int, int] = (16, 12)) -> list[Image.Image]:
    """n RGB frames, each a distinct solid colour (frame i uses PALETTE[i % 8])."""
    return [Image.new("RGB", size, PALETTE[i % len(PALETTE)]) for i in range(n)]


def make_gif(
    path: Path,
    frames: Sequence[Image.Image],
    durations: int | Sequence[int] = 100,
    *,
    loop: int | None = 0,
    disposal: int | Sequence[int] = 1,
    transparency: int | None = None,
) -> Path:
    """Write `frames` as an animated GIF with Pillow and return the path."""
    kw: dict = {
        "save_all": True,
        "append_images": list(frames[1:]),
        "duration": durations if isinstance(durations, int) else list(durations),
        "disposal": disposal if isinstance(disposal, int) else list(disposal),
        "optimize": False,
    }
    if loop is not None:
        kw["loop"] = loop
    if transparency is not None:
        kw["transparency"] = transparency
    frames[0].save(path, **kw)
    return path
