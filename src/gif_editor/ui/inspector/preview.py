"""Geometry-aware preview frames and the output size estimate for the inspector.

``PreviewService`` is a non-visual ``QObject`` that the canvas and the summary card lean
on, so neither of them has to know how the output is rendered:

* **Geometry preview.** With ``geometry_enabled`` the inspector shows the *output* look of
  the current frame (``render_frame(crop, size)``: crop, then LANCZOS resize) instead of
  the raw source frame. That is the Milestone 3 "what you will get" view; while it is off
  nothing extra is rendered and the plain composited frame is returned.
* **Size estimate.** ``pipeline.estimate_size`` encodes a few real output frames in memory
  (well under 100 ms for typical GIFs, much more for a very large source), so it runs off
  the GUI thread and is debounced: dragging a slider must not start one estimate per step.

Everything heavy goes through ``ui.workers.run_async`` with a **generation counter**. A
result whose generation is stale (a newer request was made, or a new file was opened in the
meantime) is dropped instead of shown, which is what keeps scrubbing a long GIF from
flickering through frames that no longer matter. Only ``QImage`` crosses the thread
boundary and every signal is emitted on the GUI thread, so no QPixmap is ever built here.
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from gif_editor.core import pipeline
from gif_editor.core.models import CropRect, EditState, OutputSize
from gif_editor.core.render import render_frame
from gif_editor.ui.document import Document
from gif_editor.ui.qt_image import pil_to_qimage
from gif_editor.ui.workers import run_async

#: Default number of rendered preview frames kept (per source index and geometry).
DEFAULT_CACHE_SIZE = 32
#: How long the state must stay unchanged before the size estimate is recomputed (ms).
ESTIMATE_DEBOUNCE_MS = 250

#: LRU key of one cached preview: source index plus the geometry it was rendered with.
#: ``CropRect`` and ``OutputSize`` are frozen dataclasses, so the key hashes by value.
CacheKey = tuple[int, CropRect | None, OutputSize | None]


class PreviewService(QObject):
    """Renders geometry-aware preview frames and estimates the output size.

    Construct with ``PreviewService(doc, parent=None)``. The service follows ``doc`` on its
    own: ``sourceChanged`` clears every cache and drops all pending work, ``stateChanged``
    invalidates the previews rendered with the old crop/size and re-schedules the debounced
    estimate, and ``currentIndexChanged`` asks for the new frame while geometry is on.

    It changes nothing in the document; it only reads it. The canvas draws whatever
    ``frameReady`` hands it, and the summary card shows ``estimated_bytes``.
    """

    #: A rendered (or cached) preview frame is ready: ``(source index, frame as QImage)``.
    frameReady = Signal(int, QImage)
    #: Rendering a preview frame failed: ``(source index, message)``.
    frameFailed = Signal(int, str)
    #: The estimate changed value, was invalidated, or a computation started.
    estimateChanged = Signal()
    #: A fresh estimate finished (``estimated_bytes`` holds its value) or was already known.
    estimateReady = Signal()
    #: ``geometry_enabled`` changed.
    geometryChanged = Signal(bool)

    def __init__(
        self,
        doc: Document,
        parent: QObject | None = None,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
        debounce_ms: int = ESTIMATE_DEBOUNCE_MS,
    ) -> None:
        """Bind the service to ``doc``. ``cache_size`` and ``debounce_ms`` are test hooks.

        Raises ``ValueError`` for ``cache_size < 1``. If ``doc`` already has a source open
        (a service created after the file was loaded) the first estimate is scheduled here.
        """
        super().__init__(parent)
        if cache_size < 1:
            raise ValueError("cache_size must be >= 1")
        self._doc = doc
        self._cache_size = int(cache_size)
        self._debounce_ms = max(0, int(debounce_ms))

        self._geometry = False
        self._cache: OrderedDict[CacheKey, QImage] = OrderedDict()
        self._last_geometry: tuple[CropRect | None, OutputSize | None] = (
            doc.state.crop,
            doc.state.size,
        )
        # One generation counter per work stream. A worker compares the value it captured
        # with the live one (in a GUI-thread callback) and drops its result if anything
        # invalidated the request while it ran.
        self._render_gen = 0
        self._estimate_gen = 0

        # Render side: at most one worker at a time, remembering only the newest index.
        self._render_in_flight = False
        self._pending: int | None = None  # newest index wanted while a render was running

        # Estimate side.
        self._estimate: int | None = None
        self._estimate_pending = False
        self._estimate_state: EditState | None = None  # state the queued estimate is for
        self._estimate_computed: EditState | None = None  # state the last result was for

        self._estimate_timer = QTimer(self)  # single-shot debounce for state changes
        self._estimate_timer.setSingleShot(True)
        self._estimate_timer.timeout.connect(self._start_estimate)

        self._disposed = False
        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._on_state_changed)
        doc.currentIndexChanged.connect(self._on_current_index_changed)

        if doc.source is not None:
            self.refresh_estimate()

    # ---------------------------------------------------------- geometry mode
    @property
    def geometry_enabled(self) -> bool:
        """True while the preview shows the cropped/resized output instead of the source."""
        return self._geometry

    @geometry_enabled.setter
    def geometry_enabled(self, value: bool) -> None:
        value = bool(value)
        if value == self._geometry:
            return
        self._geometry = value
        # Every cached image was rendered under the other geometry, so none of them fits.
        self._cache.clear()
        self._drop_pending_renders()
        if self._doc.source is not None:
            self.request_frame(self._doc.current_index)
        self.geometryChanged.emit(value)

    def set_geometry_enabled(self, value: bool) -> None:
        """Slot-friendly setter for ``geometry_enabled`` (e.g. ``QCheckBox.toggled``)."""
        self.geometry_enabled = value

    def render_preview_frame(self, src_index: int) -> QImage:
        """The frame to show for ``src_index``, honouring ``geometry_enabled``.

        Synchronous and always correct; the canvas normally uses ``request_frame`` so the
        GUI thread never decodes. Raises ``RuntimeError`` when nothing is open and whatever
        the source raises (``IndexError``) for an index it does not have.
        """
        source = self._doc.source
        if source is None:
            raise RuntimeError("no source is open")
        key = self._cache_key(src_index)
        if key is not None:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
        image = self._render(source, src_index, self._geometry_snapshot())
        if key is not None:
            self._cache_put(key, image)
        return image

    def request_frame(self, src_index: int) -> None:
        """Ask for ``src_index``; emit ``frameReady`` (or ``frameFailed``) later.

        A cached frame is delivered through ``QTimer.singleShot(0, ...)`` so callers always
        observe a queued signal and never re-enter their own paint path. At most one render
        runs at a time: while one is in flight only the *latest* index is remembered, so
        scrubbing a long GIF cannot queue hundreds of decodes.
        """
        if self._disposed or self._doc.source is None:
            return
        index = int(src_index)
        if self._render_in_flight:
            self._pending = index
            return
        key = self._cache_key(index)
        if key is not None:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                QTimer.singleShot(0, lambda: self._deliver(index, cached))
                return
        source = self._doc.source
        geometry = self._geometry_snapshot()  # captured now: the worker must not read live state
        self._render_in_flight = True
        generation = self._render_gen
        run_async(
            lambda: self._render(source, index, geometry),
            on_done=lambda image: self._on_rendered(index, key, generation, image),
            on_error=lambda message, _exc: self._on_render_error(index, generation, message),
        )

    # ------------------------------------------------------------- estimates
    @property
    def estimated_bytes(self) -> int | None:
        """Last computed output size in bytes, or ``None`` (nothing open / unavailable)."""
        return self._estimate

    @property
    def estimate_pending(self) -> bool:
        """True while an estimate is debouncing or running on a worker thread."""
        return self._estimate_pending

    def refresh_estimate(self) -> None:
        """Schedule the size estimate, debounced by ``debounce_ms``.

        Always re-arms the timer, so a burst of state changes yields exactly one run once
        the user stops dragging. ``estimate_pending`` turns True immediately, which lets
        the summary card show a "calculating" placeholder.
        """
        if self._disposed:
            return
        self._estimate_state = self._doc.state
        self._estimate_timer.stop()
        self._estimate_timer.start(self._debounce_ms)
        if not self._estimate_pending:
            self._estimate_pending = True
            self.estimateChanged.emit()

    def dispose(self) -> None:
        """Stop the timers, drop pending work and disconnect from the document.

        Idempotent (calling it twice is a no-op) and safe to call at any time. Tests call
        it in teardown so no timer or worker callback outlives the widget tree.
        """
        if self._disposed:
            return
        self._disposed = True
        self._estimate_timer.stop()
        self._drop_pending_renders()
        for signal, slot in (
            (self._doc.sourceChanged, self._on_source_changed),
            (self._doc.stateChanged, self._on_state_changed),
            (self._doc.currentIndexChanged, self._on_current_index_changed),
        ):
            with contextlib.suppress(RuntimeError, TypeError):
                # Already gone (Qt) or never connected.
                signal.disconnect(slot)

    # ------------------------------------------------------- render internals
    def _cache_key(self, src_index: int) -> CacheKey | None:
        """Cache key for ``src_index`` under the current geometry, or ``None`` if disabled."""
        if not self._geometry:
            return None
        state = self._doc.state
        return (src_index, state.crop, state.size)

    def _geometry_snapshot(self) -> tuple[CropRect | None, OutputSize | None] | None:
        """The crop/size to render with right now, or ``None`` for the plain source frame."""
        if not self._geometry:
            return None
        state = self._doc.state
        return (state.crop, state.size)

    @staticmethod
    def _render(
        source: object,
        src_index: int,
        geometry: tuple[CropRect | None, OutputSize | None] | None,
    ) -> QImage:
        """Pillow frame in, ``QImage`` out: never a QPixmap, never a cache write.

        This runs on a pool thread, so it is a static method that receives everything it needs
        as arguments. It reads no ``PreviewService`` or ``Document`` attribute: the geometry was
        captured on the GUI thread when the frame was requested. Reading the live state here
        would let a crop change made mid-render leak into an image that is labelled with the
        old request. The caller caches the result back on the GUI thread.
        """
        image = source.frame(src_index)  # type: ignore[attr-defined]
        if geometry is not None:
            crop, size = geometry
            image = render_frame(image, crop, size)
        return pil_to_qimage(image)

    def _cache_put(self, key: CacheKey, image: QImage) -> None:
        """Store ``image`` under ``key``, evicting the least recently used entries."""
        self._cache[key] = image
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _on_rendered(
        self, src_index: int, key: CacheKey | None, generation: int, image: object
    ) -> None:
        """A render finished: cache and deliver it unless the request went stale."""
        if self._disposed or generation != self._render_gen:
            return
        self._render_in_flight = False
        if isinstance(image, QImage):
            if key is not None and self._cache_key(src_index) == key:
                self._cache_put(key, image)
            self.frameReady.emit(src_index, image)
        self._drain_pending()

    def _on_render_error(self, src_index: int, generation: int, message: str) -> None:
        """A render failed: report it and start the newest pending request, if any."""
        if self._disposed or generation != self._render_gen:
            return
        self._render_in_flight = False
        self.frameFailed.emit(src_index, message)
        self._drain_pending()

    def _deliver(self, src_index: int, image: QImage) -> None:
        """Emit a cached frame from the event loop (never re-entrantly from the caller)."""
        if not self._disposed:
            self.frameReady.emit(src_index, image)

    def _drain_pending(self) -> None:
        """Start the newest remembered render, if a request arrived while one was running."""
        if self._disposed or self._render_in_flight:
            return
        pending = self._pending
        self._pending = None
        if pending is not None and self._doc.source is not None:
            self.request_frame(pending)

    def _drop_pending_renders(self) -> None:
        """Make every in-flight render stale and forget the remembered index."""
        self._render_gen += 1
        self._render_in_flight = False
        self._pending = None

    # ----------------------------------------------------- estimate internals
    def _start_estimate(self) -> None:
        """Debounce elapsed: compute the estimate off the GUI thread for the queued state."""
        if self._disposed:
            return
        source = self._doc.source
        state = self._estimate_state
        if source is None or state is None:
            self._estimate_pending = False
            return
        if self._estimate_computed is not None and self._estimate_computed == state:
            # Exactly this state was already measured (a re-applied or reverted edit):
            # keep the value and just stop showing "calculating".
            self._estimate_pending = False
            self.estimateReady.emit()
            return
        try:
            timeline = self._doc.plan()
        except (ValueError, RuntimeError, OSError):
            # The state is not usable for this source: show no size rather than an error.
            self._finish_estimate(state, None)
            return
        if timeline is None or timeline.frame_count == 0:
            self._finish_estimate(state, 0)
            return
        self._estimate_gen += 1
        generation = self._estimate_gen
        run_async(
            lambda: self._estimate_job(source, state, timeline),
            on_done=lambda value: self._on_estimate_ready(generation, value),
            on_error=lambda _msg, _exc: self._on_estimate_ready(generation, None),
        )

    def _estimate_job(self, source: object, state: EditState, timeline: object) -> int | None:
        """Worker half: ``estimate_size`` for one fixed source/state/timeline.

        Any failure becomes ``None`` (the UI then draws no size line) instead of
        propagating; ``run_async`` also routes a raised exception to the same ``None``.
        """
        try:
            return int(pipeline.estimate_size(source, state, timeline))  # type: ignore[arg-type]
        except Exception:  # an estimate must never raise into the caller
            return None

    def _on_estimate_ready(self, generation: int, value: object) -> None:
        """Deliver an estimate unless a newer request (or a new file) superseded it."""
        if self._disposed or generation != self._estimate_gen:
            return
        self._finish_estimate(self._estimate_state, int(value) if isinstance(value, int) else None)

    def _finish_estimate(self, state: EditState | None, size: int | None) -> None:
        """Store ``size`` for ``state`` and emit the estimate signals."""
        self._estimate_pending = False
        self._estimate_computed = state
        if size != self._estimate:
            self._estimate = size
            self.estimateChanged.emit()
        self.estimateReady.emit()

    # ----------------------------------------------------------- doc signals
    def _on_source_changed(self) -> None:
        """A file was opened or closed: nothing cached or in flight is valid any more."""
        self._cache.clear()
        self._drop_pending_renders()
        self._estimate_gen += 1  # an estimate for the previous file must not land
        self._estimate_timer.stop()
        self._estimate_state = None
        self._estimate_computed = None
        state = self._doc.state
        self._last_geometry = (state.crop, state.size)
        if self._doc.source is None:
            self._estimate_pending = False
            if self._estimate is not None:
                self._estimate = None
                self.estimateChanged.emit()
            return
        self.refresh_estimate()

    def _on_state_changed(self, state: object | None = None) -> None:
        """Edits changed: invalidate old-geometry previews and reschedule the estimate."""
        if self._disposed or self._doc.source is None:
            return
        current = state if isinstance(state, EditState) else self._doc.state
        geometry = (current.crop, current.size)
        if geometry != self._last_geometry:
            # Only the crop/size affect a rendered preview. Drop every image produced with
            # the previous geometry (the new one has its own cache keys) and re-render the
            # frame on screen, so the canvas never shows the old crop.
            for existing in [k for k in self._cache if (k[1], k[2]) != geometry]:
                self._cache.pop(existing, None)
            self._last_geometry = geometry
            if self._geometry:
                self._drop_pending_renders()
                self.request_frame(self._doc.current_index)
        self.refresh_estimate()

    def _on_current_index_changed(self, index: int) -> None:
        """Follow the current frame, but only while the geometry preview is on."""
        if self._disposed or not self._geometry or self._doc.source is None:
            return
        self.request_frame(index)
