"""Smoke-test a built GifEditor binary: it starts, edits and writes a GIF, and shows its window.

Run after `scripts/build.py`:

    .venv/bin/python scripts/smoke_build.py [path/to/binary]
    # default: out/dist/GifEditor.exe (Windows) or out/dist/GifEditor (Linux)

A frozen onefile binary cannot be imported into, so it is run as a child process, three times:

1. `--edit-spec` on a missing file: must exit 1 without a traceback. Proves the interpreter
   and the bundled core start and fail cleanly.
2. `--edit-spec` with a real edit (trim, delete, crop, resize): must exit 0 and write a
   32x24 GIF. Proves Pillow, numpy and the whole pipeline are bundled. This path never
   imports Qt.
3. `--smoke-gui` on a real GIF: must exit 0. The real window comes up offscreen, the file is
   decoded and shown, then the app quits by itself. Proves the Qt half of the bundle
   (PySide6, the platform plugin, image plugins).

Pass/fail is decided by **exit codes and the written file only**. The printed RESULT/GUI
lines are diagnostics: a Windows GUI executable built with console mode "attach" may not
send stdout to a pipe, and the check must not depend on that.

The binary is copied to a fresh temporary directory first, and TMPDIR points there for the
onefile bootstrap (it unpacks and execs a child). In the Linux dev container the project
drive and /tmp are mounted noexec, so set TMPDIR to an executable directory (e.g. under
$HOME) before running this script there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def default_binary() -> Path:
    for name in ("GifEditor.exe", "GifEditor"):  # Windows first
        p = ROOT / "out" / "dist" / name
        if p.exists():
            return p
    raise SystemExit("no built binary in out/dist: run scripts/build.py first")


def make_fixture(path: Path, frames: int = 8) -> None:
    sys.path.insert(0, str(ROOT / "tests"))
    from gifgen import make_gif, solid_frames

    make_gif(path, solid_frames(frames, (64, 48)), 100)


def run(
    binary: Path, args: list[str], workdir: Path, timeout: int = 120
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"  # headless: no display in this container or CI
    env["TMPDIR"] = str(workdir)  # onefile unpacks + execs here, so it must be executable
    return subprocess.run(
        [str(binary), *args], cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout
    )


def main() -> int:
    binary = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else default_binary()
    if not binary.exists():
        raise SystemExit(f"no such binary: {binary}")
    work = Path(tempfile.mkdtemp(prefix="gifedit-smoke-"))
    run_bin = work / binary.name
    shutil.copy2(binary, run_bin)
    run_bin.chmod(0o755)
    print(f"binary: {binary}  ({binary.stat().st_size / 1e6:.1f} MB)")
    failures: list[str] = []

    def record(step: str, ok: bool, res: subprocess.CompletedProcess, extra: str = "") -> None:
        lines = [ln for ln in (res.stdout + res.stderr).splitlines() if ln.strip()]
        shown = next((ln for ln in lines if ln.startswith(("RESULT", "ERROR", "GUI"))), "")
        print(f"{step:22s} exit={res.returncode} {'ok' if ok else 'FAILED'}  {shown}{extra}")
        if not ok:
            failures.append(f"{step}: exit {res.returncode}\n" + "\n".join(lines[-30:]))

    try:
        src = work / "in.gif"
        make_fixture(src)

        # 1. Clean failure on a missing file.
        res = run(
            run_bin, ["--edit-spec", str(work / "missing.gif"), f"out={work / 'x.gif'}"], work
        )
        record("1. missing file", res.returncode == 1 and "Traceback" not in res.stderr, res)

        # 2. A real edit + generate, no Qt.
        out = work / "out.gif"
        spec = f"trim=0:400,delete=2,crop=8:6:40:30,size=32x24,colors=64,out={out}"
        res = run(run_bin, ["--edit-spec", str(src), spec], work)
        size = None
        if out.exists():
            from PIL import Image

            with Image.open(out) as im:
                size = im.size
        record(
            "2. edit + generate", res.returncode == 0 and size == (32, 24), res, f" wrote={size}"
        )

        # 3. The real window, offscreen, opens the GIF and quits by itself.
        res = run(run_bin, ["--smoke-gui", str(src)], work)
        record("3. GUI opens a GIF", res.returncode == 0, res)
    except subprocess.TimeoutExpired as exc:
        failures.append(f"timed out after {exc.timeout} s: {exc.cmd}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print("\nFAILED:\n" + "\n\n".join(failures))
        return 1
    print("\nOK: the built binary starts, edits and writes a GIF, and opens one in its window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
