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


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled resource (e.g. ``resource_path("icons", "icon.ico")``)."""
    here = Path(__file__).resolve().parent / "resources"
    for part in parts:
        here = here / part
    if here.exists():
        return here
    base = os.environ.get("NUITKA_ONEFILE_DIR")
    if base:
        candidate = Path(base) / "gif_editor" / "resources"
        for part in parts:
            candidate = candidate / part
        if candidate.exists():
            return candidate
    return here  # let the caller see the missing path and handle it


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
