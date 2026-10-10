"""Per-frame render pipeline: crop -> resize (premultiplied LANCZOS) -> quantize."""

from __future__ import annotations

import numpy as np
from PIL import Image

from gif_editor.core.models import CropRect, OutputSize, Quality

ALPHA_THRESHOLD = 128  # GIF alpha is binary: alpha < 128 -> transparent
TRANSPARENT_RGB = (0, 0, 0)  # palette colour stored in the reserved transparent slot


def output_dimensions(
    canvas_w: int, canvas_h: int, crop: CropRect | None, size: OutputSize | None
) -> tuple[int, int]:
    """Final output size: explicit size, else crop size, else canvas size."""
    if size is not None:
        return size.width, size.height
    if crop is not None:
        return crop.w, crop.h
    return canvas_w, canvas_h


def render_frame(
    img_rgba: Image.Image, crop: CropRect | None, size: OutputSize | None
) -> Image.Image:
    """Crop then (if needed) LANCZOS-resize an RGBA frame. Never mutates the input."""
    if img_rgba.mode != "RGBA":
        raise ValueError(f"render_frame expects an RGBA image, got {img_rgba.mode!r}")
    out = img_rgba
    if crop is not None:
        crop.validate(img_rgba.width, img_rgba.height)
        out = out.crop((crop.x, crop.y, crop.x + crop.w, crop.y + crop.h))
    if size is not None and (size.width, size.height) != out.size:
        # Premultiplied alpha avoids dark/colour fringes from fully transparent neighbours.
        out = (
            out.convert("RGBa")
            .resize((size.width, size.height), Image.Resampling.LANCZOS)
            .convert("RGBA")
        )
    if out is img_rgba:
        out = img_rgba.copy()
    return out


def _palette_image(colors: list[tuple[int, int, int]]) -> Image.Image:
    pal = Image.new("P", (1, 1))
    pal.putpalette([c for rgb in colors for c in rgb])
    return pal


def _build_palette(rgb_pixels: np.ndarray, n: int) -> list[tuple[int, int, int]]:
    """Median-cut palette (<= n colours) for an (N, 3) uint8 pixel array."""
    strip = Image.fromarray(np.ascontiguousarray(rgb_pixels.reshape(1, -1, 3)), "RGB")
    q = strip.quantize(n, Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    used = sorted(int(i) for i in np.unique(np.asarray(q)))
    flat = q.getpalette() or []
    return [tuple(flat[3 * i : 3 * i + 3]) for i in used]  # type: ignore[misc]


def _map_to_palette(
    rgb: np.ndarray, colors: list[tuple[int, int, int]], dither: bool
) -> np.ndarray:
    src = Image.fromarray(rgb, "RGB")
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    mapped = src.quantize(palette=_palette_image(colors), dither=mode)
    idx = np.asarray(mapped).copy()
    # Guard against any out-of-range index (palette is exactly len(colors) entries).
    np.minimum(idx, len(colors) - 1, out=idx)
    return idx


def quantize(img_rgba: Image.Image, quality: Quality) -> Image.Image:
    """Convert an RGBA frame to a GIF-ready "P" image.

    `info["transparency"]` is set iff any pixel has alpha < 128; that palette index is
    reserved exclusively for transparent pixels. At most `quality.colors` indices are used.
    """
    if img_rgba.mode != "RGBA":
        raise ValueError(f"quantize expects an RGBA image, got {img_rgba.mode!r}")
    quality.validate()
    arr = np.asarray(img_rgba)
    rgb = np.ascontiguousarray(arr[..., :3])
    mask = arr[..., 3] < ALPHA_THRESHOLD

    if not mask.any():
        colors = _build_palette(rgb.reshape(-1, 3), quality.colors)
        idx = _map_to_palette(rgb, colors, quality.dither)
        return _make_p(idx, colors, None)

    if mask.all():
        idx = np.zeros(mask.shape, dtype=np.uint8)
        return _make_p(idx, [TRANSPARENT_RGB], 0)

    colors = _build_palette(rgb[~mask], quality.colors - 1)
    # Fill transparent pixels with an exact palette colour so they inject no dither error.
    filled = rgb.copy()
    filled[mask] = colors[0]
    idx = _map_to_palette(filled, colors, quality.dither)
    t_index = len(colors)
    idx[mask] = t_index
    return _make_p(idx, [*colors, TRANSPARENT_RGB], t_index)


def _make_p(
    idx: np.ndarray, colors: list[tuple[int, int, int]], transparency: int | None
) -> Image.Image:
    out = Image.fromarray(idx.astype(np.uint8), "P")
    out.putpalette([c for rgb in colors for c in rgb])
    if transparency is not None:
        out.info["transparency"] = transparency
    return out
