import os
import random
import threading
from pathlib import Path

import pytest
from PIL import GifImagePlugin, Image

from corpus import normalize_rgba
from gif_editor.core.decoder import FrameMeta, GifLoadError, GifSource, Limits, SourceMeta
from tests.gifgen import PALETTE, make_gif, solid_frames


def _reference(path: Path, i: int) -> Image.Image:
    """Pillow's compositing. Only valid as a reference for GIFs whose frames are all opaque
    full-canvas images (there Pillow and browsers agree); corpus tests cover the rest."""
    with Image.open(path) as im:
        im.seek(i)
        return im.convert("RGBA")


def _moving_frames(n: int, size: tuple[int, int] = (20, 14)) -> list[Image.Image]:
    """Frames with a moving square so frames differ structurally, not just in colour."""
    out = []
    for i in range(n):
        img = Image.new("RGB", size, PALETTE[i % 8])
        x = (i * 3) % (size[0] - 4)
        img.paste(PALETTE[(i + 3) % 8], (x, 2, x + 4, 6))
        out.append(img)
    return out


@pytest.fixture
def gif(tmp_path: Path) -> Path:
    return make_gif(tmp_path / "a.gif", solid_frames(5), [0, 10, 50, 200, 100], loop=0)


def test_metadata(gif: Path):
    with GifSource.open(gif) as src:
        m = src.meta
        assert isinstance(m, SourceMeta)
        assert (m.width, m.height, m.frame_count, m.loop) == (16, 12, 5, 0)
        assert m.path == gif
        assert [f.delay_ms for f in m.frames] == [0, 10, 50, 200, 100]
        assert m.delays_ms == (100, 100, 50, 200, 100)
        assert m.total_duration_ms == 550
        assert all(isinstance(f, FrameMeta) for f in m.frames)
        assert [f.index for f in m.frames] == list(range(5))
        assert m.has_transparency is False
        assert src.warnings == []


def test_loop_absent_is_none(tmp_path: Path):
    p = make_gif(tmp_path / "noloop.gif", solid_frames(2), loop=None)
    with GifSource.open(p) as src:
        assert src.meta.loop is None


def test_loop_count(tmp_path: Path):
    p = make_gif(tmp_path / "loop3.gif", solid_frames(2), loop=3)
    with GifSource.open(p) as src:
        assert src.meta.loop == 3


def test_disposal_recorded(tmp_path: Path):
    p = make_gif(tmp_path / "d.gif", solid_frames(3), disposal=[1, 2, 1])
    with GifSource.open(p) as src:
        assert [f.disposal for f in src.meta.frames] == [1, 2, 1]


def test_frame_colours(gif: Path):
    with GifSource.open(gif) as src:
        for i in range(5):
            img = src.frame(i)
            assert img.mode == "RGBA" and img.size == (16, 12)
            assert img.getpixel((3, 3)) == (*PALETTE[i], 255)


def test_frames_match_pillow(tmp_path: Path):
    # Opaque full-canvas frames: no Pillow/browser disposal discrepancy, so they must agree.
    p = make_gif(tmp_path / "m.gif", _moving_frames(12), disposal=[1, 2, 0] * 4)
    with GifSource.open(p) as src:
        for i in range(12):
            assert src.frame(i).tobytes() == _reference(p, i).tobytes()


def test_frame_returns_copy(gif: Path):
    with GifSource.open(gif) as src:
        a = src.frame(0)
        a.paste((1, 2, 3, 4), (0, 0, 16, 12))
        b = src.frame(0)
        assert b is not a
        assert b.getpixel((0, 0)) == (*PALETTE[0], 255)


def test_out_of_range(gif: Path):
    with GifSource.open(gif) as src:
        for bad in (-1, 5, 100):
            with pytest.raises(IndexError):
                src.frame(bad)
        with pytest.raises(IndexError):
            src.thumbnail(5)


def test_thumbnail_size_and_aspect(tmp_path: Path):
    p = make_gif(tmp_path / "wide.gif", solid_frames(2, size=(200, 100)))
    with GifSource.open(p) as src:
        t = src.thumbnail(1)
        assert t.mode == "RGBA" and t.size == (96, 48)
        assert t.getpixel((10, 10)) == (*PALETTE[1], 255)
        assert src.thumbnail(0, max_side=40).size == (40, 20)
        t.paste((0, 0, 0, 0), (0, 0, 96, 48))
        assert src.thumbnail(1).getpixel((10, 10)) == (*PALETTE[1], 255)


def test_thumbnail_small_image_not_upscaled(gif: Path):
    with GifSource.open(gif) as src:
        assert src.thumbnail(0).size == (16, 12)


def test_not_a_gif(tmp_path: Path):
    p = tmp_path / "x.png"
    Image.new("RGB", (4, 4), "red").save(p)
    with pytest.raises(GifLoadError):
        GifSource.open(p)


def test_garbage_file(tmp_path: Path):
    p = tmp_path / "junk.gif"
    p.write_bytes(b"this is not an image at all")
    with pytest.raises(GifLoadError):
        GifSource.open(p)


def test_missing_file(tmp_path: Path):
    with pytest.raises(GifLoadError):
        GifSource.open(tmp_path / "nope.gif")


def test_too_many_frames(tmp_path: Path):
    p = make_gif(tmp_path / "many.gif", solid_frames(5))
    with pytest.raises(GifLoadError, match="frames"):
        GifSource.open(p, Limits(max_frames=3))
    with GifSource.open(p, Limits(max_frames=5)) as src:
        assert src.meta.frame_count == 5


def test_canvas_too_large(tmp_path: Path):
    p = make_gif(tmp_path / "big.gif", solid_frames(2, size=(16, 12)))
    with pytest.raises(GifLoadError, match="Canvas"):
        GifSource.open(p, Limits(max_canvas_side=8))


def test_transparency_detected(tmp_path: Path):
    frames = []
    for i in range(3):
        img = Image.new("P", (10, 10), 1 + i)
        img.putpalette([c for rgb in PALETTE for c in rgb])
        img.paste(0, (0, 0, 5, 5))  # index 0 is the transparent index
        frames.append(img)
    p = make_gif(tmp_path / "t.gif", frames, transparency=0, disposal=2)
    with GifSource.open(p) as src:
        assert src.meta.has_transparency is True
        assert src.frame(0).getpixel((1, 1))[3] == 0
        assert src.frame(0).getpixel((8, 8)) == (*PALETTE[1], 255)
        assert src.meta.frame_count == 3
        for i in range(3):
            # Frame 0 has a transparency index, so Pillow composites with alpha too; the RGB
            # of transparent pixels is irrelevant.
            assert normalize_rgba(src.frame(i)) == normalize_rgba(_reference(p, i))


def test_truncated_file_partial_load(tmp_path: Path):
    p = make_gif(tmp_path / "trunc.gif", _moving_frames(6, size=(40, 30)))
    data = p.read_bytes()
    p.write_bytes(data[: len(data) - 40])
    with GifSource.open(p) as src:
        assert 1 <= src.meta.frame_count <= 6
        assert src.warnings, "a truncation warning is expected"
        for i in range(src.meta.frame_count):
            assert src.frame(i).size == (40, 30)


def test_truncated_file_nothing_decodes(tmp_path: Path):
    p = make_gif(tmp_path / "trunc0.gif", _moving_frames(2, size=(40, 30)))
    data = p.read_bytes()
    p.write_bytes(data[:40])
    with pytest.raises(GifLoadError):
        GifSource.open(p)


def test_lru_path_identical_pixels(tmp_path: Path):
    n = 40
    p = make_gif(tmp_path / "lru.gif", _moving_frames(n), disposal=[1, 2] * (n // 2))
    frame_bytes = 20 * 14 * 4
    limits = Limits(cache_budget_bytes=frame_bytes * 4, keyframe_interval=8)
    refs = [_reference(p, i).tobytes() for i in range(n)]
    with GifSource.open(p, limits) as src:
        assert src._cache.used_bytes <= limits.cache_budget_bytes
        order = list(range(n - 1, -1, -1)) + random.Random(1).choices(range(n), k=80)
        for i in order:
            assert src.frame(i).tobytes() == refs[i], f"frame {i}"
            assert src._cache.used_bytes <= limits.cache_budget_bytes


def test_zero_budget_still_correct(tmp_path: Path):
    p = make_gif(tmp_path / "z.gif", _moving_frames(10))
    with GifSource.open(p, Limits(cache_budget_bytes=0)) as src:
        for i in (9, 3, 0, 7, 7, 1):
            assert src.frame(i).tobytes() == _reference(p, i).tobytes()


def test_thread_safety(tmp_path: Path):
    n = 30
    p = make_gif(tmp_path / "th.gif", _moving_frames(n))
    refs = [_reference(p, i).tobytes() for i in range(n)]
    errors: list[str] = []
    with GifSource.open(p, Limits(cache_budget_bytes=20 * 14 * 4 * 3)) as src:

        def work(seed: int) -> None:
            rng = random.Random(seed)
            for _ in range(60):
                i = rng.randrange(n)
                try:
                    if src.frame(i).tobytes() != refs[i]:
                        errors.append(f"mismatch at {i}")
                    src.thumbnail(i, 8)
                except Exception as e:  # pragma: no cover - surfaced via errors
                    errors.append(repr(e))

        threads = [threading.Thread(target=work, args=(s,)) for s in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert errors == []


def test_loading_strategy_restored(gif: Path):
    before = GifImagePlugin.LOADING_STRATEGY
    with GifSource.open(gif) as src:
        src.frame(3)
    assert before == GifImagePlugin.LOADING_STRATEGY
    assert Image.MAX_IMAGE_PIXELS is not None


def test_close_and_context_manager(gif: Path):
    src = GifSource.open(gif)
    src.close()
    src.close()  # idempotent
    with GifSource.open(gif) as s2:
        assert s2.frame(0).size == (16, 12)


def _open_fds_to(path: Path) -> list[str]:
    fd_dir = Path("/proc/self/fd")
    out = []
    for fd in fd_dir.iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target == str(path.resolve()):
            out.append(target)
    return out


def test_source_file_released_after_open(tmp_path: Path):
    p = make_gif(tmp_path / "src.gif", _moving_frames(6))
    refs = [_reference(p, i).tobytes() for i in range(6)]
    other = make_gif(tmp_path / "other.gif", solid_frames(2))
    with GifSource.open(p, Limits(cache_budget_bytes=0)) as src:
        if Path("/proc/self/fd").is_dir():
            assert _open_fds_to(p) == []
        os.replace(other, p)  # "save over the source" (fails on Windows with an open handle)
        assert p.read_bytes() != b""
        p.unlink()
        assert not p.exists()
        # Still decodes the ORIGINAL frames from memory (cache disabled -> real decode).
        for i in (5, 0, 3):
            assert src.frame(i).tobytes() == refs[i]
        assert src.thumbnail(2, 8).size == (8, 6)


def test_frame_after_close_raises(gif: Path):
    src = GifSource.open(gif, Limits(cache_budget_bytes=0))
    src.close()
    with pytest.raises(ValueError, match="closed"):
        src.frame(1)


def test_frames_to_decode_tracks_the_cache(tmp_path):
    """0 when cached, 1 for the next frame in sequence, more when jumping without a cache."""
    path = make_gif(tmp_path / "a.gif", solid_frames(40, (32, 32)), 50)
    with GifSource.open(path) as src:
        # Opening composites every frame and caches what fits: small GIFs are all cached.
        assert [src.frames_to_decode(i) for i in (0, 20, 39)] == [0, 0, 0]
    # No cache at all: frames are composited from frame 0 or the last frame drawn.
    tiny = Limits(cache_budget_bytes=0)
    with GifSource.open(path, limits=tiny) as src:
        src.frame(10)
        assert src.frames_to_decode(11) == 1  # the next frame resumes from frame 10
        assert src.frames_to_decode(10) == 11  # backwards: from frame 0 again
        assert src.frames_to_decode(39) == 29
        src.frame(39)
        assert src.frames_to_decode(38) == 39
    with pytest.raises(IndexError):
        GifSource.open(path).frames_to_decode(40)


def test_frames_to_decode_never_blocks(tmp_path):
    """While another thread decodes (holding the lock) the answer is BUSY, immediately."""
    import time

    path = make_gif(tmp_path / "a.gif", solid_frames(4, (8, 8)), 50)
    with GifSource.open(path) as src:
        held, release = threading.Event(), threading.Event()

        def hold():
            with src._lock:
                held.set()
                release.wait(5)

        t = threading.Thread(target=hold)
        t.start()
        assert held.wait(5)
        t0 = time.perf_counter()
        assert src.frames_to_decode(2) == GifSource.BUSY
        assert time.perf_counter() - t0 < 0.05
        release.set()
        t.join()
        assert src.frames_to_decode(2) == 0
