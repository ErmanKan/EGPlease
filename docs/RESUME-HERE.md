# RESUME HERE — Milestone 5 (packaging), one step from done

**Written:** 2026-10-13, updated 2026-10-14. **Repo:** `/workspace/projects/gif-editor` (host `F:\Projects\gif-editor`), branch `main`.
Everything is committed. Tests: **752 passed + 2 xfailed**, lint clean.

| Milestone | Status |
|---|---|
| M1–M4 | ✅ Done |
| M5 Packaging | 🔄 `GifEditor.exe` built and smoke-tested by GitHub Actions; clean-machine test and licence bundle open |

## What M5 has (all committed)
- `scripts/build.py` — Nuitka 4.3 onefile recipe, shared by Windows and Linux; drops 10 unused Qt plugin families.
- `scripts/check_build_flags.py` — parses every build flag with Nuitka's own parser, for both platforms, in seconds.
- `scripts/make_icon.py` (+ `--check`, pixel comparison) and the icons in `src/gif_editor/resources/icons/`.
- `scripts/smoke_build.py` — 3 steps against a built binary; pass/fail by exit code and output file.
- `src/gif_editor/headless.py` (`--edit-spec`) and `--smoke-gui` in `app.py`: the two paths a built binary is checked with.
- `.github/workflows/build-exe.yml` + `packaging/build-requirements.txt`.
- Docs: per-file pages for all of the above, dev-log "Milestone 5", testing guide, README "Build the .exe".

## Proven so far
The same recipe built a **Linux** binary (61.6 MB, 19 min) that passed **all 3 smoke steps**: clean failure on a missing
file, a real edit writing a correct 32×24 GIF, and the real Qt window opening a GIF offscreen. Details:
[dev log, Milestone 5](04-development-log.md#milestone-5-packaging).

## Update 2026-10-14: the Windows build is green
The repo is on GitHub (`origin` = github.com/ErmanKan/EGPlease). Run 38478763559 (commit `94c54fc`) of
"Build GifEditor.exe" passed every step, including all 3 smoke steps; the earlier GUI-step crash (0xC0000005) did not
recur, and it is not proven which change cured it. Artifact `GifEditor-windows` (33.6 MB zip) expires 2026-11-12.
The README was rewritten for users (stack + why, basic usage).

**Dark-mode buttons fixed** (`ui/theme.py`, [dev log](04-development-log.md#dark-mode-buttons)), verified only on an
approximated Windows dark palette: **look at the next `.exe` in Windows dark mode** (playback buttons, Generate,
a disabled Reset button) and in light mode.

**Pushing:** the container has no GitHub credentials; push from the PC (`git push` in `F:\Projects\gif-editor`).

**Docker image added** (`Dockerfile`, README *Docker*, [dev log](04-development-log.md#docker-image)): GUI over Qt's VNC
server (default) or X11, headless edits, a `test` target. Never built locally (no Docker here): **check the first run of
the "Docker image" workflow** after the push and fix what it finds.

**Next:** the Docker workflow's first run, the dark-mode look check, the clean-Windows-11 test below, then the licence
bundle.

## How to build the `.exe` on Windows (cannot be done from the container)
Nuitka cannot cross-compile, and the container has no Windows toolchain. Either:

**A. On the PC** (PowerShell, repo root; Nuitka downloads a C compiler on first run with `--assume-yes-for-downloads`):
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt -r packaging\build-requirements.txt
.venv\Scripts\python scripts\check_build_flags.py
.venv\Scripts\python scripts\build.py
.venv\Scripts\python scripts\smoke_build.py out\dist\GifEditor.exe
```
**B. GitHub Actions:** Actions → "Build GifEditor.exe" → Run workflow; download the `GifEditor-windows` artifact.

Then the M5 exit criterion ([02-plan §6](02-plan.md#6-milestones)): the `.exe` runs on a **clean Windows 11 machine
without Python**, from any folder and from a USB stick. Still open after that: the licence bundle in
`packaging/licenses/` (only `.gitkeep`), and code signing (optional).

## Things to know before building on Windows
- **The user's C: drive was full** (232 GB of 232 GB, 216 MB free, seen 2026-10-13). A Windows build needs several GB
  on the drive holding `%TEMP%` and Nuitka's cache (`%LOCALAPPDATA%\Nuitka`), and the onefile `.exe` unpacks about
  150 MB into `%TEMP%` on every start. Free space on C: first, or set `NUITKA_CACHE_DIR` and `TEMP`/`TMP` to F:.
  A full disk shows up as "Input/output error" when unpacking, not as "disk full".
- The Linux-only build costs (the `ldd` scan) do not apply on Windows; expect a much shorter dependency phase.

## Known issues carried forward
- `tests/core/test_timeline.py::test_performance_10k_frames` (50 ms wall-clock budget) can fail under heavy load,
  e.g. during a build; it passes alone.
- Filmstrip fixed at 140 px tall (small windows get a ~184 px canvas); the size estimate can be ~0.67× low on long GIFs.

## Container quirks (dev environment only)
- Tests: `scripts/test.sh`, `scripts/test-hidpi.sh`. Temp files only under `out/` (gitignored); never `/tmp`.
- `/tmp`, `/dev/shm`, `/var/tmp` and the project drive are `noexec`; `/root` is the host's C: drive (full).
  To run a built Linux binary: `TMPDIR` under `/home` (container disk) and `LD_LIBRARY_PATH` at `.devlibs/`
  (no system libEGL). A local Linux build needs `.venv/bin` on `PATH` (for the venv's `patchelf`).
- `pkill -f`/`pgrep -f` inside `bash -lc` matches its own shell: kill by PID.
- Delegation workers are not durable and a provider key can be revoked mid-run; commit early and keep this note current.

## Full history
`docs/04-development-log.md` and `docs/02-plan.md` (with its deviations section).
