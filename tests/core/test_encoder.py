"""Tests for core/encoder.py (atomic streaming GIF writer)."""

from __future__ import annotations

import random
import struct
import threading
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gif_editor.core.decoder import GifSource
from gif_editor.core.encoder import Cancelled, estimate_size, read_back, write_gif

SIZE = (20, 10)


# ---------------------------------------------------------------- helpers


def pframe(color: tuple[int, int, int], box: tuple[int, int, int, int] | None = None):
    """P frame filled with `color` (index 0); `box` is painted with transparent index 1."""
    im = Image.new("P", SIZE, 0)
    im.putpalette([*color, 0, 0, 0])
    if box is not None:
        im.paste(1, box)
        im.info["transparency"] = 1
    return im


def quantized(color: tuple[int, int, int], size=SIZE) -> Image.Image:
    return Image.new("RGB", size, color).quantize(colors=4)


def noisy_frames(n: int, size=(64, 48), seed: int = 1) -> list[tuple[Image.Image, int]]:
    rng = random.Random(seed)
    palette = [rng.randrange(256) for _ in range(256 * 3)]
    out = []
    for _ in range(n):
        im = Image.frombytes("P", size, rng.randbytes(size[0] * size[1]))
        im.putpalette(palette)
        out.append((im, 4))
    return out


def gif_frames(path: Path) -> list[dict]:
    """Minimal GIF block parser: per frame its rect, disposal and transparency index."""
    d = path.read_bytes()
    assert d[:6] == b"GIF89a"
    i = 13
    if d[10] & 0x80:
        i += 3 * (2 << (d[10] & 7))
    frames, gce = [], None
    while True:
        b = d[i]
        if b == 0x3B:
            break
        if b == 0x21:
            label, j, blocks = d[i + 1], i + 2, []
            while d[j]:
                blocks.append(d[j + 1 : j + 1 + d[j]])
                j += 1 + d[j]
            if label == 0xF9:
                gce = blocks[0]
            i = j + 1
        elif b == 0x2C:
            rect = struct.unpack("<4H", d[i + 1 : i + 9])
            flags, j = d[i + 9], i + 10
            if flags & 0x80:
                j += 3 * (2 << (flags & 7))
            j += 1
            while d[j]:
                j += 1 + d[j]
            assert gce is not None
            frames.append(
                {
                    "rect": rect,
                    "disposal": (gce[0] >> 2) & 7,
                    "transparency": gce[3] if gce[0] & 1 else None,
                    "delay_cs": struct.unpack("<H", gce[1:3])[0],
                    "local_table": bool(flags & 0x80),
                }
            )
            gce, i = None, j + 1
        else:
            raise AssertionError(f"bad block 0x{b:02x} at {i}")
    return frames


def has_netscape(path: Path) -> bool:
    return b"NETSCAPE2.0" in path.read_bytes()


def has_global_table(path: Path) -> bool:
    return bool(path.read_bytes()[10] & 0x80)


def rgba_frames(path: Path) -> list[Image.Image]:
    with Image.open(path) as im:
        out = []
        for i in range(im.n_frames):
            im.seek(i)
            out.append(im.convert("RGBA"))
        return out


def expected_rgba(img: Image.Image) -> np.ndarray:
    """Input P frame as RGBA; transparent pixels normalised to (0, 0, 0, 0)."""
    pal = (img.getpalette("RGB") or []) + [0] * 768
    lut = np.zeros((256, 4), np.uint8)
    lut[:, :3] = np.array(pal[:768], np.uint8).reshape(256, 3)
    lut[:, 3] = 255
    t = img.info.get("transparency")
    if isinstance(t, int):
        lut[t] = 0
    return lut[np.asarray(img)]


def decoded_rgba(path: Path) -> list[np.ndarray]:
    with GifSource.open(path) as src:
        out = []
        for i in range(src.meta.frame_count):
            a = np.array(src.frame(i))
            a[a[..., 3] == 0] = 0
            out.append(a)
        return out


def assert_lossless(path: Path, frames) -> None:
    got = decoded_rgba(path)
    assert len(got) == len(frames)
    for k, ((img, _), g) in enumerate(zip(frames, got, strict=True)):
        exp = expected_rgba(img)
        bad = np.argwhere((exp != g).any(axis=2))
        assert bad.size == 0, f"frame {k}: {len(bad)} pixels differ, first at {bad[0]}"


def leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


# ---------------------------------------------------------------- basic writing


def test_basic_write_and_read_back(tmp_path: Path) -> None:
    frames = [
        (quantized(c), cs) for c, cs in [((255, 0, 0), 5), ((0, 255, 0), 7), ((0, 0, 255), 2)]
    ]
    out = write_gif(frames, tmp_path / "out.gif")
    assert out == tmp_path / "out.gif"
    count, durations = read_back(out)
    assert count == 3
    assert durations == [50, 70, 20]
    assert all(d % 10 == 0 for d in durations)
    with Image.open(out) as im:
        assert im.info["loop"] == 0
        assert im.size == SIZE
    assert all(f["rect"] == (0, 0, *SIZE) for f in gif_frames(out))
    assert all(f["disposal"] == 1 for f in gif_frames(out))  # no transparency anywhere
    assert leftovers(tmp_path) == []


def test_accepts_str_path_and_returns_path(tmp_path: Path) -> None:
    out = write_gif([(quantized((1, 2, 3)), 10)], str(tmp_path / "s.gif"))
    assert isinstance(out, Path)
    assert read_back(out) == (1, [100])


@pytest.mark.parametrize("loop", [0, 1, 5])
def test_loop_parameter_respected(tmp_path: Path, loop: int) -> None:
    frames = [(quantized((255, 0, 0)), 5), (quantized((0, 0, 255)), 5)]
    out = write_gif(frames, tmp_path / "l.gif", loop=loop)
    with Image.open(out) as im:
        assert im.info["loop"] == loop


def test_invalid_loop_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_gif([(quantized((0, 0, 0)), 5)], tmp_path / "x.gif", loop=-1)
    assert list(tmp_path.iterdir()) == []


def test_identical_frames_total_duration_exact(tmp_path: Path) -> None:
    red = quantized((255, 0, 0))
    delays = [3, 4, 5, 6, 7]
    frames = [(red.copy(), d) for d in delays[:3]] + [
        (quantized((0, 0, 255)), d) for d in delays[3:]
    ]
    out = write_gif(frames, tmp_path / "same.gif")
    count, durations = read_back(out)
    # Pillow's save_all would merge identical frames; this writer keeps them all.
    assert sum(durations) == sum(delays) * 10
    assert count == len(delays)
    assert durations == [d * 10 for d in delays]


# ---------------------------------------------------------------- transparency


def test_transparency_round_trip_first_frame(tmp_path: Path) -> None:
    frames = [
        (pframe((255, 0, 0), (0, 0, 5, 5)), 5),
        (pframe((0, 255, 0)), 5),
        (pframe((0, 0, 255), (10, 0, 20, 10)), 5),
    ]
    out = write_gif(frames, tmp_path / "t.gif")
    f0, f1, f2 = rgba_frames(out)
    assert f0.getpixel((0, 0))[3] == 0
    assert f0.getpixel((7, 7)) == (255, 0, 0, 255)
    assert f1.getpixel((0, 0)) == (0, 255, 0, 255)
    assert f2.getpixel((15, 5))[3] == 0  # not the previous green
    assert f2.getpixel((5, 5)) == (0, 0, 255, 255)
    # Only a frame followed by an opaque->transparent change is cleared (disposal 2);
    # the last one too because frame 0 (shown next when looping) is transparent.
    assert [f["disposal"] for f in gif_frames(out)] == [1, 2, 2]
    assert_lossless(out, frames)


def test_transparency_only_in_later_frames(tmp_path: Path) -> None:
    frames = [
        (pframe((255, 0, 0)), 5),
        (pframe((0, 255, 0)), 5),
        (pframe((0, 255, 0)), 5),
        (pframe((0, 0, 255), (10, 0, 20, 10)), 5),
        (pframe((9, 9, 9)), 5),
    ]
    out = write_gif(frames, tmp_path / "late.gif")
    imgs = rgba_frames(out)
    assert imgs[0].getpixel((15, 5)) == (255, 0, 0, 255)
    assert imgs[1].getpixel((15, 5)) == (0, 255, 0, 255)
    assert imgs[3].getpixel((15, 5))[3] == 0
    assert imgs[3].getpixel((5, 5)) == (0, 0, 255, 255)
    assert imgs[4].getpixel((15, 5)) == (9, 9, 9, 255)
    info = gif_frames(out)
    # Only the frame before the opaque->transparent change restores to background.
    assert [f["disposal"] for f in info] == [1, 1, 2, 1, 1]
    assert info[2]["rect"] == (0, 0, *SIZE)  # disposal 2 must clear the whole canvas
    assert info[3]["transparency"] == 1
    assert info[3]["rect"] == (0, 0, 10, 10)  # drawn on a blank canvas: opaque bbox only
    assert_lossless(out, frames)
    # Frame 0 was patched with an unused index so Pillow decodes the GIF as RGBA.
    assert info[0]["transparency"] is not None
    with Image.open(out) as im:
        assert im.histogram()[info[0]["transparency"]] == 0


def test_opaque_border_matching_first_transparent_colour_survives(tmp_path: Path) -> None:
    # Pillow's save_all crops this black bar away (it equals the first frame's
    # transparent colour) so viewers would show it as transparent.
    f0 = Image.new("P", SIZE, 1)
    f0.putpalette([0, 0, 0, 0, 255, 0])
    f0.paste(0, (0, 0, 20, 3))
    f0.info["transparency"] = 0
    f1 = Image.new("P", SIZE, 0)
    f1.putpalette([255, 0, 0, 0, 0, 0])
    f1.paste(1, (0, 0, 20, 3))
    f2 = Image.new("P", SIZE, 0)
    f2.putpalette([0, 0, 0])
    out = write_gif([(f0, 5), (f1, 5), (f2, 5)], tmp_path / "bar.gif")
    assert_lossless(out, [(f0, 5), (f1, 5), (f2, 5)])
    imgs = rgba_frames(out)
    assert imgs[0].getpixel((0, 0))[3] == 0
    assert imgs[1].getpixel((0, 0)) == (0, 0, 0, 255)
    assert imgs[2].getpixel((10, 5)) == (0, 0, 0, 255)


# ---------------------------------------------------------------- progress & cancel


def test_progress_reports_each_frame_with_total(tmp_path: Path) -> None:
    calls: list[tuple[int, int | None]] = []
    frames = [(quantized((i * 40, 0, 0)), 5) for i in range(5)]
    write_gif(iter(frames), tmp_path / "p.gif", total=5, progress=lambda d, t: calls.append((d, t)))
    assert calls == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


def test_progress_total_none_by_default(tmp_path: Path) -> None:
    calls: list[tuple[int, int | None]] = []
    write_gif(
        [(quantized((0, 0, 0)), 5)] * 2, tmp_path / "p.gif", progress=lambda *a: calls.append(a)
    )
    assert calls == [(1, None), (2, None)]


def test_frames_consumed_lazily(tmp_path: Path) -> None:
    consumed: list[int] = []
    progress_seen: list[int] = []

    def gen() -> Iterator[tuple[Image.Image, int]]:
        for i in range(4):
            consumed.append(i)
            assert len(progress_seen) == i  # progress fired for every earlier frame
            yield quantized((i * 50, 0, 0)), 5

    write_gif(gen(), tmp_path / "lazy.gif", progress=lambda d, t: progress_seen.append(d))
    assert consumed == [0, 1, 2, 3]


def test_cancel_mid_way(tmp_path: Path) -> None:
    dest = tmp_path / "keep.gif"
    dest.write_bytes(b"old content")
    cancel = threading.Event()
    pulled: list[int] = []

    def gen() -> Iterator[tuple[Image.Image, int]]:
        for i in range(10):
            pulled.append(i)
            yield quantized((i * 20, 0, 0)), 5

    def progress(done: int, total: int | None) -> None:
        if done == 3:
            cancel.set()

    with pytest.raises(Cancelled):
        write_gif(gen(), dest, total=10, progress=progress, cancel=cancel)
    assert pulled == [0, 1, 2]
    assert dest.read_bytes() == b"old content"
    assert leftovers(tmp_path) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.gif"]


def test_cancel_after_last_frame_still_cancels(tmp_path: Path) -> None:
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        write_gif(
            [(quantized((0, 0, 0)), 5)],
            tmp_path / "c.gif",
            progress=lambda d, t: cancel.set(),
            cancel=cancel,
        )
    assert list(tmp_path.iterdir()) == []


def test_generator_exception_cleans_up(tmp_path: Path) -> None:
    dest = tmp_path / "keep.gif"
    dest.write_bytes(b"old content")

    def gen() -> Iterator[tuple[Image.Image, int]]:
        yield quantized((255, 0, 0)), 5
        yield quantized((0, 255, 0)), 5
        raise RuntimeError("render failed")

    with pytest.raises(RuntimeError, match="render failed"):
        write_gif(gen(), dest)
    assert dest.read_bytes() == b"old content"
    assert leftovers(tmp_path) == []


def test_new_destination_not_created_on_error(tmp_path: Path) -> None:
    def gen() -> Iterator[tuple[Image.Image, int]]:
        yield quantized((255, 0, 0)), 5
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        write_gif(gen(), tmp_path / "new.gif")
    assert list(tmp_path.iterdir()) == []


def test_overwrites_existing_destination_on_success(tmp_path: Path) -> None:
    dest = tmp_path / "o.gif"
    dest.write_bytes(b"old")
    write_gif([(quantized((1, 1, 1)), 5)], dest)
    assert read_back(dest) == (1, [50])


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("delay", [1, 0, -5, 70000, 2.5, True])
def test_invalid_delay_rejected(tmp_path: Path, delay: object) -> None:
    dest = tmp_path / "d.gif"
    dest.write_bytes(b"old")
    with pytest.raises(ValueError):
        write_gif([(quantized((0, 0, 0)), 5), (quantized((9, 9, 9)), delay)], dest)  # type: ignore[list-item]
    assert dest.read_bytes() == b"old"
    assert leftovers(tmp_path) == []


def test_mismatched_sizes_rejected(tmp_path: Path) -> None:
    frames = [(quantized((0, 0, 0)), 5), (quantized((0, 0, 0), size=(21, 10)), 5)]
    with pytest.raises(ValueError, match="size"):
        write_gif(frames, tmp_path / "m.gif")
    assert list(tmp_path.iterdir()) == []


def test_non_p_mode_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        write_gif([(Image.new("RGB", SIZE), 5)], tmp_path / "rgb.gif")
    assert list(tmp_path.iterdir()) == []


def test_empty_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_gif([], tmp_path / "e.gif")
    with pytest.raises(ValueError):
        write_gif(iter(()), tmp_path / "e.gif")
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- misc


def test_non_ascii_filename(tmp_path: Path) -> None:
    dest = tmp_path / "çıktı ğ.gif"  # noqa: RUF001
    out = write_gif([(quantized((255, 0, 0)), 5), (quantized((0, 255, 0)), 6)], dest)
    assert out == dest and dest.exists()
    assert read_back(dest) == (2, [50, 60])
    assert leftovers(tmp_path) == []


def test_full_256_colour_palette(tmp_path: Path) -> None:
    frames = noisy_frames(3, size=(32, 32))
    out = write_gif(frames, tmp_path / "n.gif")
    imgs = rgba_frames(out)
    for (src, _), got in zip(frames, imgs, strict=True):
        assert got.convert("RGB").tobytes() == src.convert("RGB").tobytes()


def test_read_back_static_gif(tmp_path: Path) -> None:
    p = tmp_path / "static.gif"
    quantized((1, 2, 3)).save(p)
    assert read_back(p) == (1, [0])


def test_estimate_size_within_tolerance(tmp_path: Path) -> None:
    frames = noisy_frames(20)
    real = write_gif(frames, tmp_path / "noise.gif").stat().st_size
    est = estimate_size(frames[:5], 20)
    assert abs(est - real) <= 0.35 * real


def test_estimate_size_edge_cases() -> None:
    assert estimate_size([], 10) == 0
    frames = noisy_frames(2, size=(16, 16))
    one = estimate_size(frames[:1], 1)
    assert one > 0
    assert estimate_size(frames[:1], 10) > one
    assert estimate_size(frames, 0) == 0


# ---------------------------------------------------------------- loop & verify


def test_loop_none_writes_no_netscape_block(tmp_path: Path) -> None:
    frames = [(quantized((255, 0, 0)), 5), (quantized((0, 0, 255)), 5)]
    once = write_gif(frames, tmp_path / "once.gif", loop=None)
    assert not has_netscape(once)
    with Image.open(once) as im:
        assert "loop" not in im.info
    assert read_back(once) == (2, [50, 50])
    forever = write_gif(frames, tmp_path / "forever.gif")
    assert has_netscape(forever)


def test_verify_success_runs_on_temp_before_replace(tmp_path: Path) -> None:
    dest = tmp_path / "v.gif"
    dest.write_bytes(b"old")
    seen: list[tuple[Path, tuple[int, list[int]], bytes]] = []

    def verify(p: Path) -> None:
        seen.append((p, read_back(p), dest.read_bytes()))

    frames = [(quantized((255, 0, 0)), 5), (quantized((0, 255, 0)), 7)]
    out = write_gif(frames, dest, verify=verify)
    assert len(seen) == 1
    tmp, info, dest_then = seen[0]
    assert tmp != dest and tmp.parent == tmp_path and tmp.name.endswith(".tmp")
    assert info == (2, [50, 70])
    assert dest_then == b"old"  # destination not yet replaced while verifying
    assert read_back(out) == (2, [50, 70])
    assert leftovers(tmp_path) == []


def test_verify_failure_keeps_destination(tmp_path: Path) -> None:
    dest = tmp_path / "v.gif"
    dest.write_bytes(b"old")

    def verify(p: Path) -> None:
        assert p.exists()
        raise RuntimeError("bad output")

    with pytest.raises(RuntimeError, match="bad output"):
        write_gif([(quantized((255, 0, 0)), 5)], dest, verify=verify)
    assert dest.read_bytes() == b"old"
    assert leftovers(tmp_path) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["v.gif"]


# ---------------------------------------------------------------- differencing


def shared_frame(idx: np.ndarray, palette: list[int], t: int | None) -> Image.Image:
    im = Image.fromarray(idx.astype(np.uint8), "P")
    im.putpalette(palette)
    if t is not None and (idx == t).any():
        im.info["transparency"] = t
    return im


def test_diff_frames_write_only_changed_rect(tmp_path: Path) -> None:
    pal = [v for i in range(16) for v in (i * 16, 255 - i * 16, i * 8)]
    base = np.tile(np.arange(16, dtype=np.uint8) % 16, (24, 3))[:, :40]  # 40x24
    frames = []
    for k in range(4):
        a = base.copy()
        a[5:9, 3 + k * 5 : 7 + k * 5] = 15 - (k % 2)
        frames.append((shared_frame(a, pal, None), 4))
    frames.append((frames[-1][0].copy(), 6))  # identical frame: kept, 1x1 rect
    out = write_gif(frames, tmp_path / "d.gif")
    info = gif_frames(out)
    assert len(info) == 5 and [f["delay_cs"] for f in info] == [4, 4, 4, 4, 6]
    assert info[0]["rect"] == (0, 0, 40, 24)
    # frame 1 differs from frame 0 in x 3..11, y 5..8
    assert info[1]["rect"] == (3, 5, 9, 4)
    assert info[4]["rect"][2:] == (1, 1)
    assert all(f["disposal"] == 1 for f in info)
    # One shared palette: global colour table only.
    assert has_global_table(out)
    assert not any(f["local_table"] for f in info)
    # Unchanged pixels inside a rect are marked with an index no changed pixel uses.
    assert info[1]["transparency"] is not None
    assert_lossless(out, frames)
    for (src, _), got in zip(frames, rgba_frames(out), strict=True):
        assert got.convert("RGB").tobytes() == src.convert("RGB").tobytes()


def test_differing_palettes_keep_local_tables(tmp_path: Path) -> None:
    frames = [(quantized(c), 5) for c in [(255, 0, 0), (0, 255, 0), (0, 255, 0)]]
    frames[2] = (pframe((0, 255, 0)), 5)  # same colour, different palette
    out = write_gif(frames, tmp_path / "loc.gif")
    info = gif_frames(out)
    assert info[0]["local_table"] is False  # first palette is the global table
    assert info[1]["local_table"] is True
    assert_lossless(out, frames)
    # Frame 2 decodes identically to frame 1 -> nothing changed -> 1x1 rect.
    assert info[2]["rect"][2:] == (1, 1)


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("shared", [True, False])
@pytest.mark.parametrize("loop", [0, None])
def test_random_animation_lossless(tmp_path: Path, seed: int, shared: bool, loop) -> None:
    """Random moving blobs with appearing/disappearing transparency round-trip exactly."""
    rng = np.random.default_rng(seed)
    w, h, n = 23, 17, 12
    n_col = int(rng.choice([3, 16, 255]))
    t = n_col  # reserved transparent index (shared mode)
    pal = rng.integers(0, 256, 3 * (n_col + 1)).tolist()
    canvas = rng.integers(0, n_col, (h, w))
    frames = []
    for _ in range(n):
        canvas = canvas.copy()
        for _ in range(int(rng.integers(0, 4))):
            x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
            bw, bh = int(rng.integers(1, 8)), int(rng.integers(1, 6))
            fill = t if rng.random() < 0.3 else int(rng.integers(0, n_col))
            canvas[y : y + bh, x : x + bw] = fill
        if shared:
            frames.append((shared_frame(canvas, pal, t), int(rng.integers(2, 9))))
        else:
            # Per-frame permuted palette: same colours, different indices.
            perm = rng.permutation(n_col)
            idx = np.where(canvas == t, t, perm[np.minimum(canvas, n_col - 1)])
            p = np.array(pal[: 3 * n_col]).reshape(-1, 3)
            new_pal = np.zeros((n_col + 1, 3), int)
            new_pal[perm] = p
            frames.append((shared_frame(idx, new_pal.ravel().tolist(), t), int(rng.integers(2, 9))))
    out = write_gif(frames, tmp_path / "r.gif", loop=loop)
    assert read_back(out) == (n, [d * 10 for _, d in frames])
    assert_lossless(out, frames)
    if shared:
        assert not any(f["local_table"] for f in gif_frames(out))


def test_full_palette_partial_change_lossless(tmp_path: Path) -> None:
    """All 256 indices used: no free marker index frame-wide, still exact."""
    frames = noisy_frames(1, size=(32, 32))
    im0 = frames[0][0]
    a = np.array(im0)
    a[4:20, 4:20] = np.arange(256, dtype=np.uint8).reshape(16, 16)[::-1]
    im1 = Image.fromarray(a, "P")
    im1.putpalette(im0.getpalette())
    frames.append((im1, 4))
    out = write_gif(frames, tmp_path / "full.gif")
    info = gif_frames(out)
    assert info[1]["rect"] == (4, 4, 16, 16)
    assert_lossless(out, frames)
