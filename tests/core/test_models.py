import pytest

from gif_editor.core.models import CropRect, EditState, OutputSize, Quality


def test_defaults_are_identity():
    s = EditState()
    assert s.speed == 1.0 and s.fps is None and s.deleted == frozenset() and s.crop is None
    s.validate(100, 100, 10)


def test_with_returns_new_and_coerces_deleted():
    s = EditState()
    t = s.with_(deleted={1, 2}, speed=2.0)
    assert t is not s and t.deleted == frozenset({1, 2}) and s.deleted == frozenset()


@pytest.mark.parametrize(
    "kw",
    [
        {"speed": 0.1},
        {"speed": 5},
        {"fps": 0},
        {"fps": 60},
        {"trim_start_ms": -1},
        {"trim_duration_ms": 0},
        {"deleted": {-1}},
        {"size": OutputSize(0, 10)},
        {"quality": Quality(1)},
    ],
)
def test_invalid_fields(kw):
    with pytest.raises(ValueError):
        EditState().with_(**kw)


def test_unknown_field():
    with pytest.raises(TypeError):
        EditState().with_(nope=1)


def test_validate_against_source():
    s = EditState().with_(crop=CropRect(10, 10, 50, 50), deleted={9})
    s.validate(60, 60, 10)
    with pytest.raises(ValueError):
        s.validate(59, 60, 10)
    with pytest.raises(ValueError):
        s.validate(60, 60, 9)


def test_quality_presets():
    assert Quality.preset("low") == Quality(64, False)
