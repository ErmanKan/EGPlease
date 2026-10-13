"""Tests for gif_editor.headless: the --edit-spec path used to verify a packaged build.

The parser and the run are what a built .exe executes; a bug here means the packaging check
passes (or fails) for the wrong reason, so the spec grammar is pinned down case by case.
"""

from __future__ import annotations

import pytest
from PIL import Image

from gif_editor.core.models import CropRect, EditState, OutputSize
from gif_editor.headless import parse_spec, run_edit_spec
from tests.gifgen import make_gif, solid_frames


def spec(text: str) -> EditState:
    state, _out = parse_spec(text, EditState())
    return state


def test_out_is_required():
    with pytest.raises(ValueError, match="out=PATH"):
        parse_spec("trim=0:400", EditState())


def test_unknown_key_is_rejected():
    with pytest.raises(ValueError, match="unknown spec key"):
        parse_spec("nonsense=1,out=o.gif", EditState())


def test_item_without_equals_is_rejected():
    # A comma-separated list value (the natural mistake) is caught, not silently ignored.
    with pytest.raises(ValueError, match="expected key=value"):
        parse_spec("delete=0,3,out=o.gif", EditState())


def test_trim_whole_numbers_are_milliseconds():
    st = spec("trim=0:400,out=o.gif")
    assert (st.trim_start_ms, st.trim_duration_ms) == (0, 400)


def test_trim_decimals_are_seconds():
    st = spec("trim=0.5:1.5,out=o.gif")
    assert (st.trim_start_ms, st.trim_duration_ms) == (500, 1000)


def test_trim_without_end_runs_to_the_end():
    st = spec("trim=200,out=o.gif")
    assert (st.trim_start_ms, st.trim_duration_ms) == (200, None)


def test_trim_then_duration_overrides():
    st = spec("trim=0:400,duration=150,out=o.gif")
    assert (st.trim_start_ms, st.trim_duration_ms) == (0, 150)


def test_delete_is_colon_separated():
    assert sorted(spec("delete=0:3:5,out=o.gif").deleted) == [0, 3, 5]


def test_delete_accepts_empty_value():
    assert spec("delete=,out=o.gif").deleted == frozenset()


def test_crop_accepts_colons_or_x():
    assert spec("crop=8:6:40:30,out=o.gif").crop == CropRect(8, 6, 40, 30)
    assert spec("crop=8x6x40x30,out=o.gif").crop == CropRect(8, 6, 40, 30)


def test_size_speed_fps_and_quality():
    st = spec("size=32x24,speed=1.5,fps=12,colors=64,dither=0,out=o.gif")
    assert st.size == OutputSize(32, 24)
    assert (st.speed, st.fps) == (1.5, 12.0)
    assert st.quality.colors == 64 and st.quality.dither is False


def test_items_apply_in_order():
    """Later items win, so a spec can be built up left to right."""
    assert spec("duration=500,duration=100,out=o.gif").trim_duration_ms == 100


def test_values_are_whitespace_and_case_tolerant():
    st = spec(" TRIM = 0 : 400 , OUT = o.gif ")
    assert st.trim_duration_ms == 400


def test_keys_are_case_insensitive_but_paths_are_not():
    """Keys are lowercased; a path must survive verbatim (Windows paths are case-insensitive
    but a Linux CI machine is not, and mangling the user's path would be worse)."""
    _st, out = parse_spec("TRIM=0:100,OUT=Out/MyFile.GIF", EditState())
    assert str(out) == "Out/MyFile.GIF"


def test_out_path_is_returned():
    _st, out = parse_spec("trim=0:100,out=/tmp/x.gif", EditState())
    assert out.name == "x.gif"


def test_bad_number_reports_value_error():
    with pytest.raises(ValueError):
        spec("speed=fast,out=o.gif")


# ---------------------------------------------------------------- the full run
def test_run_edit_spec_writes_a_gif(tmp_path, capsys):
    src = make_gif(tmp_path / "in.gif", solid_frames(8, (64, 48)), 100)
    out = tmp_path / "out.gif"
    spec_text = f"trim=0:400,delete=2,crop=8:6:40:30,size=32x24,colors=64,out={out}"
    assert run_edit_spec(src, spec_text) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("RESULT ")
    assert "size=32x24" in printed and f"path={out}" in printed
    with Image.open(out) as im:
        assert im.size == (32, 24)
    # 8 frames of 100 ms trimmed to 400 ms, minus one deleted frame = 3 kept.
    assert "frames=3" in printed


def test_run_edit_spec_reports_failure_without_a_traceback(tmp_path, capsys):
    """A bad file must produce one machine-readable line and a non-zero exit code."""
    missing = tmp_path / "nope.gif"
    code = run_edit_spec(missing, f"trim=0:100,out={tmp_path / 'o.gif'}")
    assert code == 1
    err = capsys.readouterr().out
    assert err.startswith("ERROR ") and "Traceback" not in err
    assert not (tmp_path / "o.gif").exists()


def test_run_edit_spec_rejects_a_bad_spec(tmp_path, capsys):
    src = make_gif(tmp_path / "in.gif", solid_frames(4, (16, 16)), 100)
    assert run_edit_spec(src, "out=o.gif,bogus=1") == 1
    assert capsys.readouterr().out.startswith("ERROR ValueError")
