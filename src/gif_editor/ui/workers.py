"""Run blocking work (decode, thumbnails, Generate) off the GUI thread.

``run_async(fn, ...)`` executes ``fn`` in the global ``QThreadPool`` and delivers the
result back on the GUI thread through Qt signals (queued connection, because the
``_Relay`` QObject lives on the GUI thread). Callers never touch threads directly.

Cancellation is cooperative: pass a ``threading.Event`` into ``fn`` yourself and set it.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

_live: set[_Relay] = set()  # keeps relays alive until their task reports back
_lock = threading.Lock()


class _Relay(QObject):
    finished = Signal(object)
    failed = Signal(str, object)  # (message, exception)
    progress = Signal(int, object)  # (done, total | None)


def _job(
    fn: Callable[..., Any], relay: _Relay, with_progress: bool, exited: threading.Event
) -> Callable[[], None]:
    """The function a pool thread runs: call ``fn``, report through ``relay``.

    This is a plain function handed to ``QThreadPool.start(callable)``, not a Python
    subclass of ``QRunnable``. With a subclass, Qt calls a Python-overridden ``run()`` on a
    C++-owned object from a pool thread, and PySide must keep that object's Python wrapper
    alive and dispatch the override across threads. In the test suite that combination
    crashed once (segmentation fault in a pool thread) and hung once (deadlock between
    garbage collection on the GUI thread and a pool thread entering ``run()``), each about
    once in 20 full runs. A plain callable has no wrapper object to manage.
    """

    def run() -> None:  # executes on a pool thread
        try:
            if with_progress:
                result = fn(lambda done, total=None: relay.progress.emit(done, total))
            else:
                result = fn()
        except BaseException as exc:
            msg = str(exc) or type(exc).__name__
            relay.failed.emit(msg, exc)
            traceback.print_exc()
        else:
            relay.finished.emit(result)
        finally:
            # The GUI thread may run the callback (and want to delete the relay) before
            # emit() above has returned here. Deleting a QObject while another thread is
            # inside one of its emits is undefined behaviour, so the relay is only deleted
            # once this flag says the worker has let go of it (see ``_release``).
            exited.set()

    return run


def run_async(
    fn: Callable[..., Any],
    *,
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str, BaseException], None] | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
    pool: QThreadPool | None = None,
) -> None:
    """Run ``fn()`` on a pool thread; callbacks run on the GUI thread.

    If ``on_progress`` is given, ``fn`` is called as ``fn(progress)`` where
    ``progress(done, total=None)`` may be called from the worker thread.
    """
    relay = _Relay()
    exited = threading.Event()
    with _lock:
        _live.add(relay)

    def _release() -> None:
        if not exited.is_set():
            # The worker is still returning from emit(): try again shortly. This is a
            # window of microseconds, so it almost never loops more than once.
            QTimer.singleShot(1, _release)
            return
        with _lock:
            _live.discard(relay)
        relay.deleteLater()

    if on_progress is not None:
        relay.progress.connect(on_progress)

    def _done(result: object) -> None:
        try:
            if on_done is not None:
                on_done(result)
        finally:
            _release()

    def _fail(msg: str, exc: BaseException) -> None:
        try:
            if on_error is not None:
                on_error(msg, exc)
        finally:
            _release()

    relay.finished.connect(_done)
    relay.failed.connect(_fail)
    (pool or QThreadPool.globalInstance()).start(_job(fn, relay, on_progress is not None, exited))
