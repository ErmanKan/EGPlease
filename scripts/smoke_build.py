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
import time
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


def exit_text(code: int) -> str:
    """``3221225477`` -> ``3221225477 (0xC0000005 access violation)``: Windows crash codes."""
    names = {
        0xC0000005: "access violation",
        0xC0000409: "stack buffer overrun / abort",
        0xC0000135: "DLL not found",
        0xC000007B: "bad DLL image",
    }
    u = code & 0xFFFFFFFF
    return f"{code} (0x{u:08X} {names[u]})" if u in names else str(code)


def run(
    binary: Path,
    args: list[str],
    workdir: Path,
    timeout: int = 120,
    platform: str | None = "offscreen",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    if platform:
        env["QT_QPA_PLATFORM"] = platform  # headless: no display in this container or CI
    env.update(extra_env or {})
    env["TMPDIR"] = str(workdir)  # must be executable (container); no unpacking goes here now
    # Linux: the onefile cache ({CACHE_DIR} = $XDG_CACHE_HOME) goes into the work folder, so
    # each smoke run starts cold and the container's noexec/full drives are avoided. Windows
    # ignores it: {CACHE_DIR} is always %LOCALAPPDATA% there.
    env["XDG_CACHE_HOME"] = str(workdir / "cache")
    return subprocess.run(
        [str(binary), *args], cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout
    )


#: Variants of step 3 for the diagnostics, each run DIAG_REPEATS times:
#: (label, arguments, platform, extra environment).
DIAG_REPEATS = 3


def diag_variants(src: Path) -> list[tuple[str, list[str], str | None, dict[str, str]]]:
    with_file = ["--smoke-gui", str(src)]
    variants = [
        ("offscreen + file (the failing step)", with_file, "offscreen", {}),
        ("offscreen, no file", ["--smoke-gui"], "offscreen", {}),
    ]
    if sys.platform == "win32":
        variants.append(("native windows platform + file", with_file, None, {}))
    return variants


def find_cdb() -> Path | None:
    """Microsoft's console debugger, if installed (Windows SDK 'Debugging Tools')."""
    found = shutil.which("cdb")
    candidates = [Path(found)] if found else []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        if base:
            candidates.append(Path(base) / "Windows Kits" / "10" / "Debuggers" / "x64" / "cdb.exe")
    return next((c for c in candidates if c.exists()), None)


def native_stack(run_bin: Path, src: Path, work: Path) -> None:
    """Windows: rerun the failing variant under cdb and print the native stack of the crash.

    -o follows the onefile bootstrap into the child process that runs the app. Access
    violations break only at second chance (after faulthandler printed the Python stack);
    there the debugger prints the faulting instruction, registers, 40 frames, and quits.
    """
    cdb = find_cdb()
    if cdb is None:
        print("\n--- native stack: cdb not found on this machine")
        return
    on_crash = ".echo ===NATIVE CRASH===; .lastevent; r; kn 40; .echo ===END==="
    cmds = f'sxn ibp; sxn epr; sxn ld; sxn ud; sxd -c2 "{on_crash}; q" av; g'
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", TMPDIR=str(work))
    cmd = [str(cdb), "-o", "-G", "-c", cmds, str(run_bin), "--smoke-gui", str(src)]
    try:
        res = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        print("\n--- native stack: cdb timed out")
        return
    out = (res.stdout or "") + (res.stderr or "")
    if "===NATIVE CRASH===" in out:
        crash = out[out.index("===NATIVE CRASH===") :]
        print("\n--- native stack (cdb):")
        for ln in crash.splitlines()[:90]:
            print("    " + ln)
    else:
        code = exit_text(res.returncode)
        print(f"\n--- native stack: no crash under cdb (exit {code}); last lines:")
        for ln in out.splitlines()[-25:]:
            print("    " + ln)


def diagnose_gui(run_bin: Path, src: Path, work: Path) -> None:
    """Step 3 failed: rerun it in variants, several times each, to locate the failure.

    Diagnostics only; they never change the verdict. Per variant: how often each exit code
    came up, and the output of the first failing run. Then, on Windows, the native stack.
    """
    for label, args, platform, extra in diag_variants(src):
        codes: dict[str, int] = {}
        first_fail: list[str] | None = None
        for _ in range(DIAG_REPEATS):
            try:
                res = run(run_bin, args, work, timeout=90, platform=platform, extra_env=extra)
            except subprocess.TimeoutExpired:
                codes["timeout"] = codes.get("timeout", 0) + 1
                continue
            key = exit_text(res.returncode)
            codes[key] = codes.get(key, 0) + 1
            if res.returncode != 0 and first_fail is None:
                first_fail = [ln for ln in (res.stdout + res.stderr).splitlines() if ln.strip()]
        tally = ", ".join(f"exit {k} x{n}" for k, n in codes.items())
        print(f"\n--- diagnostic: {label}: {tally}")
        for ln in (first_fail or [])[-40:]:
            print("    " + ln)
    if sys.platform == "win32":
        native_stack(run_bin, src, work)


def unpack_cache_dirs(workdir: Path) -> list[Path]:
    """The onefile cache folders (``.../Erman K/GIF Editor/<version>``) this platform uses."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", ""))
    else:
        base = workdir / "cache"
    product = base / "Erman K" / "GIF Editor"
    return sorted(p for p in product.glob("*") if p.is_dir()) if product.is_dir() else []


def temp_leftovers(workdir: Path) -> list[Path]:
    """``onefile_*`` folders: what Nuitka's default (per-start) unpacking leaves behind."""
    roots = {workdir}
    if sys.platform == "win32":
        roots.add(Path(tempfile.gettempdir()))
    return sorted(p for r in roots for p in r.glob("onefile_*") if p.is_dir())


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
        code = exit_text(res.returncode)
        print(f"{step:22s} exit={code} {'ok' if ok else 'FAILED'}  {shown}{extra}")
        if not ok:
            failures.append(f"{step}: exit {code}\n" + "\n".join(lines[-60:]))

    try:
        src = work / "in.gif"
        make_fixture(src)

        # Folders Nuitka's default per-start unpacking would leave in temp (step 4 compares).
        leftovers_before = set(temp_leftovers(work))

        # 1. Clean failure on a missing file. Also the cold start that step 4 reports.
        started = time.monotonic()
        res = run(
            run_bin, ["--edit-spec", str(work / "missing.gif"), f"out={work / 'x.gif'}"], work
        )
        cold_s = time.monotonic() - started
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
        if res.returncode != 0:
            diagnose_gui(run_bin, src, work)

        # 4. Start-up cache: the program is unpacked once into the user's cache folder and
        # reused, and nothing is unpacked into temp. Step 1 was the cold start (fresh cache
        # on Linux, a fresh runner on Windows); one more start here is the warm one. The
        # times are printed, not judged: they vary too much between machines.
        started = time.monotonic()
        res = run(
            run_bin, ["--edit-spec", str(work / "missing.gif"), f"out={work / 'x.gif'}"], work
        )
        warm_s = time.monotonic() - started
        caches = unpack_cache_dirs(work)
        new_leftovers = sorted(set(temp_leftovers(work)) - leftovers_before)
        detail = f" cold start {cold_s:.1f} s, warm start {warm_s:.1f} s"
        detail += f", cache={[str(c) for c in caches]}"
        if new_leftovers:
            detail += f" temp leftovers={[str(p) for p in new_leftovers]}"
        ok = res.returncode == 1 and bool(caches) and not new_leftovers
        record("4. start-up cache", ok, res, detail)
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
