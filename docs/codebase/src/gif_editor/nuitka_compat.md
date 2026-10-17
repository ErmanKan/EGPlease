# `src/gif_editor/nuitka_compat.py`

> Keeps a probe that Nuitka 4.3 injects into PySide6 builds from running, because running it corrupts memory and crashed about half of all starts of the packaged app.

## Where it sits
- **Layer:** packaging support (imports `PySide6.QtCore` inside the function only)
- **Used by:** `app.py` (`main`, right after the Qt imports, before `QApplication` and before any `Signal.connect`); `tests/ui/test_nuitka_compat.py`.
- **Uses:** nothing in the project.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `skip_pyside_connect_probe()` | function → `str` | If `SignalInstance.connect` is Nuitka's `patched_connect`, set its cached probe answer to `False` ("compiled methods don't leak") so the probe never runs. Returns a status line (`app.main` prints it as a `GUI STAGE` marker in smoke mode): `"Nuitka connect probe skipped"`, `"…had already run (result …)"`, or `"no Nuitka connect patch (not a compiled build)"`. |
| `PROBE_RESULT` | constant | `"_wrap_compiled_methods"`: the global in Nuitka's injected module that caches the probe's answer (`None` = not run yet). |

## The bug it works around
Nuitka's package configuration (`nuitka/plugins/standard/standard.nuitka-package.config.yml`, entry `module-name: 'PySide6'`, `post-import-code`) replaces `QtCore.SignalInstance.connect`/`disconnect` with `patched_connect`/`patched_disconnect`. Their purpose: non-limited-API Shiboken builds call `PyFunction_GetDefaults` on compiled functions and leak a `SystemError`; for those, compiled bound methods are wrapped in `functools.partial`. To find out whether the running PySide6 is affected, the first `connect` of a compiled bound method runs `doesCompiledMethodLeak()`: it defines a class, connects a bound method of a throw-away instance to a throw-away `QObject`'s `destroyed` signal (twice), and deletes both.

While that `QObject` is destroyed (`QObject::~QObject` → `libpyside6`), PySide6 performs a `Py_DECREF` on a **compiled function object that has already been released** into Nuitka's free list. Nuitka keeps the free list's link in the object's first word, which is `ob_refcnt`, so the decrement turns a valid link `…740` into `…73f`. A few function creations later, `Nuitka_Function_New` takes that garbage address off the list and `_PyObject_GC_Resize` faults on it: **0xC0000005 on Windows, SIGSEGV on Linux**, always while `MainWindow` is being built (the first `connect` is in `Player.__init__`; the crash shows up in `TransportBar` when the next nested functions are created). Whether the decrement hits something that matters depends on the memory layout, hence "about half of all starts".

How it was proven (details in the [dev log](../../../04-development-log.md#root-cause-of-the-start-up-crash)): a debug build with symbols under gdb; a hardware watchpoint on the link word of released function objects caught the stale `Py_DECREF`, with the call stack running from `Player.__init__` → `patched_connect` → `protect` → `doesCompiledMethodLeak` → `Py_DECREF(sender)` → `QObject::~QObject` → `libpyside6`.

## Why answering `False` is correct
The probe's own comment: limited-API (abi3) Shiboken builds "use an attribute based fallback and are not affected". The official PySide6 wheels (including PySide6-Essentials, on Windows and Linux) are limited-API builds (`libpyside6.abi3.so`, `pyside6.abi3.dll`), so the probe would answer `False`. Pre-answering skips only the probe; `protect` still runs as designed.

## Invariants & gotchas
- Call it **before the first `Signal.connect`** of a compiled bound method; `tests/ui/test_nuitka_compat.py` checks it comes before `QApplication` and `MainWindow()` in `app.py`.
- It uses `connect.__globals__` (Nuitka's compiled functions have it) rather than a module name, so it does not depend on what Nuitka calls its injected module.
- From source (tests, `python -m gif_editor`) `connect` is PySide6's own and the function does nothing.
- **When upgrading Nuitka or PySide6:** check whether the probe still exists and still misbehaves (re-run the crash loop in the dev log); `test_pyside6_is_a_limited_api_build` fails if PySide6 stops being a limited-API build, which would make the `False` answer wrong.

## Tests
- `tests/ui/test_nuitka_compat.py`: no-op without the patch; pre-answers a `None` cache; leaves an existing answer alone; leaves an unrelated patch alone; PySide6 is a limited-API build; the call precedes `QApplication` and `MainWindow` in `app.main`.
- End to end: the packaged build's start-up loop (dev log) and the smoke test in CI.

## History
- Created 2026-10-17 after the root cause of the start-up crash was found.
