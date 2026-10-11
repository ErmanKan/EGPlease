# RESUME HERE — after Milestone 3

**Written:** 2026-10-11, at the end of Milestone 3.
**Repo:** `/workspace/projects/gif-editor` (host: `F:\Projects\gif-editor`), branch `main`.

## State

Everything is committed; there is no unverified or snapshot work left.
Tests: **640 passed + 2 expected failures** (the documented Pillow disposal-2 differences), lint clean.

| Milestone | Status |
|---|---|
| M1 Core engine (decoder, timeline, render, encoder, pipeline, self-test) | ✅ Done |
| M2 Window and inspector (document/undo, settings panel, canvas, timebar, filmstrip, player, transport, main window) | ✅ Done |
| M3 Crop and live preview (size estimate, `PreviewService`, `CropPanel`, `CropItem`, crop tool + Crop menu, P previews timing and geometry) | ✅ Done (last code commit `484382d`, then the M3 documentation pass) |
| M4 Hardening | ⏭ Next |
| M5 Single `.exe` (Nuitka onefile) | After M4 |

The M3 snapshot of `preview.py` mentioned in the previous version of this note was verified and fixed in `e904982`; the crop item was rewritten from scratch (`6e8a3ad`). See [the dev log, Milestone 3](04-development-log.md#milestone-3-crop-and-live-preview).

## Next: M4 (hardening), in this order

1. **Input limits in the UI.** Show the decoder's limits (canvas side, frame count, memory) as clear messages, and make the size/crop/FPS fields explain why a value is clamped or refused.
2. **Corrupt-file messages.** Turn `GifLoadError` texts and decoder warnings (truncated file, junk after frames, bad LZW) into user-facing wording; decide which warnings deserve a dialog vs the status bar.
3. **HiDPI pass at 150 % and 200 %.** Canvas checkerboard and pixel crispness, crop handles and label size, timebar and filmstrip painting, settings-panel layout and scrolling.
4. **Accessibility names audit.** Every control and custom widget has a meaningful `setAccessibleName`/description; tab order through the settings panel and inspector.
5. **Error dialogs.** Consistent titles and texts for open / Generate / Save-frame failures and the startup self-test; consider a "details" section with the exception text.

M4 exit criteria ([02-plan.md §6](02-plan.md#6-milestones)): large and corrupt fixtures don't freeze or crash the app; works at 150 % and 200 % scaling. (Background Generate with progress and cancel, also listed under M4 in the plan, was already done in M2.)

Known issues to pick up during M4 (listed in [03-architecture §9](03-architecture.md#known-ui-limitations-after-m3) and the dev log):
- Space+drag pan is shadowed by the Space play/pause shortcut (middle-drag works).
- The size estimate can be low (0.67×) on long GIFs whose middle is unrepresentative.

## Then: M5 (single `.exe`)

Nuitka `--onefile --enable-plugin=pyside6` build script, icon and version info, the licence bundle (`packaging/licenses/`), and a Windows CI build artifact. Exit criterion: `GifEditor.exe` runs on a clean Windows 11 VM with no Python, from any folder or a USB stick. See [02-plan.md §6](02-plan.md#6-milestones).

## Environment reminders

- Run tests with `scripts/test.sh` (sets `LD_LIBRARY_PATH` for the project-local libEGL in
  `.devlibs/` and `QT_QPA_PLATFORM=offscreen`). Plain `pytest` fails to import PySide6 here.
- `scripts/fetch-devlibs.sh` re-downloads libEGL (SHA-256 pinned, gitignored) if `.devlibs/` is lost.
- To leave out a file that a worker is still writing, use `scripts/test.sh --ignore=<path>`;
  never move or rename a worker's file.
- Delegation workers are NOT durable: closing the PC kills them. Commit early, snapshot unfinished work
  (clearly flagged), and update this note before shutting down.
- Subagents inherit the parent model by default; pin `delegation.model` in `config.yaml` on the host
  to run them on a cheaper model (not settable from inside the container).

## Full design history

See `docs/04-development-log.md` and `docs/02-plan.md` (with its deviations section).
