"""Smoke-test a built GifEditor binary: it starts, opens a GIF, edits it and writes a GIF.

Run after `scripts/build.py`:

    .venv/bin/python scripts/smoke_build.py [path/to/binary]
    # default: out/dist/GifEditor (Linux) or out/dist/GifEditor.exe (Windows)

A frozen onefile binary cannot be imported into, so it is driven as a child process. The
app is a GUI, so the checks use the two non-GUI paths a packaged app must still support:

1. **It starts and exits cleanly** on `--help`-less startup with a bad path: exit code 1 and
   a plain error, no traceback (proves the interpreter, PySide6, Pillow and the self-test all
   loaded from inside the archive).
2. **It edits and writes a GIF** through `--edit-spec`, a hidden argument that runs one
   headless edit+generate to completion and prints a result line. Without it, a packaged app
   could only be checked by hand, and a broken bundle would ship.

The binary must be on an executable filesystem: this container mounts the project drive and
`/tmp` with `noexec`, so the script copies the binary to a temporary directory under `$HOME`
and sets `TMPDIR` there for the onefile bootstrap (which unpacks and execs a child).
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
    for name in ("GifEditor.exe", "GifEditor"):
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
    # Copy out of the project drive (mounted noexec here) into an executable temp dir.
    work = Path(tempfile.mkdtemp(prefix="gifedit-smoke-"))
    run_bin = work / binary.name
    shutil.copy2(binary, run_bin)
    run_bin.chmod(0o755)
    print(f"binary: {binary}  ({binary.stat().st_size / 1e6:.1f} MB)")
    failures = []
    try:
        # 1. A bad path must fail plainly, not with a traceback.
        bad = run(run_bin, [str(work / "missing.gif")], work)
        ok = bad.returncode == 1 and "Traceback" not in bad.stderr + bad.stdout
        print(f"1. bad path       exit={bad.returncode} {'' if ok else '  <-- FAILED'}")
        if not ok:
            failures.append(f"bad-path run: exit {bad.returncode}\n{bad.stdout}\n{bad.stderr}")

        # 2. A real edit + generate through the frozen app.
        src = work / "in.gif"
        make_fixture(src)
        out = work / "out.gif"
        spec = f"trim=0:400,delete=2,crop=8:6:40:30,size=32x24,colors=64,out={out}"
        res = run(run_bin, ["--edit-spec", str(src), spec], work)
        line = next((ln for ln in res.stdout.splitlines() if ln.startswith("RESULT")), "")
        wrote = out.exists() and out.stat().st_size > 0
        ok = res.returncode == 0 and bool(line) and wrote
        note = "" if ok else "  <-- FAILED"
        print(f"2. edit + generate exit={res.returncode} {line or '(no RESULT line)'}{note}")
        if not ok:
            failures.append(f"edit run: exit {res.returncode}\n{res.stdout}\n{res.stderr}")
        else:
            from PIL import Image

            with Image.open(out) as im:
                print(
                    f"   wrote {out.name}: {im.size[0]}x{im.size[1]}, "
                    f"{im.n_frames} frame(s), {out.stat().st_size} bytes"
                )
                assert im.size == (32, 24), f"expected 32x24, got {im.size}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print("\nFAILED:\n" + "\n".join(failures))
        return 1
    print("\nOK: the built binary starts, edits and writes a GIF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
