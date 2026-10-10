"""Safe animated-GIF writer: streaming, atomic, with progress and cancellation.

Why not ``Image.save(save_all=True)``?  Pillow 12.3's multi-frame GIF writer
crops every frame after the first to a "delta" bounding box.  With
``disposal=2`` and a transparent first frame it compares later frames against
the *RGB colour* of the first frame's transparent index, so opaque border pixels
of that colour are cropped away and then shown as transparent by viewers; a
later frame that is entirely that colour even makes Pillow emit a second GIF
header (a corrupt file).  It also merges identical consecutive frames and has
to collect every frame in memory before writing.

So this module writes the GIF container itself and uses Pillow only for the
LZW-compressed image data of each frame (``GifImagePlugin.getdata``).  Every
frame is written full-canvas with its own colour table and its own
transparency index, nothing is merged, and frames are streamed to disk as they
are produced (constant memory).
"""

from __future__ import annotations

import os
import struct
import threading
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from PIL import GifImagePlugin, Image

__all__ = ["Cancelled", "estimate_size", "read_back", "write_gif"]

MIN_DELAY_CS = 2
MAX_DELAY_CS = 0xFFFF
MAX_LOOP = 0xFFFF

Frame = tuple[Image.Image, int]
ProgressFn = Callable[[int, int | None], None]


class Cancelled(Exception):
    """Raised by `write_gif` when the cancel event is set."""


# ---------------------------------------------------------------- helpers


def _transparency_index(img: Image.Image) -> int | None:
    t = img.info.get("transparency")
    if t is None:
        return None
    if isinstance(t, int):
        return t if 0 <= t <= 255 else None
    if isinstance(t, (bytes, bytearray)):  # per-index alpha table (e.g. from PNG)
        for i, a in enumerate(t):
            if a == 0:
                return i
    return None


def _check_frame(item: object, size: tuple[int, int] | None, index: int) -> Frame:
    try:
        img, delay_cs = item  # type: ignore[misc]
    except (TypeError, ValueError):
        raise ValueError(f"frame {index}: expected (image, delay_cs) tuple") from None
    if not isinstance(img, Image.Image):
        raise ValueError(f"frame {index}: expected a PIL image, got {type(img).__name__}")
    if img.mode != "P":
        raise ValueError(f"frame {index}: image mode must be 'P', got {img.mode!r}")
    if isinstance(delay_cs, bool) or not isinstance(delay_cs, int):
        raise ValueError(f"frame {index}: delay_cs must be an int, got {delay_cs!r}")
    if not MIN_DELAY_CS <= delay_cs <= MAX_DELAY_CS:
        raise ValueError(
            f"frame {index}: delay_cs must be {MIN_DELAY_CS}..{MAX_DELAY_CS}, got {delay_cs}"
        )
    if size is not None and img.size != size:
        raise ValueError(f"frame {index}: size {img.size} differs from first frame {size}")
    return img, delay_cs


def _prepare(img: Image.Image, dummy: bool) -> tuple[Image.Image, int | None]:
    """Copy `img` with a plain RGB palette covering every used index.

    Returns the copy and the transparency index to write: the frame's own
    index, or - when `dummy` is true and the frame is opaque - an index that no
    pixel uses (None if all 256 are used).  A dummy index changes nothing
    visually but makes Pillow-based readers dispose to transparent instead of
    to an opaque background colour.
    """
    out = img.copy()
    pal = img.getpalette("RGB") or []
    used = {i for i, n in enumerate(out.histogram()) if n}
    t = _transparency_index(img)
    if t is None and dummy:
        n_entries = max(len(pal) // 3, 1)
        free = [i for i in range(256) if i not in used]
        if free:
            in_table = [i for i in free if i < n_entries]
            t = in_table[0] if in_table else free[0]
    needed = max(max(used, default=0) + 1, 2, (t + 1) if t is not None else 0)
    if len(pal) < needed * 3:
        pal = pal + [0] * (needed * 3 - len(pal))
    out.putpalette(pal, "RGB")
    return out, t


def _write_header(fp: BinaryIO, size: tuple[int, int], loop: int) -> None:
    w, h = size
    # Logical screen descriptor without a global colour table: every frame has a local one.
    fp.write(b"GIF89a" + struct.pack("<HHBBB", w, h, 0, 0, 0))
    fp.write(b"!\xff\x0bNETSCAPE2.0\x03\x01" + struct.pack("<H", loop) + b"\x00")


def _write_frame(
    fp: BinaryIO, im: Image.Image, delay_cs: int, disposal: int, transparency: int | None
) -> int:
    """Write one full-canvas frame; return the file offset of its control extension."""
    params: dict[str, object] = {
        "duration": delay_cs * 10,
        "disposal": disposal,
        "include_color_table": True,
    }
    if transparency is not None:
        params["transparency"] = transparency
    gce_offset = fp.tell()
    chunks = GifImagePlugin.getdata(im, (0, 0), **params)
    if not chunks or not bytes(chunks[0]).startswith(b"!\xf9\x04"):
        raise RuntimeError("unexpected GIF frame layout from Pillow")
    for chunk in chunks:
        fp.write(chunk)
    return gce_offset


class _Writer:
    """Streams full-canvas frames to a seekable `fp` with a one-frame look-ahead.

    Disposal: a frame gets 2 (restore to background) when it or the frame drawn
    after it is transparent, so transparent pixels never show stale content;
    otherwise 1 (do not dispose).  With no transparency at all every frame is 1.

    Pillow's reader only produces RGBA frames when frame 0 declares a
    transparency index, and fills disposal-2 areas with an opaque background
    colour unless the disposed frame declares one.  So opaque frames followed
    by a transparent one get an unused "dummy" transparency index, and if a
    later frame turns out to be transparent the first frame's control extension
    is patched in place with a dummy index reserved for that purpose.
    """

    def __init__(self, fp: BinaryIO, loop: int) -> None:
        self.fp = fp
        self.loop = loop
        self.pending: Frame | None = None
        self.count = 0
        self.first_transparent = False
        self.first_gce: int | None = None
        self.first_dummy: int | None = None
        self.first_declares = False

    def add(self, img: Image.Image, delay_cs: int) -> None:
        transparent = _transparency_index(img) is not None
        if self.count == 0:
            _write_header(self.fp, img.size, self.loop)
            self.first_transparent = transparent
        else:
            self._flush(next_transparent=transparent)
            if transparent and not self.first_declares:
                self._patch_first()
        self.pending = (img, delay_cs)
        self.count += 1

    def _flush(self, *, next_transparent: bool) -> None:
        assert self.pending is not None
        img, delay_cs = self.pending
        transparent = _transparency_index(img) is not None
        disposal = 2 if transparent or next_transparent else 1
        is_first = self.first_gce is None
        im, t = _prepare(img, dummy=disposal == 2 or is_first)
        if is_first and not transparent and disposal != 2:
            # Reserve the dummy index but only declare it if a transparent frame follows.
            self.first_dummy, t = t, None
        offset = _write_frame(self.fp, im, delay_cs, disposal, t)
        if is_first:
            self.first_gce = offset
            self.first_declares = t is not None
        self.pending = None

    def _patch_first(self) -> None:
        if self.first_gce is None or self.first_dummy is None:
            return
        end = self.fp.tell()
        self.fp.seek(self.first_gce + 3)
        packed = self.fp.read(1)[0]
        self.fp.seek(self.first_gce + 3)
        self.fp.write(bytes([packed | 1]))
        self.fp.seek(self.first_gce + 6)
        self.fp.write(bytes([self.first_dummy]))
        self.fp.seek(end)
        self.first_declares = True

    def finish(self) -> None:
        if self.pending is not None:
            # When looping, the frame after the last one is the first one.
            self._flush(next_transparent=self.first_transparent)
        self.fp.write(b";")


def _iter_checked(frames: Iterable[object]) -> Iterator[Frame]:
    size: tuple[int, int] | None = None
    for i, item in enumerate(frames):
        img, delay = _check_frame(item, size, i)
        size = img.size
        yield img, delay


# ---------------------------------------------------------------- public API


def write_gif(
    frames: Iterable[Frame],
    path: str | os.PathLike[str],
    *,
    loop: int = 0,
    total: int | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Write an animated GIF atomically and return its final path.

    `frames` yields ``("P"-mode image, delay_cs)`` pairs; all images must have
    the same size and every delay must be an int >= 2 centiseconds.  A frame is
    transparent iff its ``info["transparency"]`` is set; that index is written
    per frame.  `loop` is the NETSCAPE loop count (0 = forever).

    The iterable is consumed lazily and each frame is encoded and streamed to
    disk immediately, so memory use does not grow with the frame count (this
    deliberately avoids Pillow's ``save_all`` writer, which collects all frames
    first and mis-handles per-frame transparency - see the module docstring).
    No frames are merged: the output has exactly as many frames as the input.

    `progress(done, total)` is called after each frame is consumed.
    `cancel.is_set()` is checked before each frame and before the file is
    committed; if set, `Cancelled` is raised.

    The data is written to a hidden temporary file in the destination
    directory and moved into place with `os.replace`.  On cancellation or any
    error the temporary file is removed and the exception re-raised; an
    existing destination file is left untouched.

    Raises ValueError for an empty sequence, a non-"P" image, a delay outside
    2..65535 cs, mismatched frame sizes, or a loop outside 0..65535.
    """
    if isinstance(loop, bool) or not isinstance(loop, int) or not 0 <= loop <= MAX_LOOP:
        raise ValueError(f"loop must be an int in 0..{MAX_LOOP}, got {loop!r}")
    dest = Path(path)
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")

    def check_cancel() -> None:
        if cancel is not None and cancel.is_set():
            raise Cancelled("GIF export cancelled")

    try:
        with open(tmp, "x+b") as fp:
            writer = _Writer(fp, loop)
            it = _iter_checked(frames)
            done = 0
            while True:
                check_cancel()
                try:
                    img, delay = next(it)
                except StopIteration:
                    break
                writer.add(img, delay)
                done += 1
                if progress is not None:
                    progress(done, total)
            if done == 0:
                raise ValueError("cannot write a GIF with no frames")
            writer.finish()
            fp.flush()
            os.fsync(fp.fileno())
        check_cancel()
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def read_back(path: str | os.PathLike[str]) -> tuple[int, list[int]]:
    """Return ``(frame_count, durations_ms)`` of a GIF, as Pillow reads it."""
    with Image.open(path) as im:
        n = getattr(im, "n_frames", 1)
        durations: list[int] = []
        for i in range(n):
            im.seek(i)
            durations.append(int(im.info.get("duration", 0)))
    return n, durations


def estimate_size(sample_frames: Sequence[Frame], total_frames: int) -> int:
    """Estimate the byte size of a `total_frames` GIF from a sample of its frames.

    The sample is encoded in memory with the same writer as `write_gif`; the
    estimate is ``header + first frame`` plus the sample's average per-frame
    cost for each remaining frame.  Returns 0 for an empty sample or
    ``total_frames <= 0``.
    """
    if not sample_frames or total_frames <= 0:
        return 0
    frames = list(_iter_checked(sample_frames))
    buf = BytesIO()
    writer = _Writer(buf, 0)
    writer.add(*frames[0])
    header_size = buf.tell()
    marks: list[int] = []
    for img, delay in frames[1:]:
        writer.add(img, delay)  # writes the previous frame
        marks.append(buf.tell())
    writer.finish()
    end = buf.tell() - 1  # without the trailer byte
    first_cost = marks[0] if marks else end  # header + first frame
    if len(frames) > 1:
        per_frame = (end - first_cost) / (len(frames) - 1)
    else:
        per_frame = float(end - header_size)
    return max(0, round(first_cost + per_frame * (total_frames - 1) + 1))
