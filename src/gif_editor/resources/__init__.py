"""Locate bundled resource files (icons) in both a source checkout and a frozen build.

Two layouts must work:
- **Source / tests:** `src/gif_editor/resources/...`, imported as a package.
- **Nuitka onefile:** the build packs the tree into the executable and unpacks it into a
  temporary directory at startup, whose path Nuitka passes in the `NUITKA_ONEFILE_DIR`
  environment variable. `__file__` also points inside that directory, so it is used first
  and the environment variable is the fallback for onefile's bootstrap phase.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["icon_path", "resource_path"]


def _bundle_roots() -> list[Path]:
    """Directories to search for bundled files, most specific first.

    ``__file__`` is inside `gif_editor/resources/`, so *that* directory is the root: an
    earlier version appended "resources" again and resolved `resources/resources/icons`,
    which silently disabled the window icon (found by tests/core/test_resources.py).
    Inside a Nuitka onefile the tree is unpacked to a temporary directory; `__file__` points
    there too, but the environment variable is the fallback used while the bootstrap runs.
    """
    roots = [Path(__file__).resolve().parent]
    base = os.environ.get("NUITKA_ONEFILE_DIR")
    if base:
        roots.append(Path(base) / "gif_editor" / "resources")
    return roots


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled resource (e.g. ``resource_path("icons", "icon.ico")``).

    Returns the first existing candidate; when nothing exists, the path in the source layout
    is returned so the caller can inspect or report it (it must not raise: a missing icon
    must not stop the app from starting).
    """
    candidates = [root.joinpath(*parts) for root in _bundle_roots()]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def icon_path() -> Path | None:
    """The best icon file for this platform, or ``None`` if none was bundled."""
    import sys

    names = (
        ("icon.ico", "icon-256.png") if sys.platform == "win32" else ("icon-256.png", "icon.ico")
    )
    for name in names:
        p = resource_path("icons", name)
        if p.exists():
            return p
    return None
