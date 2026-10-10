import io
import threading

import numpy as np
import pytest
from PIL import Image

from gif_editor.core import pipeline
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
    timeline = plan(src.meta, state)
    res = generate(src, state, tmp_path / "out.gif")
    n, durations = read_back(res.path)
    # Expectations come from the planner (its trim/resample rules are tested elsewhere).
    assert n == summary.frame_count == timeline.frame_count == res.frame_count > 0
    assert durations == [f.delay_cs * 10 for f in timeline.frames]
    assert sum(durations) == summary.duration_ms == res.duration_ms
    assert not {2, 4} & {f.src_index for f in timeline.frames}
    assert (res.width, res.height) == (summary.width, summary.height) == (10, 10)
    with Image.open(res.path) as im:
        assert im.size == (10, 10)
    assert [_colour(res.path, i) for i in range(n)] == [
        PALETTE[f.src_index] for f in timeline.frames
    ]


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
    # The source's loop behaviour is kept; no loop block (plays once) stays that way.
    for loop in (3, 0, None):
        path = make_gif(tmp_path / f"l{loop}.gif", solid_frames(2), 100, loop=loop)
        with GifSource.open(path) as s:
            assert s.meta.loop == loop
            res = generate(s, EditState(), tmp_path / f"o{loop}.gif")
        with Image.open(res.path) as im:
            if loop is None:
                assert "loop" not in im.info
            else:
                assert im.info["loop"] == loop
        with GifSource.open(res.path) as out:
            assert out.meta.loop == loop


def test_verify_failure_leaves_destination_untouched(src, tmp_path, monkeypatch):
    dest = tmp_path / "out.gif"
    dest.write_bytes(b"old")
    checked = []

    def bad_read_back(path):
        checked.append(path)
        n, durations = read_back(path)
        return n - 1, durations[:-1]

    monkeypatch.setattr(pipeline, "read_back", bad_read_back)
    with pytest.raises(RuntimeError, match="verification"):
        generate(src, EditState(), dest)
    assert dest.read_bytes() == b"old"
    assert len(checked) == 1 and checked[0] != dest
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.gif", "out.gif"]


def test_verify_runs_on_temp_before_replace(src, tmp_path, monkeypatch):
    dest = tmp_path / "out.gif"
    seen = []

    def spy(path):
        seen.append((path, dest.exists()))
        return read_back(path)

    monkeypatch.setattr(pipeline, "read_back", spy)
    res = generate(src, EditState(), dest)
    assert len(seen) == 1
    assert seen[0][0] != dest and seen[0][1] is False
    assert read_back(res.path) == (8, [100] * 8)


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


# ---------------------------------------------------------------- size & flicker


def _gradient_moving_rect(w=160, h=120, n=24):
    x = np.linspace(0, 255, w)
    y = np.linspace(0, 255, h)
    base = np.zeros((h, w, 3), np.uint8)
    base[..., 0] = x[None, :]
    base[..., 1] = y[:, None]
    base[..., 2] = (255 - x[None, :] * 0.5).astype(np.uint8)
    frames = []
    for i in range(n):
        a = base.copy()
        a[50:65, 5 + i * 5 : 20 + i * 5] = (250, 250, 30)
        frames.append(Image.fromarray(a, "RGB"))
    return frames


@pytest.fixture(scope="module")
def gradient_gif(tmp_path_factory):
    frames = _gradient_moving_rect()
    path = tmp_path_factory.mktemp("grad") / "grad.gif"
    kw = {"save_all": True, "append_images": frames[1:], "duration": 50, "loop": 0}
    frames[0].save(path, optimize=True, **kw)
    with GifSource.open(path) as s:
        decoded = [s.frame(i) for i in range(s.meta.frame_count)]
    buf = io.BytesIO()
    decoded[0].save(buf, "GIF", optimize=True, **{**kw, "append_images": decoded[1:]})
    return path, decoded, len(buf.getvalue())


def _decoded(path):
    with GifSource.open(path) as s:
        return [np.asarray(s.frame(i)) for i in range(s.meta.frame_count)]


@pytest.mark.parametrize("dither", [False, True])
def test_resave_size_and_no_flicker(gradient_gif, tmp_path, dither):
    path, src_frames, pillow_size = gradient_gif
    with GifSource.open(path) as s:
        res = generate(s, EditState().with_(quality=Quality(256, dither)), tmp_path / "o.gif")
    assert res.size_bytes <= 1.5 * pillow_size, (res.size_bytes, pillow_size)
    ins = [np.asarray(f) for f in src_frames]
    outs = _decoded(res.path)
    assert len(outs) == len(ins)
    worst = 0.0
    for k in range(1, len(outs)):
        unchanged = (ins[k] == ins[k - 1]).all(axis=2)
        flicker = (outs[k][..., :3] != outs[k - 1][..., :3]).any(axis=2) & unchanged
        worst = max(worst, flicker.sum() / unchanged.sum())
    assert worst == 0.0


def test_output_is_exactly_the_quantized_frames(gradient_gif, tmp_path):
    """Lossless encoder: the decoded output equals the frames fed to it."""
    path, _, _ = gradient_gif
    state = EditState().with_(quality=Quality(64, True), crop=CropRect(10, 10, 100, 80))
    with GifSource.open(path) as s:
        timeline = plan(s.meta, state)
        fed = list(pipeline.iter_output_frames(s, state, timeline))
        res = generate(s, state, tmp_path / "o.gif")
    outs = _decoded(res.path)
    assert len(outs) == len(fed)
    for (img, _), got in zip(fed, outs, strict=True):
        assert np.array_equal(np.asarray(img.convert("RGBA")), got)


def test_transparent_moving_sprite_lossless(tmp_path):
    frames = []
    for i in range(6):
        im = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
        im.paste((*PALETTE[i % 3], 255), (i * 4, 5, i * 4 + 8, 15))
        frames.append(im)
    path = tmp_path / "sprite.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, disposal=2)
    with GifSource.open(path) as s:
        src_frames = [np.asarray(s.frame(i)) for i in range(s.meta.frame_count)]
        res = generate(s, EditState(), tmp_path / "out.gif")
    for exp, got in zip(src_frames, _decoded(res.path), strict=True):
        assert np.array_equal(exp[..., 3] >= 128, got[..., 3] == 255)
        vis = got[..., 3] == 255
        assert np.array_equal(exp[vis][:, :3], got[vis][:, :3])
