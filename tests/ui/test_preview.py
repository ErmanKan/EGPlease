"""Tests for ``PreviewService`` (``ui/inspector/preview.py``).

The ``doc`` fixture has 8 solid-colour frames, 40x30, 100 ms each (``PALETTE`` colours), so
"did the crop/resize happen" is answerable by checking the image size and sampling one pixel.

Async paths are made deterministic where it matters: the size estimate is measured against a
synchronous ``estimate_size`` call for the same state, and the render burst test replaces
``run_async`` with a manual queue so the coalescing logic can be observed without racing the
thread pool.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtGui import QColor, QImage

from gif_editor.core import pipeline
from gif_editor.core.models import CropRect, OutputSize
from gif_editor.ui.document import Document
from gif_editor.ui.inspector import preview as preview_mod
from gif_editor.ui.inspector.preview import PreviewService
from gifgen import PALETTE


@pytest.fixture
def svc(qtbot, doc):
    """A geometry-off service bound to the ``doc`` fixture, disposed in teardown."""
    service = PreviewService(doc, debounce_ms=10)
    yield service
    service.dispose()


def _pixel(img: QImage, x: int = 5, y: int = 5) -> tuple[int, int, int]:
    rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
    c = QColor(rgba.pixel(x, y))
    return c.red(), c.green(), c.blue()


def _close(a, b, tol=3) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b, strict=True))


# --------------------------------------------------------------- geometry mode


def test_geometry_off_returns_unmodified_frame(svc):
    img = svc.render_preview_frame(0)
    assert (img.width(), img.height()) == (40, 30)
    assert _close(_pixel(img), PALETTE[0])
    img5 = svc.render_preview_frame(5)
    assert _close(_pixel(img5), PALETTE[5])
    assert _close(_pixel(img5, 39, 29), PALETTE[5])


def test_geometry_on_applies_crop_and_resize(svc, doc):
    doc.apply(
        doc.state.with_(crop=CropRect(10, 5, 20, 15), size=OutputSize(10, 8)),
        "Set crop and size",
    )
    svc.geometry_enabled = True
    img = svc.render_preview_frame(2)
    assert (img.width(), img.height()) == (10, 8)
    # A solid-colour source stays that colour through crop + LANCZOS resize.
    assert _close(_pixel(img, 5, 4), PALETTE[2])


def test_geometry_toggle_swaps_result_and_clears_cache(svc):
    assert (svc.render_preview_frame(0).width(), svc.render_preview_frame(0).height()) == (40, 30)
    svc.geometry_enabled = True
    assert svc._cache == {}  # old-geometry images are never reused
    assert (svc.render_preview_frame(1).width(), svc.render_preview_frame(1).height()) == (40, 30)
    svc.geometry_enabled = False
    assert svc._cache == {}
    assert (svc.render_preview_frame(1).width(), svc.render_preview_frame(1).height()) == (40, 30)


def test_geometry_enabled_signal_and_noop_setting(svc):
    seen: list[bool] = []
    svc.geometryChanged.connect(seen.append)
    svc.set_geometry_enabled(True)
    assert svc.geometry_enabled is True
    svc.set_geometry_enabled(True)  # unchanged: no second signal
    svc.geometry_enabled = False
    assert seen == [True, False]


def test_render_preview_frame_without_source_raises():
    empty = Document()
    service = PreviewService(empty)
    with pytest.raises(RuntimeError):
        service.render_preview_frame(0)
    service.dispose()


def test_crop_change_invalidates_cached_preview(qtbot, svc, doc):
    svc.geometry_enabled = True
    qtbot.waitUntil(lambda: not svc._render_in_flight)
    first = svc.render_preview_frame(0)
    assert (first.width(), first.height()) == (40, 30)

    doc.apply(doc.state.with_(crop=CropRect(0, 0, 20, 10)), "Change crop")
    with qtbot.waitSignal(svc.frameReady, timeout=3000) as sig:
        pass  # stateChanged already asked for the current frame with the new geometry
    _idx, img = sig.args
    assert (img.width(), img.height()) == (20, 10)
    assert (svc.render_preview_frame(0).width(), svc.render_preview_frame(0).height()) == (20, 10)


# ------------------------------------------------------------------- async render


def test_request_frame_emits_ready_with_index_and_size(qtbot, svc):
    with qtbot.waitSignal(svc.frameReady, timeout=5000) as sig:
        svc.request_frame(3)
    index, img = sig.args
    assert index == 3
    assert (img.width(), img.height()) == (40, 30)
    assert _close(_pixel(img), PALETTE[3])


def test_request_frame_with_geometry_returns_output_size(qtbot, svc, doc):
    doc.apply(doc.state.with_(crop=CropRect(5, 5, 20, 15)), "Change crop")
    svc.geometry_enabled = True  # this already requests the current frame (0)
    with qtbot.waitSignal(
        svc.frameReady, timeout=5000, check_params_cb=lambda i, _img: i == 4
    ) as sig:
        svc.request_frame(4)  # queued behind frame 0, then delivered
    index, img = sig.args
    assert index == 4
    assert (img.width(), img.height()) == (20, 15)


def test_worker_uses_geometry_captured_at_request_time(qtbot, svc, doc, monkeypatch):
    """A crop change made while a render runs must not leak into that render."""
    jobs = []
    monkeypatch.setattr(preview_mod, "run_async", lambda fn, **kw: jobs.append(fn))
    doc.apply(doc.state.with_(crop=CropRect(0, 0, 20, 10)), "crop A")
    svc.geometry_enabled = True  # queues a render of frame 0 with crop A
    assert jobs
    doc.apply(doc.state.with_(crop=CropRect(0, 0, 30, 20)), "crop B")  # before the job runs
    img = jobs[0]()  # run the captured job now, as a worker would
    assert (img.width(), img.height()) == (20, 10)  # crop A, not the live crop B


def test_stale_generation_result_is_dropped(svc):
    seen: list[tuple[int, QImage]] = []
    svc.frameReady.connect(lambda i, img: seen.append((i, img)))
    stale = svc._render_gen - 1
    svc._on_rendered(0, None, stale, QImage(1, 1, QImage.Format.Format_RGBA8888))
    assert seen == []  # an older request finishing late must not be displayed

    fresh = QImage(2, 2, QImage.Format.Format_RGBA8888)
    svc._on_rendered(1, None, svc._render_gen, fresh)
    assert [i for i, _ in seen] == [1]


def test_stale_result_dropped_after_source_change(qtbot, doc):
    service = PreviewService(doc, debounce_ms=10)
    try:
        service.geometry_enabled = True
        seen: list[int] = []
        service.frameReady.connect(lambda i, _img: seen.append(i))
        generation = service._render_gen
        image = QImage(1, 1, QImage.Format.Format_RGBA8888)
        service._on_source_changed()  # a new file invalidates the generation
        service._on_rendered(0, None, generation, image)
        assert seen == []
    finally:
        service.dispose()


def test_cache_hit_delivers_without_a_render(qtbot, svc):
    svc.geometry_enabled = True
    qtbot.waitUntil(lambda: not svc._render_in_flight, timeout=3000)
    cached = svc.render_preview_frame(2)  # fills the cache synchronously
    with qtbot.waitSignal(svc.frameReady, timeout=2000) as sig:
        svc.request_frame(2)
        assert not svc._render_in_flight  # a cache hit never starts a worker
    index, img = sig.args
    assert index == 2
    # PySide copies a QImage across a signal, so compare contents, not identity.
    assert img == cached


def test_burst_coalesces_to_the_latest_index(qtbot, doc, monkeypatch):
    jobs: list[tuple[object, dict]] = []
    monkeypatch.setattr(preview_mod, "run_async", lambda fn, **kw: jobs.append((fn, kw)))
    service = PreviewService(doc, debounce_ms=10_000)
    try:
        delivered: list[int] = []
        service.frameReady.connect(lambda i, _img: delivered.append(i))
        for index in range(1, 6):
            service.request_frame(index)
        assert len(jobs) == 1  # only index 1 reached the "pool"
        _fn, kw = jobs[0]
        kw["on_done"](jobs[0][0]())  # finish index 1
        # 2, 3 and 4 were superseded while index 1 rendered; only the newest survived.
        assert len(jobs) == 2
        assert delivered == [1]
        fn5, kw5 = jobs[1]
        image = fn5()
        assert _close(_pixel(image), PALETTE[5])
        kw5["on_done"](image)
        assert delivered == [1, 5]  # never more than one per stalling render
    finally:
        service.dispose()


def test_render_failure_emits_frame_failed(qtbot, doc, monkeypatch):
    monkeypatch.setattr(
        preview_mod.PreviewService,
        "_render",
        staticmethod(
            lambda source, index, geometry: (_ for _ in ()).throw(RuntimeError("decode failed"))
        ),
    )
    service = PreviewService(doc, debounce_ms=10)
    try:
        with qtbot.waitSignal(service.frameFailed, timeout=3000) as sig:
            service.request_frame(0)
        assert sig.args == [0, "decode failed"]
    finally:
        service.dispose()


# --------------------------------------------------------------- size estimate


def test_estimate_settles_and_measures_timing(qtbot, svc):
    qtbot.waitUntil(lambda: svc.estimated_bytes is not None, timeout=5000)
    assert svc.estimated_bytes > 0
    assert svc.estimate_pending is False

    # The debounce actually delays the computation.
    svc.refresh_estimate()
    assert svc.estimate_pending is True
    time.sleep(0)  # let the timer arm; the wait below drives the event loop
    with qtbot.waitSignal(svc.estimateReady, timeout=5000):
        pass
    assert svc.estimated_bytes > 0


def test_estimate_matches_a_synchronous_computation(qtbot, svc, doc):
    qtbot.waitUntil(lambda: svc.estimated_bytes is not None, timeout=5000)
    expected = pipeline.estimate_size(doc.source, doc.state, doc.plan())
    assert svc.estimated_bytes == expected


def test_estimate_accuracy_against_a_real_generate(qtbot, svc, doc, tmp_path):
    qtbot.waitUntil(lambda: svc.estimated_bytes is not None, timeout=5000)
    result = pipeline.generate(doc.source, doc.state, tmp_path / "out.gif")
    actual = result.size_bytes
    estimate = svc.estimated_bytes
    error = abs(estimate - actual) / actual
    # Reported for the milestone log: estimate vs the file Generate actually writes.
    print(f"\nestimate={estimate} actual={actual} error={error:.1%}")
    assert error < 0.5


def test_estimate_is_zero_with_every_frame_deleted(qtbot, svc, doc):
    qtbot.waitUntil(lambda: svc.estimated_bytes is not None, timeout=5000)
    doc.apply(doc.state.with_(deleted=frozenset(range(8))), "Delete every frame")
    qtbot.waitUntil(lambda: svc.estimated_bytes in (0, None), timeout=5000)
    assert svc.estimated_bytes == 0


def test_estimate_is_none_with_no_source_open(qtbot, svc, doc):
    qtbot.waitUntil(lambda: svc.estimated_bytes is not None, timeout=5000)
    doc.close()
    qtbot.waitUntil(lambda: svc.estimated_bytes is None, timeout=3000)
    assert svc.estimated_bytes is None


def test_state_change_invalidates_and_recomputes(qtbot, svc, doc):
    qtbot.waitUntil(lambda: svc.estimated_bytes is not None, timeout=5000)
    before = svc.estimated_bytes

    ready: list[int] = []
    svc.estimateReady.connect(lambda: ready.append(1))
    doc.apply(doc.state.with_(speed=3.0), "Change speed")
    assert svc.estimate_pending is True  # invalidated straight away
    qtbot.waitUntil(lambda: len(ready) >= 1, timeout=5000)
    assert svc.estimated_bytes is not None

    crop = CropRect(0, 0, 16, 12)
    doc.apply(doc.state.with_(crop=crop), "Change crop")
    expected = pipeline.estimate_size(doc.source, doc.state, doc.plan())
    qtbot.waitUntil(lambda: svc.estimated_bytes == expected, timeout=5000)
    assert svc.estimated_bytes == expected
    assert svc.estimated_bytes != before or expected == before


def test_scrubbing_frames_does_not_recompute_the_estimate(qtbot, svc, doc):
    qtbot.waitUntil(lambda: svc.estimated_bytes is not None, timeout=5000)
    ready: list[int] = []
    svc.estimateReady.connect(lambda: ready.append(1))
    for index in range(8):
        doc.set_current_index(index)
    qtbot.wait(200)  # longer than the 10 ms debounce
    assert ready == []  # the frame on screen never changes the output size


def test_estimate_never_raises_into_the_caller(qtbot, doc, monkeypatch):
    def boom(*_args, **_kwargs):
        raise ValueError("estimate exploded")

    monkeypatch.setattr(pipeline, "estimate_size", boom)
    service = PreviewService(doc, debounce_ms=10)
    try:
        svc_ready: list[int] = []
        service.estimateReady.connect(lambda: svc_ready.append(1))
        qtbot.waitUntil(lambda: bool(svc_ready), timeout=5000)
        assert service.estimated_bytes is None
        assert service.estimate_pending is False
    finally:
        service.dispose()


def test_estimate_survives_any_exception_type(qtbot, doc, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("estimate exploded differently")

    monkeypatch.setattr(pipeline, "estimate_size", boom)
    service = PreviewService(doc, debounce_ms=10)
    try:
        with qtbot.waitSignal(service.estimateReady, timeout=5000):
            pass
        assert service.estimated_bytes is None
    finally:
        service.dispose()


# ------------------------------------------------------------------ lifecycle


def test_dispose_stops_timers_and_is_idempotent(qtbot, doc):
    service = PreviewService(doc, debounce_ms=10)
    assert service._estimate_timer.isActive()
    service.dispose()
    assert not service._estimate_timer.isActive()
    assert service._pending is None
    assert service._render_in_flight is False

    doc.apply(doc.state.with_(speed=2.0), "Change speed")  # must not re-arm anything
    assert not service._estimate_timer.isActive()
    assert service.estimated_bytes is None
    service.dispose()  # second call is a no-op


def test_dispose_drops_an_in_flight_render(qtbot, doc):
    service = PreviewService(doc, debounce_ms=10)
    seen: list[int] = []
    service.frameReady.connect(lambda i, _img: seen.append(i))
    service.geometry_enabled = True  # asks for frame 0 off-thread
    service.dispose()
    qtbot.wait(200)
    assert seen == []


def test_geometry_change_asks_for_the_current_frame(qtbot, doc):
    service = PreviewService(doc, debounce_ms=10)
    try:
        doc.set_current_index(6)
        with qtbot.waitSignal(service.frameReady, timeout=5000) as sig:
            service.geometry_enabled = True
        assert sig.args[0] == 6
    finally:
        service.dispose()


def test_current_index_follows_only_with_geometry_on(qtbot, svc, doc):
    seen: list[int] = []
    svc.frameReady.connect(lambda i, _img: seen.append(i))
    doc.set_current_index(2)  # geometry off: the canvas keeps using its own frame
    qtbot.wait(150)
    assert seen == []

    svc.geometry_enabled = True  # renders the CURRENT frame, which is 2
    qtbot.waitUntil(lambda: 2 in seen, timeout=5000)
    doc.set_current_index(5)
    qtbot.waitUntil(lambda: 5 in seen, timeout=5000)
    assert seen[-1] == 5
