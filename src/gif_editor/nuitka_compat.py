"""Work around a memory-corrupting probe that Nuitka 4.3 injects into PySide6 builds.

What happens without this (found 2026-10-17, see docs/04-development-log.md, section
"Root cause of the start-up crash"): Nuitka's PySide6 support replaces
``SignalInstance.connect`` with ``patched_connect``. On the first ``connect`` of a compiled
bound method it runs a probe, ``doesCompiledMethodLeak``: it connects a throw-away method
to a throw-away ``QObject`` and deletes both. While that ``QObject`` is destroyed, PySide6
drops a reference to a compiled function object that has already been released, so the
``Py_DECREF`` lands on Nuitka's free list of function objects (the list's link lives in the
reference-count field) and corrupts it. Depending on the memory layout the app then
crashes a few function creations later: on about half of all starts, with an access
violation on Windows (0xC0000005) or a segmentation fault on Linux, always while the
window is being built. A hardware watchpoint under gdb caught the stale write in the act.

The probe only decides whether a second workaround is needed, and its own comment says
only *non-limited-API* PySide6 builds need it. The official PySide6 wheels are
limited-API (abi3) builds, so the answer is known: "not needed". Setting that answer
before the first ``connect`` means the probe never runs. ``tests/ui/test_nuitka_compat.py``
fails if a future PySide6 wheel is not a limited-API build, so this assumption is checked.

In plain Python (tests, running from source) ``connect`` is not patched and this does
nothing. Remove it once Nuitka fixes the probe (check its changelog when upgrading).
"""

from __future__ import annotations

#: The global in Nuitka's injected module that caches the probe's answer (None = not run).
PROBE_RESULT = "_wrap_compiled_methods"


def skip_pyside_connect_probe() -> str:
    """Pre-answer Nuitka's ``connect`` probe so it never runs. Returns a status for logs.

    Call it after importing PySide6 and before the first ``Signal.connect``.
    """
    from PySide6 import QtCore

    connect = QtCore.SignalInstance.connect
    # Nuitka's patched_connect is a compiled function: its module globals hold the cache.
    globals_ = getattr(connect, "__globals__", None)
    if not isinstance(globals_, dict) or PROBE_RESULT not in globals_:
        return "no Nuitka connect patch (not a compiled build)"
    if globals_[PROBE_RESULT] is None:
        globals_[PROBE_RESULT] = False  # limited-API PySide6: compiled methods don't leak
        return "Nuitka connect probe skipped"
    return f"Nuitka connect probe had already run (result {globals_[PROBE_RESULT]})"
