"""Tests for core.render: output size, crop/resize pipeline and GIF quantization."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from gif_editor.core.models import CropRect, OutputSize, Quality
from gif_editor.core.render import output_dimensions, quantize, render_frame


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
