"""Build the single-file GifEditor executable with Nuitka.

Usage:
    Windows (this is the one that produces GifEditor.exe):
        .venv\\Scripts\\python scripts\\build.py
    Linux dev container (the same recipe; produces a Linux binary and proves the recipe
    before it is run on Windows):
        .venv/bin/python scripts/build.py

Then check the result:
    .venv/bin/python scripts/smoke_build.py

Onefile + the PySide6 plugin, the icon and Windows version metadata, and the include rules
the app needs (Nuitka cannot discover a package it is only told about by a script path).
The result lands in `out/dist/`. Nuitka **cannot cross-compile**: a Windows `.exe` must be
built on Windows, which is what `.github/workflows/build-exe.yml` does.

A rebuild reuses Nuitka's cache under `out/nuitka-build/`; changing only Python code is fast,
re-running after a dependency change is slow.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUT = ROOT / "out"
DIST = OUT / "dist"
ICONS = SRC / "gif_editor" / "resources" / "icons"

APP_NAME = "GifEditor"
VERSION_FALLBACK = "0.0.0"


def version() -> str:
    """The app version, read from `src/gif_editor/__init__.py` (single source of truth)."""
    init = SRC / "gif_editor" / "__init__.py"
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return VERSION_FALLBACK


def build_command(ver: str, *, windows: bool | None = None) -> list[str]:
    """The Nuitka command line for this platform.

    Every flag here is here for a reason that cost a failed build, so they are commented.
    ``windows`` can be passed explicitly so the Windows command line can be validated on a
    Linux machine (see scripts/check_build_flags.py); it defaults to the real platform.
    """
    if windows is None:
        windows = platform.system() == "Windows"
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        # --- what to build ------------------------------------------------------------
        # The package, not just __main__.py: pointed at a lone script, Nuitka follows that
        # file's imports but cannot resolve `gif_editor.app` (a package module the script
        # imports by name), and the frozen app died with "No module named 'gif_editor.app'".
        "--include-package=gif_editor",
        # Icons are data, not code: packed as files next to the code inside the archive.
        "--include-package-data=gif_editor",
        str(SRC / "gif_editor" / "__main__.py"),
        # --- output ------------------------------------------------------------------
        "--onefile",  # a single self-contained executable
        f"--output-dir={DIST}",
        f"--output-filename={APP_NAME}",
        f"--report={OUT / 'nuitka-report.xml'}",
        "--enable-plugin=pyside6",  # ships the Qt plugins (platform, image formats)
        # --- behaviour ----------------------------------------------------------------
        # Keep stdout/stderr attached when launched from a terminal (useful for a crash
        # report and required by the smoke test); without this a GUI app has no console.
        f"--windows-console-mode={'attach' if windows else 'disable'}",
        "--assume-yes-for-downloads",  # Nuitka's own dependency walker, on first build
        # Drop two heavy build-time packages this app never imports at runtime.
        "--noinclude-pytest-mode=nofollow",
        "--noinclude-setuptools-mode=nofollow",
        # --- metadata (visible in Explorer's file properties) --------------------------
        "--company-name=Erman K",
        "--product-name=GIF Editor",
        f"--file-version={ver}",
        f"--product-version={ver}",
        "--file-description=Offline desktop GIF editor",
        "--copyright=MIT",
    ]
    if windows:
        # The icon in Explorer + the taskbar; the running window sets its own from
        # resources/ at runtime (see gif_editor.app), which a onefile build must carry too.
        cmd.append(f"--windows-icon-from-ico={ICONS / 'icon.ico'}")
    else:
        cmd.append(f"--linux-icon={ICONS / 'icon-256.png'}")
    return cmd


def main() -> int:
    ver = version()
    print(f"Building {APP_NAME} {ver} for {platform.system()}...")
    if not (SRC / "gif_editor" / "__main__.py").exists():
        raise SystemExit("src/gif_editor/__main__.py is missing; run from the repo root")
    if platform.system() == "Windows" and not (ICONS / "icon.ico").exists():
        raise SystemExit(f"missing {ICONS / 'icon.ico'}: run scripts/make_icon.py")
    DIST.mkdir(parents=True, exist_ok=True)
    cmd = build_command(ver)
    print(" ".join(cmd))
    # `--include-package=gif_editor` is resolved through the *build* interpreter's import
    # path, which does not contain `src/` (the app is not installed, it is run from source).
    # Without this, Nuitka stops with "failed to locate package 'gif_editor'".
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), env.get("PYTHONPATH", "")) if p)
    result = subprocess.run(cmd, cwd=ROOT, check=False, env=env)
    if result.returncode != 0:
        print("Nuitka failed; see its output above.", file=sys.stderr)
        return result.returncode
    produced = sorted(p for p in DIST.glob(f"{APP_NAME}*") if p.is_file())
    if not produced:
        print("Nuitka reported success but produced no file in out/dist/", file=sys.stderr)
        return 1
    for p in produced:
        print(f"built {p.relative_to(ROOT)}  ({p.stat().st_size / 1e6:.1f} MB)")
    print("check it with: .venv/bin/python scripts/smoke_build.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
