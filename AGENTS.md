# AGENTS.md — conventions for every contributor (human or agent)

## Hard rules
1. Create/modify/delete files ONLY inside this repo (`/workspace/projects/gif-editor`).
2. Never install anything globally (no apt, sudo, npm -g, pip outside `.venv`, curl|sh, PATH edits).
3. **Workers never install packages.** Need one? List it as `packages_needed` (name, exact version, why) and stop. The orchestrator vets and installs.
4. Only touch the files your task owns. Shared interfaces below are a contract: do not change signatures without the orchestrator.

## Stack (pinned)
Python 3.13 · PySide6-Essentials 6.12.0 · Pillow 12.3.0 · numpy 2.5.3 · pytest 9.1.1 · pytest-qt 4.5.0 · ruff 0.17.0 · Nuitka 4.3 onefile (release build, Windows only).

## Commands (run from repo root, inside the container)
```bash
cd /workspace/projects/gif-editor
.venv/bin/ruff check . && .venv/bin/ruff format --check .   # lint (use `ruff format .` to fix)
scripts/test.sh                                              # lint + ALL tests incl. Qt UI tests (this container)
scripts/test.sh tests/ui -k crop                             # extra args go to pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q      # all tests on Windows/CI
PYTHONPATH=src .venv/bin/python -m gif_editor               # run (needs a display)
```

## Environment note
The dev container lacks `libEGL.so.1`. `scripts/fetch-devlibs.sh` downloads Debian's `libegl1` (SHA-256 pinned, verified against the signed archive index) and unpacks it into the gitignored `.devlibs/`. Nothing is installed system-wide. `scripts/test.sh` sets `LD_LIBRARY_PATH` + `QT_QPA_PLATFORM=offscreen`, so ALWAYS run tests through it in this container (plain `pytest` without it fails to import PySide6). Workers must not fetch or add other system libraries; list them under packages_needed instead.

## Architecture rules
- `src/gif_editor/core/` is pure Python + Pillow/numpy. **No Qt imports in core.**
- `EditState` (core/models.py) is immutable and the single source of truth for edits. The UI changes it only via QUndoCommands.
- `timeline.plan_output()` is the ONLY place that decides which source frames appear in the output and their delays. The preview, summary and encoder all use it.
- Pipeline order: trim → delete → speed → FPS resample → centisecond rounding (min 2 cs) ‖ per frame: crop → resize → quantize.
- Heavy work runs off the GUI thread. Create QPixmaps only on the GUI thread.

## Product decisions (Gate 1)
- **Duration** = length of the trimmed section starting at Start time (source time). `None` = to end.
- **Deleting a frame removes its time** (the GIF gets shorter).
- **Source transparency is preserved** (GIF alpha is binary: alpha < 128 → transparent).
- GIF delays are integer centiseconds. Output delays are ≥ 2 cs (20 ms). The FPS cap is 50. Speed/FPS only ever DROP frames, never duplicate them.
- Source delays of 0 or 10 ms are treated as 100 ms (browser behaviour) → `FrameMeta.effective_delay_ms`.

## Core interfaces (contract)
```python
# core/models.py  (implemented)
CropRect(x, y, w, h); OutputSize(width, height); Quality(colors=256, dither=True)
EditState(trim_start_ms=0, trim_duration_ms=None, deleted=frozenset(), crop=None,
          speed=1.0, fps=None, size=None, quality=Quality()); .with_(**kw); .validate(w, h, n)

# core/decoder.py
Limits(max_canvas_side=8192, max_frames=10_000, cache_budget_bytes=512 MiB, keyframe_interval=32)
FrameMeta(index, delay_ms, effective_delay_ms, disposal)
SourceMeta(path, width, height, frame_count, loop, frames, has_transparency); .total_duration_ms; .delays_ms
GifLoadError(Exception)
GifSource.open(path, limits=Limits()) -> GifSource; .meta; .warnings; .frame(i) -> RGBA Image (a copy)
          .thumbnail(i, max_side=96) -> RGBA Image; .close(); context manager; thread-safe

# core/pipeline.py
plan(meta, state) -> TimelinePlan; summarize(meta, state) -> Summary
output_palette(source, state, timeline) -> Palette        # from <=16 evenly spaced output frames
iter_output_frames(source, state, timeline, palette=None) -> Iterator[(P Image, delay_cs)]
generate(source, state, out_path, *, progress=None, cancel=None) -> GenerateResult
    # keeps source loop (None stays None); verifies frame count + durations before replace
export_frame_png(source, index, out_path, state=None) -> Path

# core/timeline.py
OutputFrame(src_index, delay_cs); TimelinePlan(frames, duration_ms, warnings)
plan_output(delays_ms: Sequence[int], state: EditState) -> TimelinePlan
frame_at_time(delays_ms, t_ms) -> int ; start_times_ms(delays_ms) -> list[int]

# core/render.py
output_dimensions(canvas_w, canvas_h, crop, size) -> (w, h)
render_frame(img_rgba, crop, size) -> RGBA Image          # crop then LANCZOS resize (premultiplied alpha)
Palette(colors: tuple[RGB, ...], transparent=False); .transparent_index (= len(colors) or None); .size; .flat()
sample_indices(count, max_samples=16) -> list[int]         # evenly spaced, first+last kept
build_palette(sample_rgba_frames, quality, *, transparent=False) -> Palette   # shared palette (median cut / exact)
quantize(img_rgba, quality, palette=None, previous=None) -> "P" Image
    # info["transparency"] set iff any transparent pixel; palette given -> mapped onto it (same
    # indices every frame); previous=(prev_rgba, prev_p) keeps indices of unchanged pixels (no shimmer)

# core/encoder.py
Cancelled(Exception)
write_gif(frames: Iterable[tuple[Image, int]], path, *, loop: int | None = 0, total=None, progress=None,
          cancel=None, verify: Callable[[Path], None] | None = None) -> Path
    # lossless diff frames (changed rect, unchanged pixels transparent); 1st palette = global table;
    # loop=None -> no NETSCAPE block (plays once); verify(temp) runs before os.replace
read_back(path) -> tuple[int, list[int]]                   # (frame_count, durations_ms)
estimate_size(sample_frames, total_frames) -> int
```

## UI interfaces (contract, Milestone 2)
```python
# ui/document.py  (implemented): the hub. Widgets talk ONLY to Document, never to each other.
Document(QObject)
  signals: sourceChanged(), stateChanged(EditState), currentIndexChanged(int), selectionChanged(frozenset)
  .source .meta .path .is_open .state .current_index .selection .undo_stack (QUndoStack)
  .set_source(GifSource, path)  .close()
  .apply(new_state, text, merge_key=None)   # ONLY way to change EditState (undoable; ValueError if invalid)
  .delete_frames(idx) .restore_frames(idx) .set_trim(start_ms, duration_ms|None, merge_key="trim")
  .set_current_index(i) .set_selection(idx) .plan() .summary() .frame_start_ms(i)
# ui/commands.py  SetStateCommand(doc, old, new, text, merge_key)  # same merge_key => one undo step
# ui/workers.py   run_async(fn, on_done=, on_error=, on_progress=)  # callbacks on GUI thread
# ui/qt_image.py  pil_to_qimage(img) -> QImage ; checkerboard_brush(cell=8) -> QBrush
```
Widget rules: construct with `(doc: Document, parent=None)`; connect to doc signals; refresh fully on `sourceChanged`; show a disabled/empty state when `doc.is_open` is False; never block the GUI thread for more than ~16 ms (use `run_async`); use `merge_key` for continuous gestures (drags, spinbox scrubbing); give custom widgets `setAccessibleName`; HiDPI-safe painting (cosmetic pens, logical pixels).

## Documentation (required, part of done)
- Every file in `src/`, `tests/` and `scripts/` has a page `docs/codebase/<same path without extension>.md` following `docs/codebase/_TEMPLATE.md`, and one line in `docs/codebase/INDEX.md`.
- When you create or meaningfully change a file, write or update its page in the same commit. Explain *why*, not just *what*. Keep `docs/03-architecture.md` true if you change structure.
- Every module, class and public function has a docstring. Write comments for non-obvious logic.

## Tests
- pytest; generate fixture GIFs in code (`tests/gifgen.py`, `tests/corpus.py`). Never commit binary fixtures.
- Each core module has `tests/core/test_<module>.py`. UI tests use pytest-qt with `QT_QPA_PLATFORM=offscreen`.

## Git
- Conventional commits (`feat:`, `fix:`, `test:`, `chore:`, `docs:`, `refactor:`).
- Commit ONLY your own files: `git add <paths>` then `git commit`. If `index.lock` exists, wait 3 s and retry (other workers commit in parallel). Never `git add -A`, never rewrite history, never push.

## Definition of done
`ruff check` and `ruff format --check` are clean, all tests pass (`scripts/test.sh`), new code has tests, the public interfaces match this file, the per-file doc pages are written or updated, and the work is committed.
