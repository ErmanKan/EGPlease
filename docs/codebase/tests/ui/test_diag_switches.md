# `tests/ui/test_diag_switches.py`

> Checks that the temporary `[DIAG]` crash-investigation switches do what `scripts/smoke_build.py` relies on, so a clean run under a switch is real evidence.

## What it covers (4 tests)
| Test | Checks |
|---|---|
| `test_std_icons_switch_uses_qt_standard_icons` | with `GIF_EDITOR_DIAG_STD_ICONS=1` the transport icons are exactly Qt's standard ones, also after the play/pause swap |
| `test_without_switch_icons_are_the_theme_ones` | without it they are not (the theme's icons) |
| `test_diag_variants_switch_one_suspect_each` | the first variant is the failing step; the env switches are exactly the two known ones, at most one per variant; the native variant only on Windows |
| `test_find_cdb_returns_none_or_an_existing_file` | `find_cdb` never returns a path that does not exist |

## Gaps
- `GIF_EDITOR_DIAG_QT_ARGV` is not unit-tested: pytest-qt creates the `QApplication` before any test runs, so `app.main` reuses it and never builds one with the reduced arguments. The switch is two lines in `app.main`.

## History
- Created 2026-10-17 with the switches ([dev log](../../../04-development-log.md#windows-gui-smoke-crash-in-the-packaged-exe)). Delete this file together with the switches.
