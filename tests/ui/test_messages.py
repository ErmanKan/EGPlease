"""Tests for gif_editor.ui.messages: every error maps to a plain-language explanation."""

from __future__ import annotations

import errno
import struct

import pytest

from corpus import build_all
from gif_editor.core.decoder import GifLoadError, GifSource, Limits
from gif_editor.ui.messages import (
    Explanation,
    explain_generate_error,
    explain_load_error,
    explain_load_warnings,
)

JARGON = ("Errno", "malformed", "decodable", "exceeds", "pixels exceeds", "Traceback")


def _assert_plain(e: Explanation) -> None:
    for word in JARGON:
        assert word not in e.headline and word not in e.body, (word, e)


# ------------------------------------------------- real files -> kind -> message
@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("corpus"))


def _load_error(path, **kw) -> GifLoadError:
    with pytest.raises(GifLoadError) as info:
        GifSource.open(path, **kw)
    return info.value


def test_not_a_gif(corpus):
    p = corpus["not_a_gif"][0]
    err = _load_error(p)
    assert err.kind == GifLoadError.NOT_GIF
    e = explain_load_error(err, p)
    assert e.headline == f"\u201c{p.name}\u201d is not a GIF." and e.details == str(err)
    _assert_plain(e)


def test_empty_file(tmp_path):
    p = tmp_path / "empty.gif"
    p.write_bytes(b"")
    err = _load_error(p)
    assert err.kind == GifLoadError.EMPTY
    assert "empty (0 bytes)" in explain_load_error(err, p).headline


def test_missing_file(tmp_path):
    p = tmp_path / "gone.gif"
    err = _load_error(p)
    assert err.kind == GifLoadError.NOT_FOUND
    assert "no longer exists" in explain_load_error(err, p).headline


def test_folder(tmp_path):
    p = tmp_path / "dir.gif"
    p.mkdir()
    err = _load_error(p)
    assert err.kind == GifLoadError.IS_DIRECTORY
    assert "is a folder" in explain_load_error(err, p).headline


def test_too_large_header(corpus):
    p = corpus["large_canvas_header"][0]
    err = _load_error(p)
    assert err.kind == GifLoadError.TOO_LARGE
    assert err.info["width"] == 20000
    e = explain_load_error(err, p)
    assert "too large to edit (20000\u00d720000 pixels)" in e.headline
    assert "pixels on a side" in e.body
    _assert_plain(e)


def test_too_large_side(corpus):
    p = corpus["basic"][0]
    err = _load_error(p, limits=Limits(max_canvas_side=4))
    assert err.kind == GifLoadError.TOO_LARGE
    assert "4 pixels on a side" in explain_load_error(err, p).body


def test_too_many_frames(corpus):
    p = corpus["basic"][0]
    err = _load_error(p, limits=Limits(max_frames=2))
    assert err.kind == GifLoadError.TOO_MANY_FRAMES
    assert "up to 2 frames" in explain_load_error(err, p).body


def test_header_only_is_damaged(tmp_path):
    p = tmp_path / "hdr.gif"
    p.write_bytes(b"GIF89a" + struct.pack("<HHBBB", 10, 10, 0, 0, 0) + b"\x3b")
    err = _load_error(p)
    assert err.kind == GifLoadError.MALFORMED
    e = explain_load_error(err, p)
    assert "is damaged" in e.headline
    _assert_plain(e)


def test_unknown_error_keeps_details():
    e = explain_load_error(RuntimeError("boom"), "a.gif")
    assert "could not be opened" in e.headline and e.details == "boom"
    assert explain_load_error(RuntimeError(), "a.gif").details == "RuntimeError"


def test_memory_error():
    assert "memory" in explain_load_error(MemoryError(), "a.gif").headline


def test_load_warnings(corpus):
    p = corpus["truncated"][0]
    with GifSource.open(p) as s:
        e = explain_load_warnings(s.warnings, p, s.meta.frame_count)
        assert f"{s.meta.frame_count} frames could be loaded" in e.headline
        assert e.details == "\n".join(s.warnings)
    assert "1 frame could" in explain_load_warnings(["x"], p, 1).headline
    _assert_plain(e)


# ------------------------------------------------------------- generate errors
@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (PermissionError(errno.EACCES, "Permission denied"), "No permission to save"),
        (OSError(errno.EPERM, "Operation not permitted"), "No permission to save"),
        (OSError(errno.ENOSPC, "No space left"), "disk is full"),
        (FileNotFoundError(errno.ENOENT, "No such file"), "no longer exists"),
        (OSError(errno.ENAMETOOLONG, "File name too long"), "too long"),
        (OSError(errno.EIO, "I/O error"), "could not be saved"),
        (MemoryError(), "Not enough memory"),
        (RuntimeError("frame count mismatch"), "could not be generated"),
    ],
)
def test_generate_errors(tmp_path, exc, needle):
    e = explain_generate_error(exc, tmp_path / "out.gif")
    assert needle in e.headline, e
    assert "Nothing was written" in e.body
    assert e.title == "Generate failed" and e.details
    _assert_plain(e)


def test_windows_locked_file_is_not_called_a_permission_problem(tmp_path):
    exc = PermissionError(errno.EACCES, "used by another process")
    exc.winerror = 32  # what Windows sets for a sharing violation
    e = explain_generate_error(exc, tmp_path / "out.gif")
    assert e.headline == "\u201cout.gif\u201d is open in another program."


def test_custom_title_for_save_frame(tmp_path):
    e = explain_generate_error(OSError(errno.ENOSPC, "x"), tmp_path / "f.png", "Save failed")
    assert e.title == "Save failed"


def test_text_joins_headline_and_body():
    assert Explanation("t", "Head.", "Body.").text == "Head.\nBody."
    assert Explanation("t", "Head.", "").text == "Head."
