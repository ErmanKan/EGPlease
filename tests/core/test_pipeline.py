import threading

import pytest
from PIL import Image

from gif_editor.core.decoder import GifSource
from gif_editor.core.encoder import Cancelled, read_back
from gif_editor.core.models import CropRect, EditState, OutputSize, Quality
from gif_editor.core.pipeline import export_frame_png, generate, plan, summarize
from gifgen import PALETTE, make_gif, solid_frames


@pytest.fixture
def src(tmp_path):
    path = make_gif(tmp_path / "in.gif", solid_frames(8, (40, 30)), 100)
    with GifSource.open(path) as s:
        yield s


def _colour(path, i):
    with Image.open(path) as im:
        im.seek(i)
        return im.convert("RGB").getpixel((0, 0))


def test_identity_roundtrip(src, tmp_path):
    res = generate(src, EditState(), tmp_path / "out.gif")
    n, durations = read_back(res.path)
    assert (n, durations) == (8, [100] * 8)
    assert (res.width, res.height, res.duration_ms) == (40, 30, 800)
    assert res.size_bytes == res.path.stat().st_size
    assert [_colour(res.path, i) for i in range(8)] == PALETTE


def test_combined_edits_match_summary(src, tmp_path):
    state = EditState().with_(
        trim_start_ms=100,
        trim_duration_ms=600,
        deleted={2, 4},
        speed=2.0,
        crop=CropRect(10, 5, 20, 20),
        size=OutputSize(10, 10),
        quality=Quality.preset("low"),
    )
    summary = summarize(src.meta, state)
    res = generate(src, state, tmp_path / "out.gif")
    n, durations = read_back(res.path)
    assert n == summary.frame_count == 4  # frames 1,3,5,6
    assert sum(durations) == summary.duration_ms == 200
    assert (res.width, res.height) == (summary.width, summary.height) == (10, 10)
    with Image.open(res.path) as im:
        assert im.size == (10, 10)
    assert [_colour(res.path, i) for i in range(4)] == [PALETTE[i] for i in (1, 3, 5, 6)]


def test_fps_resample(src, tmp_path):
    res = generate(src, EditState().with_(fps=5), tmp_path / "out.gif")
    n, durations = read_back(res.path)
    assert n == 4 and durations == [200] * 4


def test_invalid_state_rejected(src, tmp_path):
    with pytest.raises(ValueError):
        plan(src.meta, EditState().with_(crop=CropRect(0, 0, 41, 30)))
    with pytest.raises(ValueError):
        generate(src, EditState().with_(deleted=set(range(8))), tmp_path / "out.gif")
    assert not (tmp_path / "out.gif").exists()


def test_cancel_leaves_no_output(src, tmp_path):
    ev = threading.Event()

    def progress(done, total):
        assert total == 8
        if done == 3:
            ev.set()

    with pytest.raises(Cancelled):
        generate(src, EditState(), tmp_path / "out.gif", progress=progress, cancel=ev)
    assert [p.name for p in tmp_path.iterdir()] == ["in.gif"]


def test_transparency_preserved(tmp_path):
    frames = []
    for i in range(3):
        im = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        im.paste((*PALETTE[i], 255), (i * 5, 0, i * 5 + 5, 20))
        frames.append(im)
    path = tmp_path / "t.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0, disposal=2)
    with GifSource.open(path) as s:
        assert s.meta.has_transparency
        res = generate(s, EditState().with_(quality=Quality(16)), tmp_path / "out.gif")
    with GifSource.open(res.path) as out:
        assert out.meta.has_transparency
        for i in range(3):
            f = out.frame(i)
            assert f.getpixel((i * 5 + 2, 10))[3] == 255
            assert f.getpixel((19, 10))[3] == 0


def test_loop_preserved_and_defaulted(tmp_path):
    for loop, expected in ((3, 3), (None, 0)):
        path = make_gif(tmp_path / f"l{loop}.gif", solid_frames(2), 100, loop=loop)
        with GifSource.open(path) as s:
            res = generate(s, EditState(), tmp_path / f"o{loop}.gif")
        with Image.open(res.path) as im:
            assert im.info.get("loop") == expected


def test_export_frame_png(src, tmp_path):
    raw = export_frame_png(src, 2, tmp_path / "f.png")
    with Image.open(raw) as im:
        assert im.format == "PNG" and im.size == (40, 30)
        assert im.convert("RGB").getpixel((0, 0)) == PALETTE[2]
    edited = export_frame_png(
        src,
        2,
        tmp_path / "g.png",
        EditState().with_(crop=CropRect(0, 0, 8, 6), size=OutputSize(4, 3)),
    )
    with Image.open(edited) as im:
        assert im.size == (4, 3)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.png", "g.png", "in.gif"]


VALID = [
    "basic",
    "partial_offsets",
    "disposal_background",
    "disposal_previous",
    "local_palettes",
    "transparency_changes",
    "zero_delays",
    "no_loop",
    "single_frame",
    "interlaced",
]


@pytest.mark.parametrize("name", VALID)
def test_corpus_generates_valid_gif(corpus, name, tmp_path):
    path, _expected = corpus[name]
    with GifSource.open(path) as s:
        summary = summarize(s.meta, EditState())
        res = generate(s, EditState(), tmp_path / "out.gif")
    n, durations = read_back(res.path)
    assert n == summary.frame_count
    assert sum(durations) == summary.duration_ms
