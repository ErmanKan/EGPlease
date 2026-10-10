"""Tests for core.render: output size, crop/resize pipeline and GIF quantization."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from gif_editor.core import render
from gif_editor.core.models import CropRect, OutputSize, Quality
from gif_editor.core.render import (
    Palette,
    build_palette,
    output_dimensions,
    quantize,
    render_frame,
    sample_indices,
)


def _gradient(w: int = 256, h: int = 32) -> Image.Image:
    a = np.zeros((h, w, 4), np.uint8)
    x = np.linspace(0, 255, w).astype(np.uint8)
    a[..., 0] = x
    a[..., 1] = x[::-1]
    a[..., 2] = np.linspace(0, 255, h).astype(np.uint8)[:, None]
    a[..., 3] = 255
    return Image.fromarray(a, "RGBA")


def _indices(img: Image.Image) -> np.ndarray:
    return np.asarray(img)


# --- output_dimensions -------------------------------------------------------


def test_output_dimensions_canvas() -> None:
    assert output_dimensions(100, 50, None, None) == (100, 50)


def test_output_dimensions_crop() -> None:
    assert output_dimensions(100, 50, CropRect(5, 5, 30, 20), None) == (30, 20)


def test_output_dimensions_size_wins() -> None:
    assert output_dimensions(100, 50, CropRect(5, 5, 30, 20), OutputSize(60, 40)) == (60, 40)
    assert output_dimensions(100, 50, None, OutputSize(7, 9)) == (7, 9)


# --- render_frame ------------------------------------------------------------


def test_crop_exact_pixels() -> None:
    a = np.arange(10 * 8 * 4, dtype=np.uint32).reshape(8, 10, 4) % 256
    img = Image.fromarray(a.astype(np.uint8), "RGBA")
    out = render_frame(img, CropRect(2, 3, 4, 5), None)
    assert out.size == (4, 5)
    assert out.mode == "RGBA"
    assert np.array_equal(np.asarray(out), np.asarray(img)[3:8, 2:6])


def test_crop_out_of_bounds_raises() -> None:
    img = Image.new("RGBA", (10, 10))
    with pytest.raises(ValueError):
        render_frame(img, CropRect(5, 5, 10, 10), None)


def test_resize_dimensions() -> None:
    img = _gradient(40, 30)
    out = render_frame(img, None, OutputSize(17, 11))
    assert out.size == (17, 11) and out.mode == "RGBA"
    out2 = render_frame(img, CropRect(0, 0, 20, 20), OutputSize(50, 60))
    assert out2.size == (50, 60)


def test_same_size_returns_copy_equal() -> None:
    img = _gradient(20, 10)
    out = render_frame(img, None, OutputSize(20, 10))
    assert out is not img
    assert np.array_equal(np.asarray(out), np.asarray(img))


def test_premultiplied_resize_no_dark_fringe() -> None:
    a = np.zeros((20, 20, 4), np.uint8)  # right half: transparent black
    a[:, :10] = (255, 0, 0, 128)  # left half: half-transparent red
    img = Image.fromarray(a, "RGBA")
    for size in (OutputSize(7, 7), OutputSize(33, 33)):
        out = np.asarray(render_frame(img, None, size)).astype(int)
        visible = out[..., 3] >= 8
        assert visible.any()
        px = out[visible]
        assert (px[:, 0] >= 240).all(), "red channel darkened at transparent edge"
        assert (px[:, 1] <= 10).all() and (px[:, 2] <= 10).all()


def test_non_rgba_raises() -> None:
    with pytest.raises(ValueError):
        render_frame(Image.new("RGB", (4, 4)), None, None)
    with pytest.raises(ValueError):
        quantize(Image.new("P", (4, 4)), Quality())


def test_input_not_mutated() -> None:
    img = _gradient(30, 20)
    before = np.asarray(img).copy()
    render_frame(img, CropRect(1, 1, 10, 10), OutputSize(25, 25))
    quantize(img, Quality(16, True))
    assert img.mode == "RGBA" and img.size == (30, 20)
    assert np.array_equal(np.asarray(img), before)


# --- quantize: opaque ----------------------------------------------------------


@pytest.mark.parametrize("n", [2, 16, 256])
def test_quantize_opaque(n: int) -> None:
    for dither in (False, True):
        q = quantize(_gradient(), Quality(n, dither))
        assert q.mode == "P"
        assert "transparency" not in q.info
        idx = _indices(q)
        assert len(np.unique(idx)) <= n
        assert idx.max() < len(q.getpalette()) // 3 <= n


def test_quantize_dither_changes_result() -> None:
    img = _gradient()
    a = _indices(quantize(img, Quality(8, False)))
    b = _indices(quantize(img, Quality(8, True)))
    assert not np.array_equal(a, b)


def test_quantize_deterministic() -> None:
    img = _gradient()
    a = quantize(img, Quality(32, True))
    b = quantize(img, Quality(32, True))
    assert np.array_equal(_indices(a), _indices(b))
    assert a.getpalette() == b.getpalette()


def test_quantize_colors_reasonable() -> None:
    a = np.zeros((4, 4, 4), np.uint8)
    a[:, :2] = (255, 0, 0, 255)
    a[:, 2:] = (0, 0, 255, 255)
    q = quantize(Image.fromarray(a, "RGBA"), Quality(2, False))
    rgb = np.asarray(q.convert("RGB"))
    assert np.array_equal(rgb, a[..., :3])


# --- quantize: transparency ----------------------------------------------------


def _with_alpha(alpha_fn) -> tuple[Image.Image, np.ndarray]:
    img = np.array(_gradient(64, 32))
    img[..., 3] = alpha_fn(img.shape[:2])
    return Image.fromarray(img, "RGBA"), img[..., 3] < 128


@pytest.mark.parametrize("n", [2, 3, 16, 256])
@pytest.mark.parametrize("dither", [False, True])
def test_quantize_transparency(n: int, dither: bool) -> None:
    def alpha(shape):
        a = np.full(shape, 255, np.uint8)
        a[:, :20] = 0
        a[10:20, 30:50] = 50
        return a

    img, mask = _with_alpha(alpha)
    q = quantize(img, Quality(n, dither))
    assert q.mode == "P"
    t = q.info["transparency"]
    idx = _indices(q)
    assert (idx[mask] == t).all()
    assert (idx[~mask] != t).all()
    assert len(np.unique(idx)) <= n
    assert len(q.getpalette()) // 3 <= n


def test_alpha_boundary_127_128() -> None:
    a = np.zeros((2, 2, 4), np.uint8)
    a[..., 0] = 200
    a[0, 0, 3] = 127
    a[0, 1, 3] = 128
    a[1, 0, 3] = 0
    a[1, 1, 3] = 255
    q = quantize(Image.fromarray(a, "RGBA"), Quality(4, False))
    t = q.info["transparency"]
    idx = _indices(q)
    assert idx[0, 0] == t and idx[1, 0] == t
    assert idx[0, 1] != t and idx[1, 1] != t


def test_no_transparency_key_when_alpha_128() -> None:
    img = Image.new("RGBA", (4, 4), (10, 20, 30, 128))
    assert "transparency" not in quantize(img, Quality(4)).info


def test_fully_transparent_frame() -> None:
    img = Image.new("RGBA", (8, 6), (255, 255, 255, 0))
    q = quantize(img, Quality(2, True))
    t = q.info["transparency"]
    assert (_indices(q) == t).all()
    assert len(q.getpalette()) // 3 <= 2


def test_gif_round_trip_transparency(tmp_path) -> None:
    def alpha(shape):
        a = np.full(shape, 255, np.uint8)
        a[:, 40:] = 0
        return a

    img, mask = _with_alpha(alpha)
    q = quantize(img, Quality(16, True))
    path = tmp_path / "out.gif"
    q.save(path)
    with Image.open(path) as re:
        back = np.asarray(re.convert("RGBA"))
    assert (back[mask][:, 3] == 0).all()
    assert (back[~mask][:, 3] == 255).all()


# --- shared palette ----------------------------------------------------------------


def _moving(n: int = 6, w: int = 48, h: int = 24, alpha: bool = False) -> list[Image.Image]:
    out = []
    for i in range(n):
        a = np.array(_gradient(w, h))
        a[8:14, 2 + i * 6 : 8 + i * 6] = (250, 250, 30, 255)
        if alpha:
            a[:4, :] = (0, 0, 0, 0)
        out.append(Image.fromarray(a, "RGBA"))
    return out


def test_sample_indices() -> None:
    assert sample_indices(0) == []
    assert sample_indices(5) == [0, 1, 2, 3, 4]
    s = sample_indices(100)
    assert len(s) == 16 and s[0] == 0 and s[-1] == 99 and s == sorted(set(s))
    assert sample_indices(100, 4) == [0, 33, 66, 99]


def test_palette_dataclass() -> None:
    p = Palette(((1, 2, 3), (4, 5, 6)), transparent=True)
    assert p.transparent_index == 2 and p.size == 3
    assert p.flat() == [1, 2, 3, 4, 5, 6, *render.TRANSPARENT_RGB]
    assert Palette(((1, 2, 3),)).transparent_index is None
    with pytest.raises(ValueError):
        Palette(())
    with pytest.raises(ValueError):
        Palette(tuple((i, i, i) for i in range(256)), transparent=True)


def test_build_palette_exact_for_few_colours() -> None:
    frames = [Image.new("RGBA", (8, 8), (*c, 255)) for c in [(255, 0, 0), (0, 9, 200)]]
    p = build_palette(frames, Quality(256))
    assert set(p.colors) == {(255, 0, 0), (0, 9, 200)} and not p.transparent


@pytest.mark.parametrize("n", [2, 16, 255, 256])
def test_build_palette_respects_colour_budget(n: int) -> None:
    for alpha in (False, True):
        p = build_palette(_moving(alpha=alpha), Quality(n))
        assert p.transparent is alpha
        assert p.size <= n


def test_build_palette_transparency_flag_and_detection() -> None:
    assert build_palette(_moving(), Quality(16), transparent=True).transparent
    assert build_palette(_moving(alpha=True), Quality(16)).transparent
    p = build_palette([Image.new("RGBA", (4, 4), (0, 0, 0, 0))], Quality(4))
    assert p.transparent and p.size == 2


def test_build_palette_deterministic_and_validates() -> None:
    frames = _moving(20)
    assert build_palette(frames, Quality(32)) == build_palette(frames, Quality(32))
    with pytest.raises(ValueError):
        build_palette([], Quality())
    with pytest.raises(ValueError):
        build_palette([Image.new("RGB", (2, 2))], Quality())


def test_build_palette_uses_at_most_16_frames() -> None:
    seen: list[int] = []

    class Spy(list):
        def __getitem__(self, i):
            seen.append(i)
            return list.__getitem__(self, i)

    build_palette(Spy(_moving(40, 16, 8)), Quality(16))
    assert len(seen) <= 16 and 0 in seen and 39 in seen


@pytest.mark.parametrize("dither", [False, True])
def test_quantize_onto_shared_palette(dither: bool) -> None:
    frames = _moving(alpha=True)
    pal = build_palette(frames, Quality(32, dither))
    outs = [quantize(f, Quality(32, dither), pal) for f in frames]
    for f, q in zip(frames, outs, strict=True):
        assert q.getpalette() == pal.flat()
        idx = _indices(q)
        mask = np.asarray(f)[..., 3] < 128
        assert q.info["transparency"] == pal.transparent_index
        assert (idx[mask] == pal.transparent_index).all()
        assert (idx[~mask] < len(pal.colors)).all()


def test_quantize_shared_exact_colours_and_dither_flag() -> None:
    img = _gradient()
    pal = build_palette([img], Quality(8))
    a = _indices(quantize(img, Quality(8, False), pal))
    b = _indices(quantize(img, Quality(8, True), pal))
    assert not np.array_equal(a, b)
    solid = Image.new("RGBA", (5, 5), (*pal.colors[3], 255))
    assert (_indices(quantize(solid, Quality(8, True), pal)) == 3).all()


def test_quantize_shared_opaque_palette_rejects_transparent_frame() -> None:
    pal = Palette(((255, 0, 0),))
    with pytest.raises(ValueError, match="transparent"):
        quantize(Image.new("RGBA", (2, 2), (0, 0, 0, 0)), Quality(4), pal)
    q = quantize(Image.new("RGBA", (2, 2), (250, 0, 0, 255)), Quality(4), pal)
    assert "transparency" not in q.info


def test_previous_keeps_indices_of_unchanged_pixels() -> None:
    frames = _moving(2)
    q = Quality(16, True)
    pal = build_palette(frames, q)
    p0 = quantize(frames[0], q, pal)
    free = _indices(quantize(frames[1], q, pal))
    stable = _indices(quantize(frames[1], q, pal, (frames[0], p0)))
    same = (np.asarray(frames[0]) == np.asarray(frames[1])).all(axis=2)
    assert np.array_equal(stable[same], _indices(p0)[same])
    assert np.array_equal(stable[~same], free[~same])
    assert not np.array_equal(free[same], _indices(p0)[same])  # FS alone would shimmer


def test_map_to_palette_raises_on_out_of_range(monkeypatch) -> None:
    real = Image.Image.quantize

    def bad(self, *a, **kw):
        out = real(self, *a, **kw)
        return Image.fromarray(np.full(out.size[::-1], 7, np.uint8), "P")

    monkeypatch.setattr(Image.Image, "quantize", bad)
    with pytest.raises(RuntimeError, match="index 7"):
        render._map_to_palette(np.zeros((2, 2, 3), np.uint8), [(0, 0, 0), (9, 9, 9)], False)
