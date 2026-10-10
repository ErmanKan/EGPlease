"""Size estimate: must be the right order of magnitude and cheap enough for live UI use."""

import io
import time

import pytest
from PIL import Image, ImageDraw

from gif_editor.core.decoder import GifSource
from gif_editor.core.models import CropRect, EditState, OutputSize, Quality
from gif_editor.core.pipeline import estimate_size, generate, plan, summarize
from gifgen import make_gif


def _noisy_gif(path, n=20, size=(120, 90)):
    frames = []
    for i in range(n):
        im = Image.new("RGB", size)
        d = ImageDraw.Draw(im)
        for y in range(size[1]):
            d.line((0, y, size[0], y), fill=((y * 3 + i) % 256, y % 256, (y * 7) % 256))
        d.ellipse((i * 3, 20, i * 3 + 30, 60), fill=(255, 255, 255))
        frames.append(im)
    return make_gif(path, frames, 50)


@pytest.mark.parametrize("dither", [True, False])
def test_estimate_close_to_real(tmp_path, dither):
    src = _noisy_gif(tmp_path / "in.gif")
    state = EditState().with_(quality=Quality(128, dither))
    with GifSource.open(src) as s:
        est = estimate_size(s, state, plan(s.meta, state))
        real = generate(s, state, tmp_path / "out.gif").size_bytes
    assert est > 0
    assert 0.5 * real <= est <= 2.0 * real, f"estimate {est} vs real {real}"


def test_estimate_respects_edits(tmp_path):
    """Heavier edits must move the estimate in the right direction."""
    src = _noisy_gif(tmp_path / "in.gif")
    with GifSource.open(src) as s:
        base = estimate_size(s, EditState(), plan(s.meta, EditState()))
        cropped = EditState().with_(
            crop=CropRect(10, 10, 30, 30), size=OutputSize(20, 20), quality=Quality(8, False)
        )
        small = estimate_size(s, cropped, plan(s.meta, cropped))
        half = EditState().with_(trim_start_ms=0, trim_duration_ms=500)
        fewer = estimate_size(s, half, plan(s.meta, half))
        all_deleted = EditState().with_(deleted=set(range(s.meta.frame_count)))
        assert small < base
        assert fewer < base
        assert estimate_size(s, all_deleted, plan(s.meta, all_deleted)) == 0
        assert summarize(s.meta, all_deleted).frame_count == 0


def test_estimate_is_fast_and_matches_generate(tmp_path):
    src = _noisy_gif(tmp_path / "in.gif", n=60, size=(200, 150))
    with GifSource.open(src) as s:
        t = time.perf_counter()
        est = estimate_size(s, EditState(), plan(s.meta, EditState()))
        dt = time.perf_counter() - t
        real = generate(s, EditState(), tmp_path / "o.gif").size_bytes
    assert dt < 1.5, f"estimate took {dt:.2f}s"
    assert 0.4 * real <= est <= 1.6 * real


def test_estimate_never_writes_files(tmp_path):
    src = _noisy_gif(tmp_path / "in.gif")
    before = sorted(p.name for p in tmp_path.iterdir())
    with GifSource.open(src) as s:
        estimate_size(s, EditState(), plan(s.meta, EditState()))
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_write_stream_writes_to_a_buffer(tmp_path):
    """The estimator encodes in memory; write_stream is the file-free path."""
    from gif_editor.core.encoder import read_back, write_stream

    buf = io.BytesIO()
    frames = [(Image.new("RGB", (8, 6), (i, i, i)).quantize(colors=4), 10) for i in range(3)]
    assert write_stream(buf, frames, loop=0) == 3
    assert buf.getbuffer().nbytes > 0
    path = tmp_path / "roundtrip.gif"
    path.write_bytes(buf.getvalue())
    assert read_back(path) == (3, [100, 100, 100])  # delays are returned in ms
    with pytest.raises(ValueError):
        write_stream(io.BytesIO(), [], loop=0)
