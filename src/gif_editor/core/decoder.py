"""GIF decoding: metadata index pass + thread-safe, byte-budgeted frame cache.

Strategy
--------
* ``GifSource.open`` runs one sequential *index pass* over the file with Pillow. For every
  frame it records a :class:`FrameMeta`, composites the frame to RGBA (Pillow applies the
  disposal methods while seeking) and checks for transparency. Frames that decode are fed
  into the cache, so if the whole animation fits ``cache_budget_bytes`` every frame is
  cached eagerly and later ``frame(i)`` calls never touch the file.
* If a frame fails to decode after at least one good frame (truncated/corrupt file), the
  pass stops, the good frames are kept and a message is appended to ``warnings``. Zero
  decodable frames -> :class:`GifLoadError`.
* The cache is an LRU of composited RGBA frames measured in bytes (``w * h * 4``). Every
  ``keyframe_interval``-th frame is *pinned* (never evicted) as long as the pinned set fits
  in a quarter of the budget; the rest of the budget is a plain LRU.
* Pillow cannot resume decoding from a stored canvas, so a cache miss is served by seeking
  the open Pillow image: forward from its current position when possible, rewinding to
  frame 0 only when going backwards. Keyframes passed on the way are cached, so later
  random access is mostly cache hits.
* ``GifImagePlugin.LOADING_STRATEGY`` is a module global read during every seek/load. It is
  set to ``RGB_ALWAYS`` only while this module talks to Pillow (under a module-wide lock)
  and restored afterwards. ``Image.MAX_IMAGE_PIXELS`` is left at its default.
* All Pillow access and cache mutation is guarded by a per-source lock, so ``frame()`` and
  ``thumbnail()`` can be called from worker threads.
"""

from __future__ import annotations

import contextlib
import threading
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from PIL import GifImagePlugin, Image

__all__ = ["FrameMeta", "GifLoadError", "GifSource", "Limits", "SourceMeta"]

_DECODE_ERRORS = (OSError, EOFError, SyntaxError, ValueError)
_STRATEGY_LOCK = threading.RLock()


@contextlib.contextmanager
def _rgb_always() -> Iterator[None]:
    """Temporarily force Pillow's RGB_ALWAYS GIF loading strategy (process-wide lock)."""
    with _STRATEGY_LOCK:
        previous = GifImagePlugin.LOADING_STRATEGY
        GifImagePlugin.LOADING_STRATEGY = GifImagePlugin.LoadingStrategy.RGB_ALWAYS
        try:
            yield
        finally:
            GifImagePlugin.LOADING_STRATEGY = previous


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
    """The file cannot be loaded as a GIF (missing, not a GIF, too large, corrupt...)."""


def _effective_delay(delay_ms: int) -> int:
    return 100 if delay_ms <= 10 else delay_ms


class _FrameCache:
    """Byte-budgeted LRU with pinned keyframes. Not thread-safe on its own."""

    def __init__(self, budget: int, frame_bytes: int, keyframe_interval: int) -> None:
        self.budget = max(0, budget)
        self.frame_bytes = max(1, frame_bytes)
        self.keyframe_interval = max(1, keyframe_interval)
        self.pin_budget = self.budget // 4
        self.pinned: dict[int, Image.Image] = {}
        self.lru: OrderedDict[int, Image.Image] = OrderedDict()

    @property
    def used_bytes(self) -> int:
        return (len(self.pinned) + len(self.lru)) * self.frame_bytes

    def get(self, i: int) -> Image.Image | None:
        img = self.pinned.get(i)
        if img is not None:
            return img
        img = self.lru.get(i)
        if img is not None:
            self.lru.move_to_end(i)
        return img

    def is_keyframe(self, i: int) -> bool:
        return i % self.keyframe_interval == 0

    def put(self, i: int, img: Image.Image) -> None:
        if i in self.pinned:
            return
        if self.is_keyframe(i) and (len(self.pinned) + 1) * self.frame_bytes <= self.pin_budget:
            self.lru.pop(i, None)
            self.pinned[i] = img
            self._evict()
            return
        if self.frame_bytes > self.budget:
            return
        self.lru[i] = img
        self.lru.move_to_end(i)
        self._evict()

    def _evict(self) -> None:
        while self.lru and self.used_bytes > self.budget:
            self.lru.popitem(last=False)

    def clear(self) -> None:
        self.pinned.clear()
        self.lru.clear()


class GifSource:
    """A decoded-on-demand GIF. Create with :meth:`open`."""

    def __init__(
        self,
        im: Image.Image,
        meta: SourceMeta,
        warnings: list[str],
        cache: _FrameCache,
        limits: Limits,
    ) -> None:
        self._im: Image.Image | None = im
        self._meta = meta
        self.warnings = warnings
        self._cache = cache
        self._limits = limits
        self._lock = threading.Lock()
        self._thumbs: dict[tuple[int, int], Image.Image] = {}

    # ------------------------------------------------------------------ open
    @classmethod
    def open(cls, path: str | Path, limits: Limits = Limits()) -> GifSource:  # noqa: B008
        path = Path(path)
        if not path.is_file():
            raise GifLoadError(f"File not found: {path}")
        with _rgb_always():
            try:
                im = Image.open(path)
            except Image.DecompressionBombError as e:
                raise GifLoadError(f"Image is too large to open safely: {e}") from e
            except (OSError, SyntaxError, ValueError) as e:
                raise GifLoadError(f"Not a readable image: {path.name} ({e})") from e
            try:
                return cls._index(im, path, limits)
            except BaseException:
                im.close()
                raise

    @classmethod
    def _index(cls, im: Image.Image, path: Path, limits: Limits) -> GifSource:
        if im.format != "GIF":
            raise GifLoadError(f"Not a GIF file: {path.name} (format {im.format or 'unknown'})")
        width, height = im.size
        if width <= 0 or height <= 0:
            raise GifLoadError(f"Invalid canvas size {width}x{height}")
        if max(width, height) > limits.max_canvas_side:
            raise GifLoadError(
                f"Canvas {width}x{height} exceeds the maximum side of {limits.max_canvas_side} px"
            )
        loop = im.info.get("loop")
        cache = _FrameCache(limits.cache_budget_bytes, width * height * 4, limits.keyframe_interval)
        frames: list[FrameMeta] = []
        warnings: list[str] = []
        has_alpha = False
        i = 0
        while True:
            if i > 0:
                try:
                    im.seek(i)
                except EOFError:
                    break  # normal end of animation
                except _DECODE_ERRORS as e:
                    warnings.append(_partial_warning(i, e))
                    break
            if i >= limits.max_frames:
                raise GifLoadError(f"GIF has more than {limits.max_frames} frames")
            try:
                rgba = im.convert("RGBA")
            except Image.DecompressionBombError as e:
                raise GifLoadError(f"Image is too large to open safely: {e}") from e
            except _DECODE_ERRORS as e:
                if i == 0:
                    raise GifLoadError(f"No decodable frames in {path.name}: {e}") from e
                warnings.append(_partial_warning(i, e))
                break
            delay = int(im.info.get("duration", 0) or 0)
            disposal = int(getattr(im, "disposal_method", 0) or 0)
            frames.append(FrameMeta(i, delay, _effective_delay(delay), disposal))
            if not has_alpha:
                has_alpha = rgba.getchannel("A").getextrema()[0] < 255
            cache.put(i, rgba)
            i += 1

        if not warnings and not _ends_with_trailer(path):
            warnings.append("The file appears to be truncated (missing GIF trailer).")

        meta = SourceMeta(
            path=path,
            width=width,
            height=height,
            frame_count=len(frames),
            loop=loop,
            frames=tuple(frames),
            has_transparency=has_alpha,
        )
        return cls(im, meta, warnings, cache, limits)

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
                img = self._decode(i)
            return img.copy()

    def _decode(self, i: int) -> Image.Image:
        im = self._im
        if im is None:
            raise ValueError("GifSource is closed")
        try:
            with _rgb_always():
                start = im.tell()
                if i < start:
                    im.seek(0)
                    start = 0
                    if self._cache.is_keyframe(0) and self._cache.get(0) is None:
                        self._cache.put(0, im.convert("RGBA"))
                for f in range(start + 1, i + 1):
                    im.seek(f)
                    if f != i and self._cache.is_keyframe(f) and self._cache.get(f) is None:
                        self._cache.put(f, im.convert("RGBA"))
                img = im.convert("RGBA")
        except _DECODE_ERRORS as e:
            raise GifLoadError(f"Failed to decode frame {i}: {e}") from e
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
            if self._im is not None:
                self._im.close()
                self._im = None
            self._cache.clear()
            self._thumbs.clear()

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


def _ends_with_trailer(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            fh.seek(-1, 2)
            return fh.read(1) == b";"
    except OSError:
        return True
