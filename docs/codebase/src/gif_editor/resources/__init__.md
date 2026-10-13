# `src/gif_editor/resources/__init__.py`

> Finds files that ship with the app (the icons), both when running from the source tree and inside a Nuitka onefile build (M5).

## Where it sits
- **Layer:** shared helper (no Qt; `os` and `pathlib` only)
- **Used by:** `gif_editor/app.py` (`icon_path()` → `QApplication.setWindowIcon`); `tests/core/test_resources.py`.
- **Uses:** the data files in `src/gif_editor/resources/icons/` ([what they are](../../../config-files.md#srcgif_editorresourcesicons)), written by [`scripts/make_icon.py`](../../../scripts/make_icon.md); the `NUITKA_ONEFILE_DIR` environment variable inside a onefile build.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `resource_path(*parts) -> Path` | function | Absolute path of a bundled file, e.g. `resource_path("icons", "icon.ico")`. Returns the first candidate that exists; if none exists, the candidate in the package folder (so the caller can report it). **Never raises.** |
| `icon_path() -> Path \| None` | function | The best icon for this platform: on Windows `icon.ico`, else `icon-256.png`; falls back to the other format; `None` if neither exists. |
| `_bundle_roots() -> list[Path]` | helper | The folders searched, most specific first. |

`__all__ = ["icon_path", "resource_path"]`.

## How it works
1. **Roots** (`_bundle_roots`):
   1. the folder this file is in, `…/gif_editor/resources/` (from `__file__`);
   2. if `NUITKA_ONEFILE_DIR` is set: `$NUITKA_ONEFILE_DIR/gif_editor/resources/`.
2. **`resource_path(*parts)`** joins `parts` onto each root and returns the first that exists, else the first candidate.
3. **`icon_path()`** tries the platform's preferred format first (`sys.platform == "win32"` → `.ico`, which carries every size Windows wants; elsewhere the 256 px PNG) and then the other one.

*Why two roots:* the source tree and a onefile build lay the files out differently. A onefile `.exe` is an archive: at start it unpacks the program and its data into a temporary folder and runs from there. Nuitka passes that folder in `NUITKA_ONEFILE_DIR`. Inside the unpacked program `__file__` also points into that folder, so root 1 normally works in both cases; root 2 is a fallback for the bootstrap phase, when `__file__` may not yet point at the unpacked tree.

*Why it must not raise:* a missing icon is cosmetic. `app.main` only calls `setWindowIcon` when `icon_path()` is not `None`, so the app starts without an icon rather than not at all.

## Invariants & gotchas
- **The root is `resources/` itself.** `__file__` is `…/resources/__init__.py`, so its parent *is* the resources folder. **The first version appended `"resources"` again** and looked in `resources/resources/icons/`. Nothing raised: `icon_path()` silently returned `None`, and the app **never set its window icon**, from source or in a build. The new `tests/core/test_resources.py` caught it on its first run; it was fixed in `a2e41d0`, and the window icon was then verified to be non-null. Lesson: a "must not raise" helper needs a test that the happy path finds something, or failures stay invisible.
- The files must be packed into the build: `scripts/build.py` passes `--include-package-data=gif_editor` for that.
- The `.exe`'s icon in Explorer comes from a different place: `--windows-icon-from-ico` embeds `icon.ico` into the executable's Windows resources at build time. This module covers the **running window** (title bar, Alt+Tab, taskbar while running).
- Import is cheap and Qt-free; keep it that way (it is imported by `app.main` before the window is built, and by core tests).

## Tests
- `tests/core/test_resources.py` ([page](../../../tests/core/test_resources.md)), 5 cases: the icons folder and `icon.ico` are found from source; `.ico` on Windows and `.png` elsewhere; `None` when nothing exists; the `NUITKA_ONEFILE_DIR` fallback with `__file__` pointed elsewhere; a missing file returns an informative path without raising.
- **Gap:** an actual onefile build is only checked indirectly (the smoke test does not assert the icon).

## History
- `3531ca0` (M5): added (with the `resources/resources` bug).
- `a2e41d0` (M5): roots fixed and factored into `_bundle_roots`; `resource_path` returns the first existing candidate ([dev log, Milestone 5](../../../../04-development-log.md#the-icon-that-never-loaded)).
