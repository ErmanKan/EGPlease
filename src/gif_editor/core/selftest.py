"""Startup self-test of the undocumented Pillow internals the core relies on.

The decoder drives Pillow's C ``"gif"`` LZW decoder through ``Image.frombytes`` with
hand-built decoder arguments, and the encoder uses ``GifImagePlugin.getdata``. Neither is a
documented API, so a Pillow upgrade could silently break them. :func:`run_selftest` writes a
tiny 2-frame GIF with :func:`gif_editor.core.encoder.write_gif`, decodes it with
:class:`gif_editor.core.decoder.GifSource` and checks every pixel and delay. It takes a few
milliseconds; the app calls it at startup and reports :class:`SelfTestError` to the user.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import PIL
from PIL import Image

__all__ = ["SelfTestError", "run_selftest"]

_SIZE = (5, 3)
_PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
_DELAYS_CS = (7, 23)
_TRANSPARENT = 3  # frame 0 uses index 3 as its transparent index


class SelfTestError(RuntimeError):
    """The GIF round trip through Pillow internals failed (likely an incompatible Pillow)."""


def _frames() -> list[tuple[Image.Image, list[tuple[int, int, int, int]]]]:
    """(P-mode frame, expected RGBA pixels row-major) for both test frames."""
    w, h = _SIZE
    flat = [c for rgb in _PALETTE for c in rgb]
    out = []
    for k in range(2):
        idx = [(x + 2 * y + k) % len(_PALETTE) for y in range(h) for x in range(w)]
        if k == 1:  # the second frame is fully opaque
            idx = [i % 3 for i in idx]
        im = Image.new("P", _SIZE)
        im.putdata(idx)
        im.putpalette(flat)
        if k == 0:
            im.info["transparency"] = _TRANSPARENT
        expected = [
            (0, 0, 0, 0) if k == 0 and i == _TRANSPARENT else (*_PALETTE[i], 255) for i in idx
        ]
        out.append((im, expected))
    return out


def _normalize(px: tuple[int, ...]) -> tuple[int, ...]:
    return (0, 0, 0, 0) if px[3] == 0 else tuple(px)


def run_selftest() -> None:
    """Encode + decode a tiny GIF; raise :class:`SelfTestError` on any mismatch or error."""
    try:
        from gif_editor.core.decoder import GifSource
        from gif_editor.core.encoder import write_gif

        frames = _frames()
        with tempfile.TemporaryDirectory(prefix="gif_editor_selftest_") as tmp:
            path = Path(tmp) / "selftest.gif"
            write_gif(
                [(im, d) for (im, _), d in zip(frames, _DELAYS_CS, strict=True)], path, loop=0
            )
            with GifSource.open(path) as src:
                meta = src.meta
                if (meta.width, meta.height, meta.frame_count) != (*_SIZE, 2):
                    raise SelfTestError(
                        f"unexpected geometry {meta.width}x{meta.height}, "
                        f"{meta.frame_count} frame(s)"
                    )
                delays = tuple(f.delay_ms for f in meta.frames)
                if delays != tuple(d * 10 for d in _DELAYS_CS):
                    raise SelfTestError(f"unexpected delays {delays}")
                for i, (_, expected) in enumerate(frames):
                    img = src.frame(i)
                    got = [
                        _normalize(img.getpixel((x, y)))
                        for y in range(_SIZE[1])
                        for x in range(_SIZE[0])
                    ]
                    if img.mode != "RGBA" or got != expected:
                        raise SelfTestError(f"frame {i} pixels differ: {got} != {expected}")
    except SelfTestError as e:
        raise SelfTestError(_message(str(e))) from e
    except Exception as e:  # any failure inside Pillow internals or our code
        raise SelfTestError(_message(f"{type(e).__name__}: {e}")) from e


def _message(detail: str) -> str:
    return (
        f"GIF self-test failed with Pillow {PIL.__version__} (expected a compatible Pillow "
        f"12.x; the editor relies on Pillow's internal GIF encoder/decoder): {detail}"
    )
