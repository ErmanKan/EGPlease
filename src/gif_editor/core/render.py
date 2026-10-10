"""Per-frame render pipeline: crop -> resize (premultiplied LANCZOS) -> quantize."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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


def _palette_image(colors: Sequence[tuple[int, int, int]]) -> Image.Image:
    pal = Image.new("P", (1, 1))
    pal.putpalette([c for rgb in colors for c in rgb])
    return pal


@dataclass(frozen=True, slots=True)
class Palette:
    """A palette shared by every frame of one output GIF.

    ``colors`` are the opaque colours (palette indices ``0..len(colors)-1``).  When
    ``transparent`` is true one extra index, ``len(colors)``, is reserved exclusively
    for transparent pixels.  At most 256 entries in total.
    """

    colors: tuple[tuple[int, int, int], ...]
    transparent: bool = False

    def __post_init__(self) -> None:
        if not self.colors:
            raise ValueError("a palette needs at least one colour")
        if len(self.colors) + int(self.transparent) > 256:
            raise ValueError("a palette holds at most 256 entries")

    @property
    def transparent_index(self) -> int | None:
        return len(self.colors) if self.transparent else None

    @property
    def size(self) -> int:
        """Number of palette entries including the reserved transparent slot."""
        return len(self.colors) + int(self.transparent)

    def flat(self) -> list[int]:
        """Flat RGB list for ``Image.putpalette`` (transparent slot included)."""
        colors = [*self.colors, TRANSPARENT_RGB] if self.transparent else list(self.colors)
        return [c for rgb in colors for c in rgb]


PALETTE_SAMPLE_FRAMES = 16
PALETTE_SAMPLE_PIXELS = 1 << 20  # total pixels fed to median cut
EXACT_SCAN_PIXELS = 1 << 23  # scan this many pixels for "few colours -> exact palette"


def sample_indices(count: int, max_samples: int = PALETTE_SAMPLE_FRAMES) -> list[int]:
    """Up to ``max_samples`` evenly spaced indices in ``range(count)`` (first and last kept)."""
    if count <= 0:
        return []
    if count <= max_samples:
        return list(range(count))
    return sorted({round(i * (count - 1) / (max_samples - 1)) for i in range(max_samples)})


def build_palette(
    sample_rgba_frames: Sequence[Image.Image], quality: Quality, *, transparent: bool = False
) -> Palette:
    """Build one palette for a whole animation from (rendered) RGBA sample frames.

    Up to 16 evenly spaced frames of ``sample_rgba_frames`` are used.  If their opaque
    pixels contain few enough distinct colours, those colours are used exactly;
    otherwise a median cut runs over a deterministic pixel subsample.  One index is
    reserved for transparency when ``transparent`` is true or any sampled pixel has
    alpha < 128.  The palette has at most ``quality.colors`` entries in total.
    """
    quality.validate()
    if not sample_rgba_frames:
        raise ValueError("build_palette needs at least one sample frame")
    frames = [sample_rgba_frames[i] for i in sample_indices(len(sample_rgba_frames))]
    opaque: list[np.ndarray] = []
    reserve = transparent
    for img in frames:
        if img.mode != "RGBA":
            raise ValueError(f"build_palette expects RGBA images, got {img.mode!r}")
        arr = np.asarray(img).reshape(-1, 4)
        alpha_ok = arr[:, 3] >= ALPHA_THRESHOLD
        if not alpha_ok.all():
            reserve = True
        opaque.append(arr[alpha_ok, :3])
    pixels = np.concatenate(opaque) if opaque else np.zeros((0, 3), np.uint8)
    n_opaque = quality.colors - int(reserve)
    if len(pixels) == 0:
        return Palette((TRANSPARENT_RGB,), reserve)
    scan = pixels
    if len(scan) > EXACT_SCAN_PIXELS:
        scan = scan[:: -(-len(scan) // EXACT_SCAN_PIXELS)]
    packed = scan[:, 0].astype(np.uint32) << 16 | scan[:, 1].astype(np.uint32) << 8 | scan[:, 2]
    unique = np.unique(packed)
    if len(unique) <= n_opaque and scan is pixels:
        colors = tuple(
            (int(v >> 16) & 255, int(v >> 8) & 255, int(v) & 255) for v in unique.tolist()
        )
        return Palette(colors, reserve)
    if len(pixels) > PALETTE_SAMPLE_PIXELS:
        rng = np.random.default_rng(0x61F)  # deterministic subsample
        pixels = pixels[rng.choice(len(pixels), PALETTE_SAMPLE_PIXELS, replace=False)]
    return Palette(tuple(_build_palette(pixels, n_opaque)), reserve)


def _build_palette(rgb_pixels: np.ndarray, n: int) -> list[tuple[int, int, int]]:
    """Median-cut palette (<= n colours) for an (N, 3) uint8 pixel array."""
    strip = Image.fromarray(np.ascontiguousarray(rgb_pixels.reshape(1, -1, 3)), "RGB")
    q = strip.quantize(n, Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    used = sorted(int(i) for i in np.unique(np.asarray(q)))
    flat = q.getpalette() or []
    return [tuple(flat[3 * i : 3 * i + 3]) for i in used]  # type: ignore[misc]


def _map_to_palette(
    rgb: np.ndarray, colors: Sequence[tuple[int, int, int]], dither: bool
) -> np.ndarray:
    src = Image.fromarray(np.ascontiguousarray(rgb), "RGB")
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    mapped = src.quantize(palette=_palette_image(colors), dither=mode)
    idx = np.asarray(mapped).copy()
    if idx.size and int(idx.max()) >= len(colors):
        raise RuntimeError(
            f"palette mapping produced index {int(idx.max())} for a {len(colors)}-colour palette"
        )
    return idx


def quantize(
    img_rgba: Image.Image,
    quality: Quality,
    palette: Palette | None = None,
    previous: tuple[Image.Image, Image.Image] | None = None,
) -> Image.Image:
    """Convert an RGBA frame to a GIF-ready "P" image.

    `info["transparency"]` is set iff any pixel has alpha < 128; that palette index is
    reserved exclusively for transparent pixels.

    Without `palette` a per-frame median-cut palette of <= `quality.colors` entries is
    built.  With a shared `palette` (see `build_palette`) the frame is mapped onto it
    and the returned image carries exactly that palette (`palette.flat()`), so frames
    of one animation are index-compatible; a transparent pixel then requires
    `palette.transparent`.  `previous=(prev_rgba, prev_p)` (shared palette only) keeps
    the previous output index wherever the source pixel is unchanged and opaque in
    both frames, so Floyd-Steinberg dithering cannot make a static background shimmer.
    """
    if img_rgba.mode != "RGBA":
        raise ValueError(f"quantize expects an RGBA image, got {img_rgba.mode!r}")
    quality.validate()
    if palette is not None:
        return _quantize_shared(img_rgba, quality, palette, previous)
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


def _quantize_shared(
    img_rgba: Image.Image,
    quality: Quality,
    palette: Palette,
    previous: tuple[Image.Image, Image.Image] | None,
) -> Image.Image:
    arr = np.asarray(img_rgba)
    rgb = np.ascontiguousarray(arr[..., :3])
    mask = arr[..., 3] < ALPHA_THRESHOLD
    any_t = bool(mask.any())
    if any_t and not palette.transparent:
        raise ValueError("frame has transparent pixels but the palette reserves no index")
    if any_t:
        filled = rgb.copy()
        filled[mask] = palette.colors[0]  # exact colour: injects no dither error
    else:
        filled = rgb
    idx = _map_to_palette(filled, palette.colors, quality.dither)
    if previous is not None and quality.dither:
        prev_rgba, prev_p = previous
        if prev_rgba.size != img_rgba.size or prev_p.size != img_rgba.size:
            raise ValueError("previous frame size differs")
        parr = np.asarray(prev_rgba)
        keep = ~mask & (parr[..., 3] >= ALPHA_THRESHOLD) & (parr[..., :3] == rgb).all(axis=2)
        prev_idx = np.asarray(prev_p)
        keep &= prev_idx < len(palette.colors)
        idx[keep] = prev_idx[keep]
    if any_t:
        idx[mask] = palette.transparent_index
    out = Image.fromarray(idx.astype(np.uint8), "P")
    out.putpalette(palette.flat())
    if any_t:
        out.info["transparency"] = palette.transparent_index
    return out


def _make_p(
    idx: np.ndarray, colors: list[tuple[int, int, int]], transparency: int | None
) -> Image.Image:
    out = Image.fromarray(idx.astype(np.uint8), "P")
    out.putpalette([c for rgb in colors for c in rgb])
    if transparency is not None:
        out.info["transparency"] = transparency
    return out
