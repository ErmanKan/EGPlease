"""GifSource against the generated corpus and the browser reference compositor.

``tests/core/test_corpus.py`` documents where raw Pillow differs from browsers (xfails on
``disposal_background`` frames 2 and 3); here the same entries must pass for our decoder.
"""

from __future__ import annotations

import random
import subprocess
import sys
import textwrap
import time
import tracemalloc
from pathlib import Path

import pytest
from PIL import Image

import corpus as C
from corpus import Expected, FrameSpec, GifSpec
from gif_editor.core.decoder import GifLoadError, GifSource, Limits


def _write(tmp_path: Path, spec: GifSpec, name: str = "x.gif") -> Path:
    path = tmp_path / name
    path.write_bytes(C.encode_gif(spec)[0])
    return path


def _assert_frames(src: GifSource, expected: list[Image.Image] | tuple[Image.Image, ...]) -> None:
    for i, exp in enumerate(expected):
        assert C.normalize_rgba(src.frame(i)) == C.normalize_rgba(exp), f"frame {i}"


# --- corpus entries ----------------------------------------------------------------------


@pytest.mark.parametrize("name", C.VALID_ENTRIES)
def test_valid_entry_matches_reference(name: str, corpus: dict[str, tuple[Path, Expected]]):
    path, exp = corpus[name]
    with GifSource.open(path) as src:
        m = src.meta
        assert (m.width, m.height) == exp.canvas_size
        assert m.frame_count == exp.frame_count
        assert m.loop == exp.loop
        assert tuple(f.delay_ms for f in m.frames) == exp.delays_ms
        assert m.delays_ms == tuple(100 if d <= 10 else d for d in exp.delays_ms)
        assert m.has_transparency == exp.has_transparency
        assert src.warnings == []
        _assert_frames(src, exp.frames)


@pytest.mark.parametrize("name", C.VALID_ENTRIES)
def test_valid_entry_backward_with_tiny_cache(name: str, corpus: dict[str, tuple[Path, Expected]]):
    path, exp = corpus[name]
    w, h = exp.canvas_size
    limits = Limits(cache_budget_bytes=w * h * 4 * 2, keyframe_interval=2)
    with GifSource.open(path, limits) as src:
        order = list(range(exp.frame_count - 1, -1, -1))
        order += random.Random(name).choices(range(exp.frame_count), k=20)
        for i in order:
            assert C.normalize_rgba(src.frame(i)) == C.normalize_rgba(exp.frames[i]), i


def test_disposal_background_is_browser_like(corpus: dict[str, tuple[Path, Expected]]):
    # The frames Pillow gets wrong (see test_corpus.PILLOW_DISCREPANCIES).
    path, _ = corpus["disposal_background"]
    with GifSource.open(path) as src:
        f2 = src.frame(2)
        assert f2.getpixel((2, 2))[3] == 0  # frame 1 rect cleared to transparent
        assert f2.getpixel((10, 6)) == (*C.PAL8[0], 255)  # transparent idx shows frame 0
        f3 = src.frame(3)
        assert f3.getpixel((9, 6))[3] == 0  # frame 2 rect cleared after display
        assert f3.getpixel((0, 0)) == (*C.PAL8[0], 255)


def test_truncated_entry(corpus: dict[str, tuple[Path, Expected]]):
    path, exp = corpus["truncated"]
    with GifSource.open(path) as src:
        assert src.meta.frame_count == exp.frame_count == 2
        assert len(src.warnings) == 1 and "truncated" in src.warnings[0]
        assert tuple(f.delay_ms for f in src.meta.frames) == exp.delays_ms
        _assert_frames(src, exp.frames)


def test_not_a_gif_entry(corpus: dict[str, tuple[Path, Expected]]):
    with pytest.raises(GifLoadError, match="Not a GIF"):
        GifSource.open(corpus["not_a_gif"][0])


def test_large_canvas_header_entry(corpus: dict[str, tuple[Path, Expected]]):
    path, _ = corpus["large_canvas_header"]
    with pytest.raises(GifLoadError, match="too large"):
        GifSource.open(path)
    # Even with a permissive side limit the decompression-bomb guard still applies.
    with pytest.raises(GifLoadError, match="too large"):
        GifSource.open(path, Limits(max_canvas_side=100_000))


def test_bomb_guard_follows_max_image_pixels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = _write(tmp_path, GifSpec(40, 40, [FrameSpec(2, 2, bytes(4))]))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 500)
    with pytest.raises(GifLoadError, match="too large"):
        GifSource.open(path)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    with GifSource.open(path) as src:
        assert src.meta.frame_count == 1


# --- generated edge cases ------------------------------------------------------------------


def _mixed_spec(n: int = 60, w: int = 23, h: int = 17, seed: int = 7) -> GifSpec:
    """Many partial frames with every disposal, changing transparency and local palettes."""
    rng = random.Random(seed)
    frames = [FrameSpec(w, h, C.diag(w, h), disposal=1)]
    for k in range(1, n):
        fw, fh = rng.randint(1, w), rng.randint(1, h)
        left, top = rng.randint(0, w - 1), rng.randint(0, h - 1)  # may exceed the canvas
        local = None
        if rng.random() < 0.3:
            local = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(4)]
        n_col = 4 if local else 8
        frames.append(
            FrameSpec(
                fw,
                fh,
                bytes(rng.randrange(n_col) for _ in range(fw * fh)),
                left=left,
                top=top,
                local_palette=local,
                disposal=rng.choice((0, 1, 2, 3)),
                transparent=rng.choice((None, 0, 1, n_col - 1)),
                interlace=rng.random() < 0.3,
                delay_cs=k % 4,
            )
        )
    return GifSpec(w, h, frames)


def test_mixed_random_access_matches_reference(tmp_path: Path):
    spec = _mixed_spec()
    path = _write(tmp_path, spec)
    expected = C.compose(spec)
    w, h = spec.width, spec.height
    with GifSource.open(path) as full:
        _assert_frames(full, expected)
    # Tiny budget: 3 frames -> checkpoints squeezed to a doubled interval, LRU of ~2 frames.
    limits = Limits(cache_budget_bytes=w * h * 4 * 3, keyframe_interval=4)
    with GifSource.open(path, limits) as src:
        assert src._cache.used_bytes <= limits.cache_budget_bytes
        order = list(range(len(expected) - 1, -1, -1))
        order += random.Random(3).choices(range(len(expected)), k=150)
        for i in order:
            assert C.normalize_rgba(src.frame(i)) == C.normalize_rgba(expected[i]), i
            assert src._cache.used_bytes <= limits.cache_budget_bytes
    with GifSource.open(path, Limits(cache_budget_bytes=0)) as src:
        for i in (59, 3, 0, 31, 31, 58):
            assert C.normalize_rgba(src.frame(i)) == C.normalize_rgba(expected[i]), i


def test_checkpoints_spread_when_budget_is_small(tmp_path: Path):
    spec = GifSpec(8, 8, [FrameSpec(8, 8, C.solid(8, 8, i % 8)) for i in range(64)])
    path = _write(tmp_path, spec)
    fb = 8 * 8 * 4
    with GifSource.open(path, Limits(cache_budget_bytes=fb * 16, keyframe_interval=4)) as src:
        cps = sorted(src._cache.checkpoints)
        assert len(cps) * fb <= fb * 16 // 4
        assert cps[0] == 0 and cps[-1] >= 32  # interval doubled, not just the first ones
        assert src._cache.used_bytes <= fb * 16


def test_frame_bigger_than_canvas_is_clipped(tmp_path: Path):
    spec = GifSpec(
        6,
        5,
        [
            FrameSpec(9, 8, C.diag(9, 8)),  # larger than the logical screen
            FrameSpec(4, 4, C.solid(4, 4, 2), left=4, top=3, disposal=2),
            FrameSpec(2, 2, C.solid(2, 2, 1), left=10, top=10),  # entirely off-canvas
        ],
    )
    with GifSource.open(_write(tmp_path, spec)) as src:
        assert src.frame(0).size == (6, 5)
        _assert_frames(src, C.compose(spec))


def test_no_global_palette_and_out_of_table_index(tmp_path: Path):
    spec = GifSpec(
        4,
        1,
        [FrameSpec(4, 1, bytes([0, 1, 2, 3]), local_palette=[(9, 8, 7), (1, 2, 3)])],
        global_palette=None,
    )
    data = bytearray(C.encode_gif(spec)[0])
    path = tmp_path / "oot.gif"
    path.write_bytes(bytes(data))
    with GifSource.open(path) as src:
        px = [src.frame(0).getpixel((x, 0)) for x in range(4)]
    # A 2-colour table with LZW code size 2: indices 2 and 3 are outside the table.
    assert px[:2] == [(9, 8, 7, 255), (1, 2, 3, 255)]
    assert px[2:] == [(0, 0, 0, 255), (0, 0, 0, 255)]  # beyond the table: opaque black


def test_missing_trailer_warns(tmp_path: Path):
    spec = GifSpec(4, 4, [FrameSpec(4, 4, C.solid(4, 4, 1))], trailer=False)
    with GifSource.open(_write(tmp_path, spec)) as src:
        assert src.meta.frame_count == 1
        assert src.warnings and "trailer" in src.warnings[0]


def test_short_lzw_stream_keeps_decoded_pixels(tmp_path: Path):
    # Second frame's LZW data ends (EOI) after 5 of 16 pixels; block structure is intact.
    w = h = 4
    spec = GifSpec(w, h, [FrameSpec(w, h, C.solid(w, h, 1)), FrameSpec(w, h, C.solid(w, h, 2))])
    data, offsets = C.encode_gif(spec)
    stream = C.lzw_encode(bytes([2] * 5), 3)
    blocks = bytes([len(stream)]) + stream + b"\x00"
    start = offsets[1]
    end = start
    while data[end]:
        end += data[end] + 1
    patched = data[:start] + blocks + data[end + 1 :]
    path = tmp_path / "short.gif"
    path.write_bytes(patched)
    with GifSource.open(path) as src:
        assert src.meta.frame_count == 2
        assert any("incomplete" in m for m in src.warnings)
        f1 = src.frame(1)
        row = [f1.getpixel((x, y)) for y in range(h) for x in range(w)]
        blue, green = (*C.PAL8[2], 255), (*C.PAL8[1], 255)
        assert row[:5] == [blue] * 5 and row[5:] == [green] * 11


def test_unknown_block_stops_with_warning(tmp_path: Path):
    spec = GifSpec(4, 4, [FrameSpec(4, 4, C.solid(4, 4, 1)), FrameSpec(4, 4, C.solid(4, 4, 2))])
    data, _ = C.encode_gif(spec)
    path = tmp_path / "junk.gif"
    path.write_bytes(data[:-1] + b"\x99junk")
    with GifSource.open(path) as src:
        assert src.meta.frame_count == 2
        assert src.warnings and "Unexpected" in src.warnings[0]


def test_gif87a_without_extensions(tmp_path: Path):
    spec = GifSpec(5, 3, [FrameSpec(5, 3, C.diag(5, 3), gce=False)], loop=None)
    data = b"GIF87a" + C.encode_gif(spec)[0][6:]
    path = tmp_path / "87a.gif"
    path.write_bytes(data)
    with GifSource.open(path) as src:
        assert src.meta.loop is None and src.meta.frames[0].delay_ms == 0
        assert src.meta.frames[0].disposal == 0
        _assert_frames(src, C.compose(spec))


# --- per-frame size limits (memory DoS) ---------------------------------------------------


def _descriptor_bomb(
    fw: int, fh: int, *, good_first: bool = False, interlace: bool = False
) -> bytes:
    """Tiny file: 10x10 canvas, 2-colour GCT, a frame *declaring* ``fw x fh``, minimal LZW."""
    out = bytearray(b"GIF89a" + C._u16(10) + C._u16(10) + bytes([0x80, 0, 0]))
    out += bytes([0, 0, 0, 255, 255, 255])
    if good_first:
        out += b"\x2c" + C._u16(0) + C._u16(0) + C._u16(10) + C._u16(10) + b"\x00\x02"
        out += C._sub_blocks(C.lzw_encode(bytes(100), 2))
    out += b"\x2c" + C._u16(0) + C._u16(0) + C._u16(fw) + C._u16(fh)
    out += bytes([0x40 if interlace else 0]) + b"\x02"
    out += b"\x02\x44\x01\x00"  # clear, 0, end -> one pixel then EOI
    return bytes(out) + b"\x3b"


@pytest.mark.parametrize(
    ("fw", "fh", "limits", "match"),
    [
        (16000, 16000, Limits(), "maximum side"),
        (8000, 8000, Limits(), "far larger"),  # side OK, 64 Mpx on a 10x10 canvas
        (16000, 16000, Limits(max_canvas_side=100_000), "too large"),  # > 2 * bomb limit
        (16000, 2000, Limits(max_canvas_side=100_000), "far larger"),
    ],
)
def test_huge_frame_descriptor_rejected_fast_and_small(
    tmp_path: Path, fw: int, fh: int, limits: Limits, match: str
):
    path = tmp_path / "bomb.gif"
    path.write_bytes(_descriptor_bomb(fw, fh))
    assert path.stat().st_size < 64
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        with pytest.raises(GifLoadError, match=match):
            GifSource.open(path, limits)
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert elapsed < 1.0
    assert peak < 100 * 2**20, f"peak {peak / 2**20:.1f} MiB"


def test_huge_frame_after_good_frames_still_rejected(tmp_path: Path):
    path = tmp_path / "bomb2.gif"
    path.write_bytes(_descriptor_bomb(8000, 8000, good_first=True))
    with pytest.raises(GifLoadError, match="Frame 2"):
        GifSource.open(path)


def test_frame_within_slack_is_accepted(tmp_path: Path):
    # 40x40 = 16x the 10x10 canvas area, but far below 16 Mpx: allowed and clipped.
    path = tmp_path / "ok.gif"
    path.write_bytes(_descriptor_bomb(40, 40, good_first=True))
    with GifSource.open(path) as src:
        assert src.meta.frame_count == 2
        assert src.frame(1).getpixel((0, 0)) == (0, 0, 0, 255)


@pytest.mark.skipif(sys.platform == "win32", reason="resource module is POSIX-only")
def test_descriptor_bomb_peak_rss_in_subprocess(tmp_path: Path):
    """Real RSS (Pillow's C allocations are invisible to tracemalloc): the review's repro."""
    path = tmp_path / "bomb.gif"
    path.write_bytes(_descriptor_bomb(16000, 16000))
    code = textwrap.dedent(
        f"""
        import resource, sys
        from gif_editor.core.decoder import GifLoadError, GifSource, Limits
        base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        for limits in (Limits(), Limits(max_canvas_side=100_000)):
            try:
                GifSource.open({str(path)!r}, limits).frame(0)
                sys.exit("no error")
            except GifLoadError:
                pass
        print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - base)
        """
    )
    src_dir = Path(__file__).resolve().parents[2] / "src"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PYTHONPATH": str(src_dir)},
        check=True,
    )
    grown_kib = int(out.stdout.strip())
    assert grown_kib < 100 * 1024, f"RSS grew by {grown_kib} KiB"


def test_off_canvas_frame_is_not_decoded(tmp_path: Path):
    # The off-canvas frame has invalid LZW data; it is never decoded, so no warning.
    spec = GifSpec(
        6,
        4,
        [
            FrameSpec(6, 4, C.diag(6, 4)),
            FrameSpec(3, 3, C.solid(3, 3, 2), left=50, top=1, delay_cs=33),
            FrameSpec(2, 2, C.solid(2, 2, 3), left=1, top=1),
        ],
    )
    data, offsets = C.encode_gif(spec)
    end = offsets[1]
    while data[end]:
        end += data[end] + 1
    data = data[: offsets[1]] + bytes([2, 0xFF, 0xFF, 0]) + data[end + 1 :]  # corrupt LZW
    path = tmp_path / "off.gif"
    path.write_bytes(data)
    with GifSource.open(path) as src:
        assert src.meta.frame_count == 3
        assert src.meta.frames[1].delay_ms == 330
        assert src.warnings == []
        _assert_frames(src, C.compose(spec))


@pytest.mark.parametrize("interlace", [False, True])
def test_frame_larger_than_canvas_matches_reference(tmp_path: Path, interlace: bool):
    spec = GifSpec(
        5,
        6,
        [
            FrameSpec(5, 6, C.solid(5, 6, 1)),
            FrameSpec(9, 21, C.diag(9, 21), left=1, top=2, interlace=interlace, disposal=2),
            FrameSpec(3, 3, C.solid(3, 3, 4), left=3, top=4, interlace=interlace),
        ],
    )
    with GifSource.open(_write(tmp_path, spec)) as src:
        assert src.warnings == []
        _assert_frames(src, C.compose(spec))


@pytest.mark.parametrize("interlace", [False, True])
@pytest.mark.parametrize("n_written", [1, 7, 13, 26, 40, 61])
def test_short_lzw_partially_off_canvas(tmp_path: Path, interlace: bool, n_written: int):
    """Short data in a frame larger than the canvas: exactly the decoded prefix is painted.

    The prefix ends with index 0 pixels (``diag`` wraps), exercising the 0/255 refill logic.
    """
    cw, ch, fw, fh = 5, 6, 7, 11
    full = C.diag(fw, fh)
    rows = C.interlace_order(fh) if interlace else list(range(fh))
    stored = b"".join(full[r * fw : (r + 1) * fw] for r in rows)
    spec = GifSpec(
        cw,
        ch,
        [FrameSpec(cw, ch, C.solid(cw, ch, 6)), FrameSpec(fw, fh, full, interlace=interlace)],
    )
    data, offsets = C.encode_gif(spec)
    end = offsets[1]
    while data[end]:
        end += data[end] + 1
    blocks = C._sub_blocks(C.lzw_encode(stored[:n_written], 3))
    path = tmp_path / "short.gif"
    path.write_bytes(data[: offsets[1]] + blocks + data[end + 1 :])
    # Expected: written pixel positions in decode order map back to (x, y).
    written = {(k % fw, rows[k // fw]) for k in range(n_written)}
    with GifSource.open(path) as src:
        # Non-interlaced rows below the canvas are not decoded, so data that covers every
        # visible row counts as complete (no warning), like the pixels a browser shows.
        partial = interlace or n_written < fw * ch
        assert any("incomplete" in m for m in src.warnings) == partial
        img = src.frame(1)
        for y in range(ch):
            for x in range(cw):
                want = C.PAL8[full[y * fw + x]] if (x, y) in written else C.PAL8[6]
                assert img.getpixel((x, y)) == (*want, 255), (x, y)


def test_open_performance_500x500x200(tmp_path: Path):
    """Index pass (decode + composite every frame) of a 500x500, 200-frame GIF."""
    import numpy as np

    rng = np.random.default_rng(0)
    pal = [c for k in range(256) for c in (k, 255 - k, (k * 7) % 256)]
    frames = []
    base = (np.arange(500)[None, :] // 7 + np.zeros((500, 1), int)).astype(np.uint8)
    for i in range(200):
        a = (base + i) % 64
        x = (i * 2) % 400
        a[100:200, x : x + 100] = rng.integers(0, 256, (100, 100), dtype=np.uint8)
        im = Image.fromarray(a.astype(np.uint8)).convert("P")
        im.putpalette(pal)
        frames.append(im)
    path = tmp_path / "perf.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], disposal=2, optimize=False)
    t0 = time.perf_counter()
    with GifSource.open(path) as src:
        elapsed = time.perf_counter() - t0
        assert src.meta.frame_count == 200
        assert src.frame(199).size == (500, 500)
    # Target is < 2 s (measured ~0.3 s); bound generously for slow CI machines.
    assert elapsed < 6.0, f"open took {elapsed:.2f} s"
