"""GIF decoding with browser disposal semantics + a thread-safe, byte-budgeted frame cache.

Why our own compositor
----------------------
Pillow (12.x) composites GIF frames itself while seeking, but not like browsers do: when the
first frame has no transparency index Pillow keeps an RGB canvas, so disposal 2 ("restore to
background") fills the frame rectangle with an *opaque* colour and later frames lose their
transparency. Browsers start from a fully transparent canvas and clear disposal-2 rectangles to
transparent. This module therefore only uses Pillow for LZW decompression and does the rest:

* **Block parser** (pure Python, fast): ``GifSource.open`` reads the file once and walks the
  GIF block structure — header, logical screen, colour tables, Graphic Control Extensions
  (delay, disposal, transparency index), the NETSCAPE2.0/ANIMEXTS1.0 loop extension and image
  descriptors (rect, interlace, local table). Image data sub-blocks are skipped by their length
  bytes only; for each frame we remember the byte range of its LZW data.
* **LZW**: a frame's index pixels are decoded by Pillow's C ``"gif"`` decoder through the
  instance method ``Image.Image.frombytes(data, "gif", bits, interlace, -1)`` called on a
  pre-allocated ``"P"`` image of the rows we need (``_decode_indices``). The decoder args
  mirror the tile ``GifImagePlugin`` builds; they are undocumented, so ``core/selftest.py``
  checks them at startup. Nothing else from Pillow's GIF plugin is used, so
  ``GifImagePlugin.LOADING_STRATEGY`` is untouched.
* **Compositor** (numpy): canvas starts transparent; a frame paints its non-transparent pixels
  (clipped to the canvas) with its local or global palette (indices beyond the table are
  opaque black); after the frame is shown, disposal 0/1 (and the undefined 4..7) keep it,
  2 clears its rect to transparent, 3 restores the rect to its pre-frame content.

Robustness / limits
-------------------
* Not a GIF, missing file, canvas > ``2 * Image.MAX_IMAGE_PIXELS`` (Pillow's decompression
  bomb threshold), canvas side > ``max_canvas_side``, more than ``max_frames`` frames or zero
  decodable frames -> :class:`GifLoadError`.
* Every image descriptor is validated while parsing, because each frame declares its own size
  and a 40-byte file could otherwise make us allocate gigabytes. Any frame (also one after
  good frames) whose side exceeds ``max_canvas_side``, whose area exceeds
  ``2 * Image.MAX_IMAGE_PIXELS``, or whose area exceeds both ``4 * canvas area`` and
  ``16 Mpx`` (:data:`_FRAME_SLACK_PIXELS`) makes the whole file a :class:`GifLoadError`
  (no real encoder writes such frames; rejecting is safer than guessing).
* Decoding never allocates more than needed: a frame entirely outside the canvas is not
  decoded at all (it still counts as a frame with its delay/disposal); for a non-interlaced
  frame only the rows that reach the canvas are decoded (interlaced frames need all rows,
  which the cap above bounds). Short LZW data costs no second frame-sized buffer: the
  written pixels are a prefix in decode order, located by scanning rows from the end.
* The file ending inside a frame drops that frame and later ones (warning). A structurally
  complete frame whose LZW stream is short/corrupt keeps the pixels that did decode (like
  browsers) and adds a warning. Missing trailer -> warning.

Cache
-----
* ``open`` composites every frame once (needed for ``has_transparency`` and to validate the
  data) and feeds the results into an LRU of RGBA frames measured in ``w * h * 4`` bytes.
  This is done **eagerly** (~1.2 s for 150 frames of 1280x720 on a dev machine), so the UI
  must call ``open`` off the GUI thread.
* Every ``keyframe_interval``-th frame gets a *checkpoint*: the canvas state right before it
  is drawn. Checkpoints are pinned and use at most a quarter of the budget; if they do not fit
  the interval is doubled (dropping every other checkpoint), so they stay spread over the whole
  animation. A cache miss for frame ``i`` resumes from the nearest of: the newest checkpoint
  ``<= i``, a cached frame ``j < i`` whose disposal is not 3 (its post-disposal canvas is
  derivable from the image), or the canvas left by the last render. Backward seeks therefore
  cost at most ``keyframe_interval`` frame decodes instead of O(i).
* ``open`` reads the whole file into memory and closes it immediately; frames are decoded
  from those bytes afterwards. No file handle stays open (on Windows the user can therefore
  save over / delete the source while it is loaded) and later changes on disk are ignored.
* All decoding and cache mutation happen under a per-source lock (thread-safe).
"""

from __future__ import annotations

import contextlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import numpy as np
from PIL import Image

__all__ = ["FrameMeta", "GifLoadError", "GifSource", "Limits", "SourceMeta"]

_DECODE_ERRORS = (OSError, EOFError, SyntaxError, ValueError, MemoryError)

# A frame may be at most this many pixels (or 4x the canvas area, whichever is larger).
_FRAME_SLACK_PIXELS = 16 * 1024 * 1024


@dataclass(frozen=True)
class Limits:
    max_canvas_side: int = 8192
    max_frames: int = 10_000
    cache_budget_bytes: int = 512 * 1024 * 1024
    keyframe_interval: int = 32


@dataclass(frozen=True)
class FrameMeta:
    index: int
    delay_ms: int  # raw value from the file (0 when missing)
    effective_delay_ms: int  # 0/10 ms -> 100 ms (browser behaviour)
    disposal: int


@dataclass(frozen=True)
class SourceMeta:
    path: Path
    width: int
    height: int
    frame_count: int
    loop: int | None
    frames: tuple[FrameMeta, ...]
    has_transparency: bool

    @property
    def total_duration_ms(self) -> int:
        return sum(f.effective_delay_ms for f in self.frames)

    @property
    def delays_ms(self) -> tuple[int, ...]:
        return tuple(f.effective_delay_ms for f in self.frames)


class GifLoadError(Exception):
    """The file cannot be loaded as a GIF (missing, not a GIF, too large, corrupt...).

    ``str(err)`` is a precise technical message (shown under "Details" in the UI and matched
    by tests). ``kind`` says *why*, so the UI can explain it in plain words without parsing
    the text. ``info`` holds the numbers that explanation needs (sizes, limits).
    """

    #: Possible ``kind`` values.
    NOT_FOUND = "not_found"  # no such path
    IS_DIRECTORY = "is_directory"  # the path is a folder
    UNREADABLE = "unreadable"  # OS error while reading (permissions, locked, disk error)
    EMPTY = "empty"  # zero-byte file
    NOT_GIF = "not_gif"  # wrong signature: some other format, or junk
    TOO_LARGE = "too_large"  # canvas over the pixel or side limit
    TOO_MANY_FRAMES = "too_many_frames"  # over Limits.max_frames
    MALFORMED = "malformed"  # a GIF, but broken (truncated header, bad frame, no frames)

    def __init__(self, message: str, kind: str = MALFORMED, **info: object) -> None:
        super().__init__(message)
        self.kind = kind
        self.info = info


def _effective_delay(delay_ms: int) -> int:
    return 100 if delay_ms <= 10 else delay_ms


# ------------------------------------------------------------------------------- parsing


class _Truncated(Exception):
    """The byte stream ended inside a block."""


@dataclass(frozen=True)
class _RawFrame:
    left: int
    top: int
    width: int
    height: int
    interlace: bool
    bits: int  # LZW minimum code size
    data_start: int  # first sub-block length byte
    data_end: int  # one past the block terminator
    lut: np.ndarray  # (256, 4) uint8 RGBA, alpha 255
    transparent: int | None
    disposal: int
    delay_ms: int


@dataclass
class _Parsed:
    width: int
    height: int
    loop: int | None
    frames: list[_RawFrame]
    warnings: list[str]


def _make_lut(table: bytes | None) -> np.ndarray:
    lut = np.zeros((256, 4), dtype=np.uint8)
    lut[:, 3] = 255
    if table:
        rgb = np.frombuffer(table, dtype=np.uint8).reshape(-1, 3)[:256]
        lut[: len(rgb), :3] = rgb
    return lut


def _read_header(data: bytes, name: str) -> tuple[int, int, int, int]:
    """Validate the signature; return (width, height, logical-screen flags, header end)."""
    if len(data) < 6 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise GifLoadError(
            f"Not a GIF file: {name}",
            GifLoadError.EMPTY if not data else GifLoadError.NOT_GIF,
        )
    if len(data) < 13:
        raise GifLoadError(f"No decodable frames in {name}: header is truncated")
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    return width, height, data[10], 13


def _skip_sub_blocks(data: bytes, pos: int) -> int:
    """Return the position after the block terminator of the sub-block chain at ``pos``."""
    n = len(data)
    while True:
        if pos >= n:
            raise _Truncated
        size = data[pos]
        pos += 1
        if size == 0:
            return pos
        pos += size
        if pos > n:
            raise _Truncated


def _check_frame_size(n: int, fw: int, fh: int, width: int, height: int, limits: Limits) -> None:
    """Reject image descriptors whose declared size could exhaust memory (see module doc)."""
    if max(fw, fh) > limits.max_canvas_side:
        raise GifLoadError(
            f"Frame {n} is {fw}x{fh}, which exceeds the maximum side of "
            f"{limits.max_canvas_side} px; the file is malformed or malicious."
        )
    area = fw * fh
    max_pixels = Image.MAX_IMAGE_PIXELS
    if max_pixels is not None and area > 2 * max_pixels:
        raise GifLoadError(
            f"Frame {n} is too large to open safely: {fw}x{fh} = {area} pixels "
            f"exceeds the limit of {2 * max_pixels}"
        )
    if area > max(4 * width * height, _FRAME_SLACK_PIXELS):
        raise GifLoadError(
            f"Frame {n} ({fw}x{fh}) is far larger than the {width}x{height} canvas; "
            "the file is malformed."
        )


def _parse(data: bytes, name: str, limits: Limits) -> _Parsed:
    width, height, flags, pos = _read_header(data, name)
    if width <= 0 or height <= 0:
        raise GifLoadError(f"Invalid canvas size {width}x{height}")
    max_pixels = Image.MAX_IMAGE_PIXELS
    if max_pixels is not None and width * height > 2 * max_pixels:
        raise GifLoadError(
            f"Image is too large to open safely: {width}x{height} = {width * height} pixels "
            f"exceeds the limit of {2 * max_pixels}",
            GifLoadError.TOO_LARGE,
            width=width,
            height=height,
            max_side=limits.max_canvas_side,
        )
    if max(width, height) > limits.max_canvas_side:
        raise GifLoadError(
            f"Canvas {width}x{height} exceeds the maximum side of {limits.max_canvas_side} px",
            GifLoadError.TOO_LARGE,
            width=width,
            height=height,
            max_side=limits.max_canvas_side,
        )

    warnings: list[str] = []
    global_lut: np.ndarray | None = None
    if flags & 0x80:
        size = 3 << ((flags & 7) + 1)
        if pos + size > len(data):
            raise GifLoadError(f"No decodable frames in {name}: colour table is truncated")
        global_lut = _make_lut(data[pos : pos + size])
        pos += size
    default_lut = global_lut if global_lut is not None else _make_lut(None)

    loop: int | None = None
    frames: list[_RawFrame] = []
    gce: tuple[int, int, int | None] | None = None  # (disposal, delay_ms, transparent)
    n = len(data)
    trailer = False
    try:
        while pos < n:
            block = data[pos]
            if block == 0x3B:  # trailer
                trailer = True
                break
            if block == 0x21:  # extension
                if pos + 2 > n:
                    raise _Truncated
                label = data[pos + 1]
                start = pos + 2
                pos = _skip_sub_blocks(data, start)
                if label == 0xF9 and data[start] >= 4:
                    packed = data[start + 1]
                    delay = int.from_bytes(data[start + 2 : start + 4], "little") * 10
                    transparent = data[start + 4] if packed & 1 else None
                    gce = ((packed >> 2) & 7, delay, transparent)
                elif label == 0xFF and data[start] == 11:
                    ident = data[start + 1 : start + 12]
                    sub = start + 12
                    if (
                        ident in (b"NETSCAPE2.0", b"ANIMEXTS1.0")
                        and sub < pos - 1
                        and data[sub] >= 3
                        and data[sub + 1] == 1
                    ):
                        loop = int.from_bytes(data[sub + 2 : sub + 4], "little")
                continue
            if block != 0x2C:
                warnings.append(
                    f"Unexpected data (byte 0x{block:02x}) after frame {len(frames)}; "
                    "the rest of the file was ignored."
                )
                break
            if pos + 10 > n:
                raise _Truncated
            left, top, fw, fh = (
                int.from_bytes(data[pos + k : pos + k + 2], "little") for k in (1, 3, 5, 7)
            )
            _check_frame_size(len(frames) + 1, fw, fh, width, height, limits)
            packed = data[pos + 9]
            pos += 10
            lut = default_lut
            if packed & 0x80:
                size = 3 << ((packed & 7) + 1)
                if pos + size > n:
                    raise _Truncated
                lut = _make_lut(data[pos : pos + size])
                pos += size
            if pos >= n:
                raise _Truncated
            bits = data[pos]
            data_start = pos + 1
            pos = _skip_sub_blocks(data, data_start)
            if len(frames) >= limits.max_frames:
                raise GifLoadError(
                    f"GIF has more than {limits.max_frames} frames",
                    GifLoadError.TOO_MANY_FRAMES,
                    max_frames=limits.max_frames,
                )
            disposal, delay, transparent = gce if gce is not None else (0, 0, None)
            gce = None
            frames.append(
                _RawFrame(
                    left,
                    top,
                    fw,
                    fh,
                    bool(packed & 0x40),
                    bits,
                    data_start,
                    pos,
                    lut,
                    transparent,
                    disposal,
                    delay,
                )
            )
    except _Truncated:
        if frames:
            warnings.append(
                f"The file is truncated inside frame {len(frames) + 1}; "
                f"loaded the first {len(frames)} frame(s)."
            )
        trailer = True  # already reported
    if not frames:
        raise GifLoadError(f"No decodable frames in {name}")
    if not trailer and not warnings:
        warnings.append("The file appears to be truncated (missing GIF trailer).")
    return _Parsed(width, height, loop, frames, warnings)


# ------------------------------------------------------------------------------ decoding


def _interlace_rows(height: int) -> list[int]:
    """Row numbers in the order an interlaced GIF stores them."""
    return [
        y for first, step in ((0, 8), (4, 8), (2, 4), (1, 2)) for y in range(first, height, step)
    ]


def _written_end(im: Image.Image, rows: list[int] | range, fill: int) -> int:
    """Position (in decode order) right after the last pixel of ``im`` that is not ``fill``."""
    w = im.width
    fill_byte = bytes([fill])
    blank = fill_byte * w
    for k in range(len(rows) - 1, -1, -1):
        r = rows[k]
        row = im.crop((0, r, w, r + 1)).tobytes()
        if row != blank:
            return k * w + len(row.rstrip(fill_byte))
    return 0


def _decode_indices(
    f: _RawFrame, blob: bytes, canvas_w: int, canvas_h: int
) -> tuple[np.ndarray, np.ndarray | None]:
    """LZW-decode the visible part of a frame.

    Returns (indices, written): ``indices`` is the (h, w) uint8 part of the frame that lies on
    the canvas (empty when nothing does; then nothing is decoded); ``written`` is a bool mask
    of the same shape for pixels the (short/corrupt) data actually produced, or None when the
    data was complete.
    """
    if not 1 <= f.bits <= 12:
        raise ValueError(f"invalid LZW code size {f.bits}")
    vis_w = max(0, min(f.width, canvas_w - f.left))
    vis_h = max(0, min(f.height, canvas_h - f.top))
    if vis_w == 0 or vis_h == 0:
        return np.zeros((vis_h, vis_w), dtype=np.uint8), None
    # Non-interlaced rows are stored top to bottom: rows below the canvas are not needed
    # (Pillow's decoder stops cleanly once the target image is full).
    rows: list[int] | range = _interlace_rows(f.height) if f.interlace else range(vis_h)
    im = Image.new("P", (f.width, len(rows)), 0)
    args = (f.bits, int(f.interlace), -1)
    try:
        im.frombytes(blob, "gif", *args)
        complete = True
    except ValueError:
        complete = False
    full = (vis_w, vis_h) == im.size
    idx = np.asarray(im if full else im.crop((0, 0, vis_w, vis_h)), dtype=np.uint8)
    if complete:
        return idx, None
    # Short/corrupt data: the decoder wrote a prefix (in decode order) of n pixels. With a
    # 0-filled image the last written pixel is the last non-0 one unless its value is 0; then
    # a 255-filled re-decode (into the same buffer) finds it. n = max of both ends.
    end0 = _written_end(im, rows, 0)
    im.paste(255, (0, 0, *im.size))
    with contextlib.suppress(ValueError):
        im.frombytes(blob, "gif", *args)
    n = max(end0, _written_end(im, rows, 255))
    del im
    rank = np.empty(f.height if f.interlace else vis_h, dtype=np.int64)
    rank[np.asarray(rows, dtype=np.int64)] = np.arange(len(rows), dtype=np.int64)
    pos = rank[:vis_h, None] * f.width + np.arange(vis_w, dtype=np.int64)[None, :]
    return idx, pos < n


class _Compositor:
    """Applies one frame to a canvas (H, W, 4 uint8) in place."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def blank(self) -> np.ndarray:
        return np.zeros((self.height, self.width, 4), dtype=np.uint8)

    def clip(self, f: _RawFrame) -> tuple[int, int, int, int] | None:
        x0, y0 = min(f.left, self.width), min(f.top, self.height)
        x1, y1 = min(f.left + f.width, self.width), min(f.top + f.height, self.height)
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1, y1

    def draw(
        self, canvas: np.ndarray, f: _RawFrame, idx: np.ndarray, written: np.ndarray | None
    ) -> np.ndarray | None:
        """Paint frame ``f``. Returns the saved rect content when disposal is 3."""
        rect = self.clip(f)
        if rect is None:
            return None
        x0, y0, x1, y1 = rect
        region = canvas[y0:y1, x0:x1]
        saved = region.copy() if f.disposal == 3 else None
        sub = idx[: y1 - y0, : x1 - x0]
        # One 32-bit gather per pixel (RGBA packed in native order) is ~5x faster than
        # gathering (N, 4) uint8 rows.
        colours = f.lut.view(np.uint32).reshape(256)[sub]
        mask = None if f.transparent is None else sub != f.transparent
        if written is not None:
            w = written[: y1 - y0, : x1 - x0]
            mask = w if mask is None else mask & w
        region32 = region.view(np.uint32).reshape(region.shape[:2])
        if mask is None:
            region32[...] = colours
        else:
            np.copyto(region32, colours, where=mask)
        return saved

    def dispose(self, canvas: np.ndarray, f: _RawFrame, saved: np.ndarray | None) -> None:
        rect = self.clip(f)
        if rect is None:
            return
        x0, y0, x1, y1 = rect
        if f.disposal == 2:
            canvas[y0:y1, x0:x1] = 0
        elif f.disposal == 3 and saved is not None:
            canvas[y0:y1, x0:x1] = saved


def _to_image(canvas: np.ndarray) -> Image.Image:
    return Image.fromarray(canvas.copy())


# --------------------------------------------------------------------------------- cache


class _FrameCache:
    """LRU of composited frames + pinned canvas checkpoints. Not thread-safe on its own."""

    def __init__(self, budget: int, frame_bytes: int, keyframe_interval: int) -> None:
        self.budget = max(0, budget)
        self.frame_bytes = max(1, frame_bytes)
        self.keyframe_interval = max(1, keyframe_interval)
        self.pin_budget = self.budget // 4
        self.checkpoints: dict[int, np.ndarray] = {}  # frame -> canvas before drawing it
        self.lru: OrderedDict[int, Image.Image] = OrderedDict()

    @property
    def used_bytes(self) -> int:
        return (len(self.checkpoints) + len(self.lru)) * self.frame_bytes

    def get(self, i: int) -> Image.Image | None:
        img = self.lru.get(i)
        if img is not None:
            self.lru.move_to_end(i)
        return img

    def lru_capacity(self) -> int:
        """How many frames the LRU can hold next to the current checkpoints."""
        return max(0, self.budget - len(self.checkpoints) * self.frame_bytes) // self.frame_bytes

    def is_keyframe(self, i: int) -> bool:
        return i % self.keyframe_interval == 0

    def put(self, i: int, img: Image.Image) -> None:
        if self.frame_bytes > self.budget - len(self.checkpoints) * self.frame_bytes:
            return
        self.lru[i] = img
        self.lru.move_to_end(i)
        self._evict()

    def put_checkpoint(self, i: int, canvas: np.ndarray) -> None:
        if i in self.checkpoints or not self.is_keyframe(i):
            return
        if self.frame_bytes > self.pin_budget:
            return
        while (len(self.checkpoints) + 1) * self.frame_bytes > self.pin_budget:
            self.keyframe_interval *= 2
            self.checkpoints = {
                k: v for k, v in self.checkpoints.items() if k % self.keyframe_interval == 0
            }
            if not self.is_keyframe(i):
                return
        self.checkpoints[i] = canvas.copy()
        self._evict()

    def nearest_checkpoint(self, i: int) -> int | None:
        best = None
        for k in self.checkpoints:
            if k <= i and (best is None or k > best):
                best = k
        return best

    def _evict(self) -> None:
        while self.lru and self.used_bytes > self.budget:
            self.lru.popitem(last=False)

    def clear(self) -> None:
        self.checkpoints.clear()
        self.lru.clear()


# -------------------------------------------------------------------------------- source


class GifSource:
    """A decoded-on-demand GIF. Create with :meth:`open`."""

    def __init__(
        self,
        data: bytes,
        parsed: _Parsed,
        meta: SourceMeta,
        cache: _FrameCache,
        last: tuple[int, np.ndarray] | None,
    ) -> None:
        self._data: bytes | None = data  # the whole file; no handle is kept open
        self._frames = parsed.frames[: meta.frame_count]
        self._meta = meta
        self.warnings = parsed.warnings
        self._cache = cache
        self._comp = _Compositor(meta.width, meta.height)
        self._last = last  # (index, canvas after disposing that frame)
        self._lock = threading.Lock()
        self._thumbs: dict[tuple[int, int], Image.Image] = {}

    # ------------------------------------------------------------------ open
    @classmethod
    def open(cls, path: str | Path, limits: Limits = Limits()) -> GifSource:  # noqa: B008
        path = Path(path)
        if path.is_dir():
            raise GifLoadError(f"Is a folder, not a file: {path}", GifLoadError.IS_DIRECTORY)
        if not path.is_file():
            raise GifLoadError(f"File not found: {path}", GifLoadError.NOT_FOUND)
        try:
            with path.open("rb") as fp:
                data = fp.read()
        except OSError as e:
            raise GifLoadError(f"Cannot read {path.name}: {e}", GifLoadError.UNREADABLE) from e
        parsed = _parse(data, path.name, limits)
        return cls._index(data, parsed, path, limits)

    @classmethod
    def _index(cls, data: bytes, parsed: _Parsed, path: Path, limits: Limits) -> GifSource:
        width, height = parsed.width, parsed.height
        comp = _Compositor(width, height)
        cache = _FrameCache(limits.cache_budget_bytes, width * height * 4, limits.keyframe_interval)
        canvas = comp.blank()
        metas: list[FrameMeta] = []
        has_alpha = False
        for i, f in enumerate(parsed.frames):
            try:
                idx, written = _decode_indices(f, data[f.data_start : f.data_end], width, height)
            except _DECODE_ERRORS as e:
                if i == 0:
                    raise GifLoadError(f"No decodable frames in {path.name}: {e}") from e
                parsed.warnings.append(_partial_warning(i, e))
                break
            if written is not None:
                parsed.warnings.append(
                    f"Frame {i + 1} has incomplete or corrupt image data; "
                    "the undecodable pixels were left unchanged."
                )
            cache.put_checkpoint(i, canvas)
            saved = comp.draw(canvas, f, idx, written)
            if not has_alpha:
                has_alpha = bool((canvas[:, :, 3] < 255).any())
            cache.put(i, _to_image(canvas))
            comp.dispose(canvas, f, saved)
            metas.append(FrameMeta(i, f.delay_ms, _effective_delay(f.delay_ms), f.disposal))

        meta = SourceMeta(
            path=path,
            width=width,
            height=height,
            frame_count=len(metas),
            loop=parsed.loop,
            frames=tuple(metas),
            has_transparency=has_alpha,
        )
        return cls(data, parsed, meta, cache, (len(metas) - 1, canvas))

    # ------------------------------------------------------------- accessors
    @property
    def meta(self) -> SourceMeta:
        return self._meta

    def _check_index(self, i: int) -> None:
        if not isinstance(i, int) or not 0 <= i < self._meta.frame_count:
            raise IndexError(f"frame index {i} out of range (0..{self._meta.frame_count - 1})")

    def frame(self, i: int) -> Image.Image:
        """Composited RGBA frame ``i`` at canvas size. Returns a copy the caller may mutate."""
        self._check_index(i)
        with self._lock:
            img = self._cache.get(i)
            if img is None:
                img = self._render(i)
            return img.copy()

    #: ``frames_to_decode`` result while another thread holds the decoder.
    BUSY = 1 << 30

    def frames_to_decode(self, i: int) -> int:
        """How many frames ``frame(i)`` would composite right now (0 = cached).

        Mirrors ``_resume_point`` without copying any canvas, so it is cheap enough to call
        before every frame request. The UI uses it to decide whether ``frame(i)`` is fast
        enough for the GUI thread or should run in the background (scrubbing backwards
        through a GIF bigger than the cache can mean re-compositing 30+ large frames).

        Never blocks: if another thread is decoding right now (it holds the lock for the
        whole render), the answer is ``BUSY``, a cost so high the caller goes asynchronous
        instead of waiting on the GUI thread for that render to finish.
        """
        self._check_index(i)
        if not self._lock.acquire(blocking=False):
            return self.BUSY
        try:
            if i in self._cache.lru:
                return 0
            start = 0
            k = self._cache.nearest_checkpoint(i)
            if k is not None:
                start = k
            if self._last is not None and start <= self._last[0] < i:
                start = self._last[0] + 1
            for j in range(i - 1, start - 1, -1):
                if j in self._cache.lru and self._frames[j].disposal != 3:
                    return i - j
            return i - start + 1
        finally:
            self._lock.release()

    def _resume_point(self, i: int) -> tuple[int, np.ndarray]:
        """Pick the latest known canvas state from which frame ``i`` can be composited.

        Returns (first frame to draw, canvas before drawing it) — the canvas is a fresh array.
        """
        start, canvas = 0, None
        k = self._cache.nearest_checkpoint(i)
        if k is not None:
            start, canvas = k, self._cache.checkpoints[k]
        if self._last is not None and start <= self._last[0] < i:
            start, canvas = self._last[0] + 1, self._last[1]
        for j in range(i - 1, start - 1, -1):
            f = self._frames[j]
            img = self._cache.lru.get(j)
            if img is not None and f.disposal != 3:
                arr = np.array(img, dtype=np.uint8)
                self._comp.dispose(arr, f, None)
                return j + 1, arr
        return start, (canvas.copy() if canvas is not None else self._comp.blank())

    def _render(self, i: int) -> Image.Image:
        data = self._data
        if data is None:
            raise ValueError("GifSource is closed")
        start, canvas = self._resume_point(i)
        # Also cache the frames just before ``i`` (half of the free LRU room) so scrubbing
        # backwards turns into cache hits instead of re-compositing from the checkpoint.
        keep_from = i - self._cache.lru_capacity() // 2
        img: Image.Image | None = None
        for n in range(start, i + 1):
            f = self._frames[n]
            try:
                idx, written = _decode_indices(
                    f, data[f.data_start : f.data_end], self._meta.width, self._meta.height
                )
            except _DECODE_ERRORS as e:
                raise GifLoadError(f"Failed to decode frame {n}: {e}") from e
            self._cache.put_checkpoint(n, canvas)
            saved = self._comp.draw(canvas, f, idx, written)
            if n == i:
                img = _to_image(canvas)
            elif n >= keep_from and self._cache.lru.get(n) is None:
                self._cache.put(n, _to_image(canvas))
            self._comp.dispose(canvas, f, saved)
        self._last = (i, canvas)
        assert img is not None
        self._cache.put(i, img)
        return img

    def thumbnail(self, i: int, max_side: int = 96) -> Image.Image:
        """RGBA thumbnail of frame ``i`` fitting in ``max_side`` (aspect kept). Cached."""
        self._check_index(i)
        if max_side < 1:
            raise ValueError("max_side must be >= 1")
        key = (i, max_side)
        with self._lock:
            cached = self._thumbs.get(key)
        if cached is None:
            w, h = self._meta.width, self._meta.height
            scale = min(1.0, max_side / max(w, h))
            size = (max(1, round(w * scale)), max(1, round(h * scale)))
            src = self.frame(i)
            cached = src if size == src.size else src.resize(size, Image.Resampling.LANCZOS)
            with self._lock:
                self._thumbs[key] = cached
        return cached.copy()

    # ------------------------------------------------------------- lifecycle
    def close(self) -> None:
        with self._lock:
            self._data = None
            self._cache.clear()
            self._thumbs.clear()
            self._last = None

    def __enter__(self) -> GifSource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _partial_warning(i: int, e: BaseException) -> str:
    return (
        f"Frame {i + 1} could not be decoded ({e}); the file may be truncated or corrupt. "
        f"Loaded the first {i} frame(s)."
    )
