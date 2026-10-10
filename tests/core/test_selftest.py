import time

import PIL
import pytest
from PIL import GifImagePlugin, Image

from gif_editor.core import decoder, encoder
from gif_editor.core.selftest import SelfTestError, run_selftest


def test_selftest_passes_quickly():
    run_selftest()  # warm imports
    t0 = time.perf_counter()
    run_selftest()
    assert time.perf_counter() - t0 < 0.2


def test_selftest_error_is_runtime_error():
    assert issubclass(SelfTestError, RuntimeError)


def _boom(*args, **kwargs):
    raise RuntimeError("internal API changed")


def test_decoder_internals_broken(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Image.Image, "frombytes", _boom)
    with pytest.raises(SelfTestError, match=PIL.__version__) as info:
        run_selftest()
    assert "internal API changed" in str(info.value)


def test_encoder_internals_broken(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(GifImagePlugin, "getdata", _boom)
    with pytest.raises(SelfTestError, match="Pillow"):
        run_selftest()


def test_wrong_pixels_detected(monkeypatch: pytest.MonkeyPatch):
    real = decoder._decode_indices

    def corrupt(*args, **kwargs):
        idx, written = real(*args, **kwargs)
        return (idx + 1) % 3, written

    monkeypatch.setattr(decoder, "_decode_indices", corrupt)
    with pytest.raises(SelfTestError, match="frame 0 pixels differ"):
        run_selftest()


def test_wrong_delays_detected(monkeypatch: pytest.MonkeyPatch):
    real = encoder.write_gif

    def write(frames, path, **kw):
        return real([(im, d + 1) for im, d in frames], path, **kw)

    monkeypatch.setattr(encoder, "write_gif", write)
    with pytest.raises(SelfTestError, match="delays"):
        run_selftest()
