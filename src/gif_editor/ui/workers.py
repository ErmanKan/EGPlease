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

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_live: set[_Relay] = set()  # keeps relays alive until their task reports back
_lock = threading.Lock()


class _Relay(QObject):
    finished = Signal(object)
    failed = Signal(str, object)  # (message, exception)
    progress = Signal(int, object)  # (done, total | None)


class _Runnable(QRunnable):
    def __init__(self, fn: Callable[..., Any], relay: _Relay, with_progress: bool) -> None:
        super().__init__()
        self._fn = fn
        self._relay = relay
        self._with_progress = with_progress

    def run(self) -> None:  # executes on a pool thread
        try:
            if self._with_progress:
                result = self._fn(lambda done, total=None: self._relay.progress.emit(done, total))
            else:
                result = self._fn()
        except BaseException as exc:
            msg = str(exc) or type(exc).__name__
            self._relay.failed.emit(msg, exc)
            traceback.print_exc()
        else:
            self._relay.finished.emit(result)


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
    with _lock:
        _live.add(relay)

    def _release() -> None:
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
    (pool or QThreadPool.globalInstance()).start(
        _Runnable(fn, relay, with_progress=on_progress is not None)
    )
