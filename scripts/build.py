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

Rebuilds reuse Nuitka's own cache in the user cache directory (override it with the
`NUITKA_CACHE_DIR` environment variable); per-build working files go to
`out/dist/__main__.build/`. On Linux in the dev container most of the build time is
Nuitka's dependency scan (`ldd` once per bundled Qt library, with a 104-directory
LD_LIBRARY_PATH, in a filesystem with slow failed lookups), not the C compile; Windows uses
a different dependency walker and does not have that cost.
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

#: Qt plugin families the app never uses (see build_command for why they are dropped).
UNUSED_QT_PLUGINS = (
    "iconengines",  # SVG icon engine: the app has no SVG icons
    "mediaservice",  # audio/video
    "printsupport",  # no printing
    "platformthemes",  # Linux desktop-theme integration (GTK, portals)
    "tls",  # SSL for networking: the app is offline
    "egldeviceintegrations",  # Linux embedded EGL
    "xcbglintegrations",  # OpenGL on X11: the canvas uses raster QGraphicsView
    "wayland-shell-integration",  # Linux Wayland: X11/XWayland is used instead
    "wayland-decoration-client",
    "wayland-graphics-integration-client",
)
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
        # Of Nuitka's "sensible" Qt plugin families the app needs only `platforms` (the
        # windowing backend), `imageformats` (QIcon reads the .ico window icon through
        # it on Windows) and `styles`. The rest are dropped: smaller exe, and on Linux each
        # bundled library costs a slow `ldd` dependency scan (measured: the Wayland/TLS/EGL
        # families alone kept a build in that scan for 30+ minutes). Names that do not
        # exist on the build platform are ignored by Nuitka (it discards from a set), so
        # one list serves Windows and Linux.
        "--noinclude-qt-plugins=" + ",".join(UNUSED_QT_PLUGINS),
        # --- behaviour ----------------------------------------------------------------
        # Keep stdout/stderr attached when launched from a terminal (useful for a crash
        # report and required by the smoke test); without this a GUI app has no console.
        f"--windows-console-mode={'attach' if windows else 'disable'}",
        "--assume-yes-for-downloads",  # Nuitka's own dependency walker, on first build
        # --- start-up speed -----------------------------------------------------------
        # Unpack ONCE per version into the user's cache folder and reuse it:
        # %LOCALAPPDATA%\Erman K\GIF Editor\<version> on Windows, $XDG_CACHE_HOME (or
        # ~/.cache)/Erman K/GIF Editor/<version> on Linux. Nuitka's default unpacks the
        # whole payload (150-230 MB) into a new %TEMP%\onefile_<pid>_<time> folder on EVERY
        # start and deletes it on exit: slow on Windows (Defender scans every new DLL),
        # it fails on a nearly full disk, and a crashed or killed start leaves the folder
        # behind. With a static path Nuitka switches to its cached mode: each start compares
        # every file's CRC32 with the payload and rewrites only mismatches
        # (OnefileBootstrap.c), so a rebuilt .exe never runs stale files.
        "--onefile-tempdir-spec={CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}",
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
