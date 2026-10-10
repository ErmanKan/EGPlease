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
LZW-compressed image data of each frame (``GifImagePlugin.getdata``).  Frames
are written as exact difference rectangles against the previous frame's decoded
colours (lossless by construction), nothing is merged, and frames are streamed
to disk with a one-frame look-ahead (constant memory).
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

import numpy as np
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


def _canonical_palette(img: Image.Image) -> bytes:
    """The image's RGB palette as exactly 768 bytes (zero padded / truncated)."""
    pal = bytes(img.getpalette("RGB") or [])[:768]
    return pal + bytes(768 - len(pal))


def _table_entries(n: int) -> int:
    """Smallest GIF colour-table size (power of two, 2..256) holding ``n`` entries."""
    size = 2
    while size < n:
        size *= 2
    return size


def _table_flag_bits(entries: int) -> int:
    return entries.bit_length() - 2  # 2 -> 0, 4 -> 1, ..., 256 -> 7


def _palette_len(img: Image.Image) -> int:
    return max(len(img.getpalette("RGB") or []) // 3, 1)


class _Record:
    """One input frame, decoded to packed RGBA (transparent = 0) for exact diffs."""

    __slots__ = ("delay_cs", "idx", "need", "own_t", "palette", "rgba")

    def __init__(self, img: Image.Image, delay_cs: int) -> None:
        self.delay_cs = delay_cs
        self.idx = np.asarray(img, dtype=np.uint8)
        self.palette = _canonical_palette(img)
        self.own_t = _transparency_index(img)
        # Colour-table entries this frame needs: its palette, every used index, its t.
        self.need = max(
            _palette_len(img),
            int(self.idx.max()) + 1 if self.idx.size else 1,
            (self.own_t + 1) if self.own_t is not None else 0,
        )
        rgb = np.frombuffer(self.palette, np.uint8).reshape(256, 3).astype(np.uint32)
        lut = rgb[:, 0] | rgb[:, 1] << 8 | rgb[:, 2] << 16 | np.uint32(0xFF000000)
        if self.own_t is not None:
            lut[self.own_t] = 0
        self.rgba = lut[self.idx]

    @property
    def has_transparency(self) -> bool:
        return self.own_t is not None and bool((self.idx == self.own_t).any())


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) of the true pixels of a 2-D mask, or None."""
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _write_header(
    fp: BinaryIO, size: tuple[int, int], loop: int | None, global_table: bytes
) -> None:
    w, h = size
    entries = len(global_table) // 3
    flags = 0x80 | 0x70 | _table_flag_bits(entries)  # global table, 8-bit colour resolution
    fp.write(b"GIF89a" + struct.pack("<HHBBB", w, h, flags, 0, 0) + global_table)
    if loop is not None:
        fp.write(b"!\xff\x0bNETSCAPE2.0\x03\x01" + struct.pack("<H", loop) + b"\x00")


def _write_frame(
    fp: BinaryIO,
    im: Image.Image,
    offset: tuple[int, int],
    delay_cs: int,
    disposal: int,
    transparency: int | None,
    local_table: bool,
) -> None:
    params: dict[str, object] = {
        "duration": delay_cs * 10,
        "disposal": disposal,
        "include_color_table": local_table,
    }
    if transparency is not None:
        params["transparency"] = transparency
    chunks = GifImagePlugin.getdata(im, offset, **params)
    if not chunks or not bytes(chunks[0]).startswith(b"!\xf9\x04"):
        raise RuntimeError("unexpected GIF frame layout from Pillow")
    for chunk in chunks:
        fp.write(chunk)


class _Writer:
    """Streams frames to `fp` as *difference* frames with a one-frame look-ahead.

    The canvas a viewer shows after frame k-1 (with disposal 1, "do not dispose") is
    exactly frame k-1's image, so frame k only writes the bounding rectangle of the
    pixels whose decoded RGBA differs from frame k-1; inside that rectangle unchanged
    pixels are set to a transparency index ("keep what is there"), which compresses
    well.  Comparisons are on decoded colours, so the output is lossless whatever the
    frames' palettes are.

    A diff over a kept canvas cannot turn an opaque pixel transparent.  When frame k
    does that, frame k-1 is written full-canvas with disposal 2 (cleared to
    transparent afterwards) and frame k is written against a blank canvas.  When
    looping and frame 0 has transparent pixels, the last frame is handled the same
    way so the restart starts from a clear canvas.

    The first frame's palette becomes the global colour table; frames with the same
    palette omit their local table (always the case with a shared palette), others
    carry their own.  Every frame declares a transparency index whenever a usable one
    exists: Pillow's reader only produces RGBA frames when frame 0 declares one and
    fills disposal-2 areas with an opaque colour unless the disposed frame does.
    """

    def __init__(self, fp: BinaryIO, loop: int | None) -> None:
        self.fp = fp
        self.loop = loop
        self.size: tuple[int, int] | None = None
        self.global_palette = b""
        self.first_palette = b""
        self.global_entries = 0
        self.pending: _Record | None = None
        self.base: np.ndarray | None = None  # canvas under `pending`; None = blank
        self.first_transparent = False
        self.count = 0

    def add(self, img: Image.Image, delay_cs: int) -> None:
        rec = _Record(img, delay_cs)
        if self.count == 0:
            self.size = img.size
            self.global_entries = _table_entries(rec.need)
            self.first_palette = rec.palette
            self.global_palette = rec.palette[: 3 * self.global_entries]
            _write_header(self.fp, img.size, self.loop, self.global_palette)
            self.first_transparent = rec.has_transparency
        else:
            assert self.pending is not None
            restore = bool(((self.pending.rgba != 0) & (rec.rgba == 0)).any())
            self._flush(restore=restore)
        self.pending = rec
        self.count += 1

    def finish(self) -> None:
        if self.pending is not None:
            # When looping, the frame after the last one is the first one.
            self._flush(restore=self.loop is not None and self.first_transparent)
        self.fp.write(b";")

    def _flush(self, *, restore: bool) -> None:
        rec = self.pending
        assert rec is not None and self.size is not None
        w, h = self.size
        first = self.base is None and self.count == 1
        canvas_rgba = self.base if self.base is not None else np.zeros_like(rec.rgba)
        changed = rec.rgba != canvas_rgba
        full = (0, 0, w, h)
        x0, y0, x1, y1 = full if restore or first else (_bbox(changed) or (0, 0, 1, 1))
        idx = rec.idx[y0:y1, x0:x1]
        ch = changed[y0:y1, x0:x1]

        shared = rec.need <= self.global_entries and rec.palette == self.first_palette
        entries = self.global_entries if shared else _table_entries(rec.need)
        mark = self._marker(rec, idx, ch, entries)
        if mark is None and not shared:
            # A larger local table may provide an unused index.
            bigger = _table_entries(entries + 1) if entries < 256 else entries
            mark = self._marker(rec, idx, ch, bigger)
            if mark is not None:
                entries = bigger
        out = np.where(ch, idx, mark).astype(np.uint8) if mark is not None else idx
        im = Image.fromarray(np.ascontiguousarray(out), "P")
        im.putpalette(rec.palette[: 3 * entries], "RGB")
        disposal = 2 if restore else 1
        _write_frame(self.fp, im, (x0, y0), rec.delay_cs, disposal, mark, not shared)
        self.base = None if restore else rec.rgba
        self.pending = None

    @staticmethod
    def _marker(rec: _Record, idx: np.ndarray, ch: np.ndarray, entries: int) -> int | None:
        """Index to declare transparent: never used by a changed pixel inside the rect.

        The frame's own transparency index qualifies (a changed pixel is never
        transparent: that case is written against a blank canvas, where transparent
        pixels are unchanged).  Otherwise prefer an index outside the frame's palette.
        """
        if rec.own_t is not None:
            return rec.own_t  # always < entries (rec.need covers it)
        used = np.zeros(256, bool)
        used[np.unique(idx[ch])] = True
        for i in range(entries - 1, -1, -1):
            if not used[i]:
                return i
        return None


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
    loop: int | None = 0,
    total: int | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    verify: Callable[[Path], None] | None = None,
) -> Path:
    """Write an animated GIF atomically and return its final path.

    `frames` yields ``("P"-mode image, delay_cs)`` pairs; all images must have
    the same size and every delay must be an int >= 2 centiseconds.  A frame is
    transparent iff its ``info["transparency"]`` is set; that index is written
    per frame.  `loop` is the NETSCAPE loop count (0 = forever); ``None`` writes no
    loop extension at all (the GIF plays once, like a source without one).

    Frames are written as difference frames (see `_Writer`): only the rectangle that
    changed since the previous frame, with unchanged pixels inside it marked
    transparent.  Decoding the output yields exactly the input frames.  The first
    frame's palette is the global colour table and frames sharing it carry no local
    table (pass frames quantized onto one `render.Palette` for the smallest files).

    The iterable is consumed lazily and each frame is encoded and streamed to
    disk immediately, so memory use does not grow with the frame count (this
    deliberately avoids Pillow's ``save_all`` writer, which collects all frames
    first and mis-handles per-frame transparency - see the module docstring).
    No frames are merged: the output has exactly as many frames as the input.

    `progress(done, total)` is called after each frame is consumed.
    `cancel.is_set()` is checked before each frame and before the file is
    committed; if set, `Cancelled` is raised.

    `verify(temp_path)`, if given, runs on the complete temporary file just before
    it is moved into place; any exception it raises aborts the write (the temporary
    file is deleted, the destination untouched) and propagates.

    The data is written to a hidden temporary file in the destination
    directory and moved into place with `os.replace`.  On cancellation or any
    error the temporary file is removed and the exception re-raised; an
    existing destination file is left untouched.

    Raises ValueError for an empty sequence, a non-"P" image, a delay outside
    2..65535 cs, mismatched frame sizes, or a loop that is not None or 0..65535.
    """
    if loop is not None and (
        isinstance(loop, bool) or not isinstance(loop, int) or not 0 <= loop <= MAX_LOOP
    ):
        raise ValueError(f"loop must be None or an int in 0..{MAX_LOOP}, got {loop!r}")
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
        if verify is not None:
            verify(tmp)
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
