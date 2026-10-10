# RESUME HERE — Milestone 3 (in progress)

**Written:** 2026-10-11, when the PC was shut down mid-milestone.
**Repo:** `/workspace/projects/gif-editor` (host: `F:\Projects\gif-editor`), branch `main`.

## State at shutdown

Committed and green: **531 tests passing + 2 expected failures**, lint clean.
Last commit: `5eeb3f2` (the orphaned `preview.py` snapshot).

| Piece | Status |
|---|---|
| M3 core: output size estimate (`pipeline.estimate_size`, `encoder.write_stream`) | ✅ Done, committed `b9021ca`, verified 1.0–1.18× accurate |
| M3 docs: `CropPanel` specification | ✅ Done, committed `fe4e1a8` (`docs/codebase/src/gif_editor/ui/crop_panel.md`, 127 lines) |
| M3 `ui/inspector/preview.py` | ⚠️ **Written but never tested or reviewed.** Committed as a snapshot only (`5eeb3f2`). It parses and has the specified API (`PreviewService`, signals `frameReady/frameFailed/estimateChanged/estimateReady/geometryChanged`), but a worker was mid-task and never ran its tests or wrote its docs page. **Treat as unverified — re-verify before trusting.** |
| M3 `ui/inspector/crop_item.py` (draggable crop rectangle) | ❌ Never started. The worker was killed at shutdown. |
| M3 `ui/crop_panel.py` | ❌ Not started. Full spec exists — implement from the spec. |
| M3 wiring (canvas → crop item, inspector, settings panel, main window menus/actions) | ❌ Not started. |

**Unverified leftover:** `src/gif_editor/ui/inspector/preview.py` has no `tests/ui/test_preview.py`
and no `docs/codebase/.../preview.md`. Either finish it (write the tests + docs page per its task spec)
or delete it and re-dispatch.

## Next steps, in order

1. **Verify or finish `preview.py`**: run `scripts/test.sh`, write `tests/ui/test_preview.py` and its
   docs page per the spec below. Delete and re-dispatch if it looks unsound.
2. **`crop_item.py`** — was never written. Task spec is in this log and in `AGENTS.md`
   (UI interfaces). Key contract: lives in the scene (scene coords = image pixels), never writes to
   `Document` during a drag, applies on mouse release with `merge_key='crop'` so a drag is one undo step.
3. **`crop_panel.py`** — implement exactly from the committed spec
   `docs/codebase/src/gif_editor/ui/crop_panel.md` (127 lines, complete and precise).
4. **Wire it up** (orchestrator work): `FrameCanvas` hosts `CropItem` and routes keyboard
   nudge/resize; `settings_panel.py` gains the `CropPanel` below the "Output size" group;
   `inspector.py` shows `PreviewService` output; main window gains a "Crop" menu / toggle action
   and shows the estimated size in the summary card.
5. **Then M4** (hardening/polish) and **M5** (Nuitka single-`.exe` build) per `docs/02-plan.md`.

## Environment reminders

- Run tests with `scripts/test.sh` (sets `LD_LIBRARY_PATH` for the project-local libEGL in
  `.devlibs/` and `QT_QPA_PLATFORM=offscreen`). Plain `pytest` fails to import PySide6 here.
- `scripts/fetch-devlibs.sh` re-downloads libEGL (SHA-256 pinned, gitignored) if `.devlibs/` is lost.
- Delegation workers are NOT durable: closing the PC kills them. Commit early, snapshot unfinished work.
- Subagents inherit the parent model by default; pin `delegation.model` in `config.yaml` on the host
  to run them on a cheaper model (not settable from inside the container).

## Full design history

See `docs/04-development-log.md` and `docs/02-plan.md` (with its deviations section).