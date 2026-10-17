# AGENTS.md — conventions for every contributor (human or agent)

## Hard rules
1. Create/modify/delete files ONLY inside this repo (`/workspace/projects/gif-editor`).
2. Never install anything globally (no apt, sudo, npm -g, pip outside `.venv`, curl|sh, PATH edits).
3. **Workers never install packages.** Need one? List it as `packages_needed` (name, exact version, why) and stop. The orchestrator vets and installs.
4. Only touch the files your task owns. Shared interfaces below are a contract: do not change signatures without the orchestrator.

## Stack (pinned)
Python 3.13 · PySide6-Essentials 6.12.0 · Pillow 12.3.0 · numpy 2.5.3 · pytest 9.1.1 · pytest-qt 4.5.0 · ruff 0.17.0 · Nuitka 4.3 onefile (release build; build-only pins in `packaging/build-requirements.txt`: nuitka 4.3, ordered-set 4.1.0, zstandard 0.25.0, patchelf 0.19.1.0 on non-Windows).

## Commands (run from repo root, inside the container)
```bash
cd /workspace/projects/gif-editor
.venv/bin/ruff check . && .venv/bin/ruff format --check .   # lint (use `ruff format .` to fix)
scripts/test.sh                                              # lint + ALL tests incl. Qt UI tests (this container)
scripts/test.sh tests/ui -k crop                             # extra args go to pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q      # all tests on Windows/CI
PYTHONPATH=src .venv/bin/python -m gif_editor [file.gif]    # run (needs a display)
.venv/bin/python scripts/check_build_flags.py                 # Nuitka flags valid (run after touching build.py)
.venv/bin/python scripts/make_icon.py --check                 # committed icons match the generator
PATH=$PWD/.venv/bin:$PATH .venv/bin/python scripts/build.py   # Linux onefile (~20 min; proves the recipe, no .exe)
TMPDIR=$HOME/smoke-tmp .venv/bin/python scripts/smoke_build.py out/dist/GifEditor   # needs an exec-able TMPDIR here
```
The Windows `.exe` can only be built on Windows (Nuitka cannot cross-compile): `.github/workflows/build-exe.yml` or `python scripts\build.py` on a Windows PC.

## Environment note
The dev container lacks `libEGL.so.1`. `scripts/fetch-devlibs.sh` downloads Debian's `libegl1`, **verifies its pinned SHA-256** and unpacks it into the gitignored `.devlibs/`. The Debian signature chain was verified once, by hand, when the hash was pinned (`sqv --message` on `InRelease`, then the `Packages` hash, then the package SHA-256; commands in `docs/codebase/scripts/fetch-devlibs.md`); the script does not re-check it. Nothing is installed system-wide. `scripts/test.sh` sets `LD_LIBRARY_PATH` + `QT_QPA_PLATFORM=offscreen`, so ALWAYS run tests through it in this container (plain `pytest` without it fails to import PySide6). Workers must not fetch or add other system libraries; list them under packages_needed instead.

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
Summary(frame_count, duration_ms, width, height, warnings)            # frozen; exact except size
GenerateResult(path, frame_count, duration_ms, width, height, size_bytes, warnings)
plan(meta, state) -> TimelinePlan; summarize(meta, state) -> Summary
render_output_frame(source, src_index, state) -> RGBA Image  # crop + resize; shared with preview
output_palette(source, state, timeline) -> Palette        # from <=16 evenly spaced output frames
iter_output_frames(source, state, timeline, palette=None) -> Iterator[(P Image, delay_cs)]
generate(source, state, out_path, *, progress=None, cancel=None) -> GenerateResult
    # progress(done, total|None); cancel: threading.Event -> encoder.Cancelled
    # ValueError if the plan is empty; keeps source loop (None stays None);
    # verifies frame count + durations before os.replace
export_frame_png(source, index, out_path, state=None) -> Path   # state -> crop+resize; atomic
estimate_size(source, state, timeline, *, samples=ESTIMATE_SAMPLES=5) -> int
    # bytes; 0 for an empty plan. Encodes a CONTIGUOUS middle run of real output frames as ONE
    # stream in memory (write_stream) and extrapolates first + marginal_per_frame * (n - 1).
    # Renders ~n/2 frames: call off the GUI thread (PreviewService does)

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
estimate_size(sample_frames, total_frames) -> int        # M1 helper; NOT used by the app (see pipeline.estimate_size)
write_stream(fp, frames, *, loop=0, total=None, progress=None, cancel=None) -> int
    # write_gif's encoder without the file: into any open binary stream (BytesIO); cancel is a
    # callable that raises; returns the frame count; write_gif delegates to it
```

## UI interfaces (contract, Milestones 2–3)
```python
# ui/document.py: the hub. Widgets talk ONLY to Document, never to each other.
Document(QObject)
  signals: sourceChanged(), stateChanged(EditState), currentIndexChanged(int), selectionChanged(frozenset)
  .source .meta .path .is_open .state .current_index .selection .undo_stack (QUndoStack)
  .set_source(GifSource, path)  .close()     # both reset and emit all four signals
  .apply(new_state, text, merge_key=None)   # ONLY way to change EditState (undoable; ValueError if invalid)
  .delete_frames(idx) .restore_frames(idx) .set_trim(start_ms, duration_ms|None, *, merge_key="trim")
      # "trim" default is for spinbox scrubbing; drags pass their own key, menus/actions pass None
  .set_current_index(i) .set_selection(idx) .plan() .summary() .frame_start_ms(i)
# ui/commands.py  SetStateCommand(doc, old, new, text, merge_key)  # same merge_key => one undo step
# ui/workers.py   run_async(fn, *, on_done=None, on_error=None, on_progress=None, pool=None)
#     # callbacks on the GUI thread; with on_progress, fn is called as fn(progress); call from GUI thread
# ui/qt_image.py  pil_to_qimage(img) -> QImage ; checkerboard_brush(cell=8) -> QBrush

# Widgets (M2). Constructor, key public API, outward signals.
SettingsPanel(doc, parent=None, *, preview=None)   # ui/settings_panel.py; preview: PreviewService -> Size line
  signal generateRequested()                  # Generate button (enabled only if output has frames)
  .crop_panel (CropPanel; its errorOccurred is shown in the summary card)
  .generate_button, .start_spin, .speed_spin, ... (public children, for tests only)
  format_bytes(n) -> str                      # module function: '850 B', '12.4 KB', '3.21 MB' (1 KB = 1024 B)
FrameCanvas(doc, parent=None)                 # ui/inspector/canvas.py (QGraphicsView, read-only)
  signal zoomChanged(float)
  .zoom .fit_mode .zoom_in() .zoom_out() .zoom_actual() .zoom_fit() .set_zoom(f)
  .image_rect() .map_to_image(view_pos)       # scene coords == image pixels (OUTPUT pixels in geometry preview)
  .image_item .set_preview(preview) .geometry_preview   # shows PreviewService frames while geometry is on;
      # never requests frames itself (the service follows currentIndexChanged)
TimeBar(doc, parent=None)                     # ui/inspector/timebar.py
  signal scrubbed(int)                        # while dragging the playhead
  .x_for_time(ms) .time_for_x(x) .handle_at(pos) -> "in"|"out"|None
Filmstrip(doc, parent=None)                   # ui/inspector/filmstrip.py (QListView)
  signal errorOccurred(str)                   # refused edit; the window shows it
  .selected_rows() .delete_selected() .restore_selected()
  .set_trim_start_at(row) .set_trim_end_at(row) .build_context_menu(row=None) .frame_model
Player(doc, parent=None, *, clock=None, time_scale=1.0)   # ui/inspector/player.py (QObject)
  signals playingChanged(bool), previewEditsChanged(bool)
  .is_playing .preview_edits .set_preview_edits(b) .sequence()
  .play() .pause() .toggle() .stop() .go_first() .go_last() .step(n)   # step wraps
TransportBar(doc, player, parent=None)        # ui/inspector/transport.py
  signal saveFrameRequested()
  .first_button .prev_button .play_button .next_button .last_button .preview_check .info_label
Inspector(doc, player, parent=None)           # ui/inspector/inspector.py: .canvas .transport .timebar .filmstrip

# Dark-mode contrast (ui/theme.py)
install(app)                                  # app.py, after setStyle("Fusion"): tuned palette now and on colorSchemeChanged
apply(app) tuned_palette(base) -> QPalette   # reset to the system palette, then lift Button / disabled ButtonText if dark
media_icon(kind, palette) -> QIcon            # kind in MEDIA_KINDS; drawn in ButtonText (+ disabled mode)
mark_primary(button)                          # accent style sheet, text contrast >= PRIMARY_MIN_CONTRAST, follows the palette
primary_colors(palette) primary_style_sheet(palette) contrast_ratio(a, b) relative_luminance(c) mix(a, b, t) is_dark(p)

# Milestone 3
CropPanel(doc, parent=None)                   # ui/crop_panel.py (inside SettingsPanel)
  signal errorOccurred(str)                   # a crop edit was rejected (ValueError message)
  .last_error .crop_group (checkable: unticked = no crop) .aspect_combo .x_spin .y_spin .w_spin .h_spin
  .full_button .center_button .reset_button .status_label   # public children, for tests only; no public methods
  ASPECTS, TIMES                              # module constants
CropItem(doc, parent=None)                    # ui/inspector/crop_item.py (QGraphicsObject); the main window adds it
                                              # to canvas.scene() at (0, 0): item coords == source image pixels
  signals previewChanged(QRectF)              # live rect while dragging (no Document write until release)
          cropActiveChanged(bool)             # doc.state.crop switched between None and set
  .crop_active .tool_enabled .dragging .crop_rect() -> QRect .image_size() -> (w, h)
  .set_tool_enabled(b)                        # off = hidden, ignores mouse AND nudge/resize/activate/reset
  .handle_at(scene_pos) -> 'tl'|'t'|'tr'|'r'|'br'|'b'|'bl'|'l'|'move'|None
  .nudge(dx, dy) .resize(dw, dh) .activate() .reset()   # one undo step each (merge_key=None)
PreviewService(doc, parent=None, *, cache_size=32, debounce_ms=250)   # ui/inspector/preview.py (QObject)
  signals frameReady(int, QImage), frameFailed(int, str), estimateChanged(), estimateReady(),
          geometryChanged(bool)
  .geometry_enabled (property, settable) .set_geometry_enabled(b)   # crop+resize preview on/off
  .render_preview_frame(i) -> QImage          # synchronous; .request_frame(i) -> async frameReady
  .estimated_bytes -> int|None .estimate_pending -> bool .refresh_estimate() .dispose()
      # pool work gets the geometry captured at request time; stale results dropped by generation

MainWindow(doc=None, parent=None)             # ui/main_window.py: owns Document, Player, PreviewService, CropItem
  .open_file(path) .generate_to(path) .cancel_generate() .save_frame_to(path, with_edits=False)
  .trim_in_here() .trim_out_here() .reset_trim() .is_busy .last_error .last_result .last_dialog
  .preview .crop_item .settings .inspector
  .act_* (QActions; shortcuts are window-wide): act_preview (P: timing AND geometry), act_crop_tool (C),
      act_crop_reset, act_crop_nudge[4] (Ctrl+arrows), act_crop_resize[4] (Ctrl+Shift+arrows)
```

Milestone 4 and 5 additions:
```text
# Milestone 4
messages.py                                   # ui/messages.py: core exceptions -> plain-language dialogs (no Qt)
  Explanation(title, headline, body, details)  # .text == headline + "\n" + body (for last_error/status bar)
  explain_load_error(exc, path) -> Explanation       # dispatches on GifLoadError.kind; technical text in .details
  explain_load_warnings(warnings, path, frames) -> Explanation
  explain_generate_error(exc, path, title="Generate failed") -> Explanation   # errno/winerror/MemoryError/fallback
MainWindow.show_explanation(expl, icon=QMessageBox.Icon.Warning) -> QMessageBox
                                              # non-blocking; keeps last_error (text) and last_dialog; details behind "Show Details..."
MainWindow._fit_to_screen()                   # PREFERRED_SIZE (1300x820) capped to 90 % of the screen, centred
FrameCanvas.spaceTapped                       # signal: Space pressed and released with no drag (tap = play/pause)
FrameCanvas.set_preview(preview)              # also enables async source frames: source frames costing more
                                              # than SYNC_DECODE_PIXELS (4M frames x pixels) render in the background
GifSource.frames_to_decode(i) -> int          # compositing cost of frame(i); GifSource.BUSY if another thread
                                              # holds the decoder (never blocks) -> caller must go async
GifLoadError.kind / .info                     # NOT_FOUND, IS_DIRECTORY, UNREADABLE, EMPTY, NOT_GIF, TOO_LARGE,
                                              # TOO_MANY_FRAMES, MALFORMED; .info carries width/height/max_side/max_frames
workers.run_async(...)                        # unchanged API; jobs now run as plain callables (never subclass
                                              # QRunnable in Python in this project: cross-thread wrapper/override
                                              # handling caused one crash and one GC deadlock in ~20 suite runs)

# Milestone 5 (packaging)
scripts/build.py
  version() -> str                            # __version__ read as text from src/gif_editor/__init__.py
  build_command(ver, *, windows=None) -> list[str]   # the Nuitka command; windows=True/False builds the other
                                              # platform's command (for check_build_flags on Linux)
  main() -> int                               # runs Nuitka with PYTHONPATH=src -> out/dist/GifEditor(.exe)
scripts/check_build_flags.py                  # exit 0/1; known_options(), flag_name(arg), check(name, *, windows, known)
                                              # validates against nuitka.options.OptionParsing.parser
scripts/make_icon.py [--check]                # draw() -> icons/; --check compares decoded PIXELS (exit 0/1)
scripts/smoke_build.py [binary]               # 3 runs of a built binary; pass/fail by exit codes + written file only
gif_editor.resources                          # no Qt
  resource_path(*parts) -> Path               # package dir first, then $NUITKA_ONEFILE_DIR/gif_editor/resources;
                                              # never raises (returns the source-layout path if missing)
  icon_path() -> Path | None                  # icon.ico on Windows, icon-256.png elsewhere; None if not bundled
gif_editor.headless                           # no Qt
  parse_spec(spec, state) -> (EditState, Path)   # "k=v,k=v"; lists use colons (delete=0:3:5); trim whole=ms,
                                              # decimal=s; keys trim duration delete crop speed fps size colors dither out
  run_edit_spec(source_path, spec) -> int     # prints "RESULT frames=.. size=WxH bytes=.. ms=.. path=.." or "ERROR ..."; 0/1
app.main(argv)                                # --edit-spec IN SPEC -> run_edit_spec (exit 0/1, 2 = missing args), NO Qt;
                                              # --smoke-gui [FILE] -> _arm_smoke_exit: 50 ms poll, 30 s timeout,
                                              # prints "GUI OK ..."/"GUI FAIL ...", exits 0/1; file = first non-"--" arg;
                                              # window icon from resources.icon_path()
```

Packaging rules:
- After touching `scripts/build.py`, run `scripts/check_build_flags.py` (seconds) before any build (20 minutes). Keep (and extend) the comments in `build_command` that say why each flag is there: most of them record a build that failed without it.
- No Qt import (direct or via a module-level import in `app.py`, `headless.py`, `resources/`, `core/`) may run before the `--edit-spec` branch in `app.main`: the headless path must work without a display or a Qt platform plugin.
- The icon files are generated: change `scripts/make_icon.py`, rerun it, commit both; CI runs `--check`.
- Never run two builds at once, and never delete `out/dist/` while a build runs.

Temporary `[DIAG]` switches (crash investigation, remove together once the Windows smoke crash is understood): `GIF_EDITOR_DIAG_QT_ARGV=program` in `app.main`, `GIF_EDITOR_DIAG_STD_ICONS=1` in `TransportBar._update_icons`, `tests/ui/test_diag_switches.py`, and their variants in `scripts/smoke_build.diag_variants`. Find them all with `grep -rn "\[DIAG\]\|GIF_EDITOR_DIAG"`.

Docker rules (`Dockerfile`, `.github/workflows/docker.yml`):
- `runtime` stays the **last** stage: a plain `docker build` builds the last stage (`tests/core/test_dockerfile.py` checks).
- The base image is pinned by tag **and** digest; update both together.
- The apt package list is measured (`ldd` on Qt's libraries and the xcb/vnc/offscreen plugins). Re-measure when PySide6 changes; a missing library shows up as a platform plugin that fails to load.
- Qt's VNC server has no password: every documented `-p` for port 5900 binds `127.0.0.1` (the test checks the README).
- Commands in the README's Docker section and in `docker.yml` must match; `docker` is not available in the dev container, so the workflow is the only place the image is built.

Merge-key rule: `SetStateCommand` merges ANY consecutive commands with the same key, so keys are per gesture. Spinbox scrubbing uses a fixed key per setting (`"trim"`, `"speed"`, `"fps"`, `"size"`, `"quality"`, `"crop"`); each drag uses a fresh key per press (`"trim-drag-N"`, `"crop-drag-N"`) so a drag never merges with the next drag or with a following spinbox edit; discrete actions (buttons, menu items, nudges, toggles) pass `None`. Never reuse a spinbox key for a drag.

Widget rules: construct with `(doc: Document, parent=None)`; connect to doc signals; refresh fully on `sourceChanged`; show a disabled/empty state when `doc.is_open` is False; never block the GUI thread for more than ~16 ms (use `run_async`); use `merge_key` for continuous gestures (drags, spinbox scrubbing); give custom widgets `setAccessibleName`; HiDPI-safe painting (cosmetic pens, logical pixels); colours from the palette, never hard-coded, and anything derived from it (icons, style sheets) rebuilt on `QEvent.PaletteChange` (not `ApplicationPaletteChange`, which only top-level windows get, before their palette updates); don't use `QStyle.standardIcon` media icons (invisible in dark mode, use `theme.media_icon`); only `ui/theme.py` sets the app palette.

## Documentation (required, part of done)
- Every file in `src/`, `tests/` and `scripts/` has a page `docs/codebase/<same path without extension>.md` following `docs/codebase/_TEMPLATE.md`, and one line in `docs/codebase/INDEX.md`.
- When you create or meaningfully change a file, write or update its page in the same commit. Explain *why*, not just *what*. Keep `docs/03-architecture.md` true if you change structure.
- Every module, class and public function has a docstring. Write comments for non-obvious logic.

## Tests
- pytest; generate fixture GIFs in code (`tests/gifgen.py`, `tests/corpus.py`). Never commit binary fixtures.
- Each core module has `tests/core/test_<module>.py`. UI tests use pytest-qt with `QT_QPA_PLATFORM=offscreen`.
- Temp files stay inside the project: `scripts/test.sh` passes `--basetemp=out/pytest-tmp/run-<pid>` (one dir per run; dirs of exited runs are deleted) and `--capture=sys` (the default fd capture uses deleted-while-open temp files, which the F: drive mount rejects, so `TMPDIR` must not point into the project). Never write to `/tmp`; use `out/`.
- `tests/ui/conftest.py` has an autouse `_drain_workers` fixture (depends on `qtbot`, so it tears down before widgets close): it waits for `QThreadPool` and processes events, so no background task outlives its test. Do not remove it; never leave a worker running across tests.

## Git
- Conventional commits (`feat:`, `fix:`, `test:`, `chore:`, `docs:`, `refactor:`).
- Commit ONLY your own files: `git add <paths>` then `git commit`. If `index.lock` exists, wait 3 s and retry (other workers commit in parallel). Never `git add -A`, never rewrite history, never push.

## Definition of done
`ruff check` and `ruff format --check` are clean, all tests pass (`scripts/test.sh`), new code has tests, the public interfaces match this file, the per-file doc pages are written or updated, and the work is committed.
