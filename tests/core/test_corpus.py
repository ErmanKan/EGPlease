"""Validate the generated corpus itself (writer + reference compositor) against Pillow.

Where Pillow genuinely differs from browser semantics the case is marked
``xfail(strict=True)`` with the exact difference, so a Pillow change is noticed.
These tests document *raw Pillow*; our own compositor (``GifSource``) is checked against the
same entries, without xfails, in ``tests/core/test_decoder_corpus.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import GifImagePlugin, Image

import corpus as C
from corpus import Expected

PILLOW_DISPOSAL2 = (
    "Pillow differs: disposal 2 fills the frame rect with an OPAQUE colour instead of clearing "
    "it to transparent. The first frame has no transparent index so Pillow keeps the canvas in "
    "RGB mode (no alpha): the opaque-frame rect gets the global background colour (index 3, "
    "yellow) and the rect of the frame with transparent index 6 gets palette[6] (white)."
)

# (entry, frame index) -> reason for frames where Pillow's compositing is not browser-like.
PILLOW_DISCREPANCIES: dict[tuple[str, int], str] = {
    ("disposal_background", 2): PILLOW_DISPOSAL2,
    ("disposal_background", 3): PILLOW_DISPOSAL2,
}


def _frame_params() -> list:
    params = []
    for name in C.VALID_ENTRIES:
        _, expected = C.ENTRIES[name].build()
        for i in range(expected.frame_count):
            marks = []
            if (name, i) in PILLOW_DISCREPANCIES:
                marks.append(pytest.mark.xfail(strict=True, reason=PILLOW_DISCREPANCIES[name, i]))
            params.append(pytest.param(name, i, id=f"{name}-{i}", marks=marks))
    return params


@pytest.fixture
def rgb_always(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        GifImagePlugin, "LOADING_STRATEGY", GifImagePlugin.LoadingStrategy.RGB_ALWAYS
    )


def _diff_summary(actual: bytes, expected: bytes, width: int) -> str:
    diffs = [
        (k // 4 % width, k // 4 // width, tuple(actual[k : k + 4]), tuple(expected[k : k + 4]))
        for k in range(0, len(actual), 4)
        if actual[k : k + 4] != expected[k : k + 4]
    ]
    return f"{len(diffs)} pixels differ (x, y, pillow, expected): {diffs[:5]}"


# --- structural checks ---------------------------------------------------------------------


def test_all_entries_written(corpus: dict[str, tuple[Path, Expected]], corpus_dir: Path) -> None:
    assert set(corpus) == set(C.ENTRIES)
    for path, expected in corpus.values():
        assert path.parent == corpus_dir and path.suffix == ".gif" and path.stat().st_size > 0
        assert expected.description


@pytest.mark.parametrize("name", C.VALID_ENTRIES)
def test_valid_entry_metadata(
    name: str, corpus: dict[str, tuple[Path, Expected]], rgb_always: None
) -> None:
    path, exp = corpus[name]
    assert exp.kind == "valid" and len(exp.frames) == exp.frame_count == len(exp.delays_cs)
    with Image.open(path) as im:
        assert im.format == "GIF"
        assert im.size == exp.canvas_size
        assert im.n_frames == exp.frame_count
        assert im.info.get("loop") == exp.loop
        durations = []
        for i in range(im.n_frames):
            im.seek(i)
            durations.append(im.info.get("duration", 0))
        assert tuple(durations) == exp.delays_ms


@pytest.mark.parametrize(("name", "index"), _frame_params())
def test_valid_entry_pixels(
    name: str, index: int, corpus: dict[str, tuple[Path, Expected]], rgb_always: None
) -> None:
    path, exp = corpus[name]
    with Image.open(path) as im:
        im.seek(index)
        actual = C.normalize_rgba(im.convert("RGBA"))
    expected = C.normalize_rgba(exp.frames[index])
    assert actual == expected, _diff_summary(actual, expected, exp.canvas_size[0])


def test_truncated_decodes_two_frames_then_raises(
    corpus: dict[str, tuple[Path, Expected]], rgb_always: None
) -> None:
    path, exp = corpus["truncated"]
    assert exp.kind == "truncated" and exp.frame_count == 2 and exp.declared_frame_count == 3
    data = path.read_bytes()
    assert not data.endswith(b"\x3b")
    with Image.open(path) as im:
        for i in range(2):
            im.seek(i)
            assert C.normalize_rgba(im.convert("RGBA")) == C.normalize_rgba(exp.frames[i])
            assert im.info["duration"] == exp.delays_ms[i]
        with pytest.raises(OSError, match="truncated"):
            im.seek(2)
            im.load()


def test_not_a_gif(corpus: dict[str, tuple[Path, Expected]]) -> None:
    path, exp = corpus["not_a_gif"]
    assert exp.kind == "invalid"
    try:
        with Image.open(path) as im:
            fmt = im.format
    except Exception:
        return
    assert fmt != "GIF"


def test_large_canvas_header(corpus: dict[str, tuple[Path, Expected]]) -> None:
    path, exp = corpus["large_canvas_header"]
    data = path.read_bytes()
    assert data[:6] == b"GIF89a"
    assert int.from_bytes(data[6:8], "little") == int.from_bytes(data[8:10], "little") == 20000
    assert exp.canvas_size == (20000, 20000) and not exp.frames
    assert len(data) < 200  # tiny file, huge declared canvas
    # Pillow refuses 400 Mpx outright (> 2 * MAX_IMAGE_PIXELS) before decoding anything.
    with pytest.raises(Image.DecompressionBombError):
        Image.open(path)


# --- writer / compositor unit checks (independent of the corpus files) ---------------------


def test_interlace_order() -> None:
    assert C.interlace_order(13) == [0, 8, 4, 12, 2, 6, 10, 1, 3, 5, 7, 9, 11]
    for h in range(1, 40):
        assert sorted(C.interlace_order(h)) == list(range(h))


@pytest.mark.parametrize("n_colours", [2, 3, 4, 16, 17, 256])
def test_lzw_round_trip_through_pillow(tmp_path: Path, n_colours: int) -> None:
    # Large frame: many clear codes and many 255-byte sub-blocks.
    palette = [(i, (i * 7) % 256, 255 - i) for i in range(n_colours)]
    w, h = 61, 37
    idx = C.pattern(w, h, lambda x, y: (x * 3 + y * 5) % n_colours)
    data, _ = C.encode_gif(C.GifSpec(w, h, [C.FrameSpec(w, h, idx)], global_palette=palette))
    path = tmp_path / "rt.gif"
    path.write_bytes(data)
    with Image.open(path) as im:
        assert im.mode == "P"
        assert im.tobytes() == idx


def test_lzw_rejects_out_of_range_index() -> None:
    with pytest.raises(ValueError):
        C.lzw_encode(bytes([4]), 2)


def test_reference_compositor_semantics() -> None:
    pal = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (9, 9, 9)]
    red, green, blue = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)
    spec = C.GifSpec(
        2,
        1,
        [
            C.FrameSpec(1, 1, b"\x00", disposal=1),  # red at (0,0); (1,0) stays transparent
            C.FrameSpec(1, 1, b"\x01", left=1, disposal=3),  # green at (1,0) then restore
            C.FrameSpec(1, 1, b"\x02", left=1, disposal=2),  # blue at (1,0) then clear
            C.FrameSpec(2, 1, b"\x03\x03", transparent=3),  # fully transparent frame
        ],
        global_palette=pal,
    )
    frames = [[f.getpixel((x, 0)) for x in range(2)] for f in C.compose(spec)]
    assert frames == [
        [red, C.TRANSPARENT],
        [red, green],
        [red, blue],
        [red, C.TRANSPARENT],
    ]
