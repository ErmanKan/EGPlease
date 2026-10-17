# `tests/ui/test_nuitka_compat.py`

> Tests the workaround for Nuitka's PySide6 `connect` probe, and the assumption it rests on.

## What it covers (6 tests)
| Test | Checks |
|---|---|
| `test_noop_when_connect_is_not_patched` | from source, `connect` is PySide6's own: nothing changes |
| `test_pre_answers_the_probe` | a fake `patched_connect` whose `__globals__` hold `_wrap_compiled_methods = None` gets `False` |
| `test_leaves_an_existing_answer_alone` | an answer that is already there (`True`) is kept |
| `test_other_patch_without_the_cache_is_left_alone` | some other patched `connect` without the cache variable is untouched |
| `test_pyside6_is_a_limited_api_build` | the installed PySide6 ships `libpyside6.abi3.so` (Linux) / `pyside6.abi3.dll` (Windows); if not, answering `False` would be wrong |
| `test_app_main_calls_it_before_any_widget_exists` | in `app.py` the call comes before `QApplication(...)` and `MainWindow()` |

## Helpers
- `fake_patched_connect(globals_)`: builds a plain function whose `__globals__` is the given dict (`types.FunctionType(code, globals)`), standing in for Nuitka's compiled `patched_connect`. `monkeypatch` restores the real `connect` afterwards.

## Gaps
- The real Nuitka patch exists only in a compiled build; it is exercised by the packaged-build start-up loop and the smoke test, not here.

## History
- Created 2026-10-17 with `nuitka_compat.py` ([dev log](../../../04-development-log.md#root-cause-of-the-start-up-crash)).
