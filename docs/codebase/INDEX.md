# Codebase index

Every file in the repo (except `docs/`) with a one-line summary and a link to its page. Pages mirror the repo path with `.md` in place of the file extension. Config files share [config-files.md](config-files.md).

## Application: `src/gif_editor/`
| File | Summary | Page |
|---|---|---|
| `src/gif_editor/__init__.py` | Package docstring and `__version__ = "0.1.0"` | [page](src/gif_editor/__init__.md) |
| `src/gif_editor/__main__.py` | `python -m gif_editor` → `app.main()` | [page](src/gif_editor/__main__.md) |
| `src/gif_editor/app.py` | Creates the `QApplication`; placeholder main window until M2 lands | [page](src/gif_editor/app.md) |
| `src/gif_editor/resources/icons/.gitkeep` | Empty placeholder for app icons | — |

### Core engine: `src/gif_editor/core/` (no Qt)
| File | Summary | Page |
|---|---|---|
| `core/__init__.py` | Package marker ("Pure-Python GIF engine (no Qt)") | [page](src/gif_editor/core/__init__.md) |
| `core/models.py` | Immutable `EditState` + `CropRect`, `OutputSize`, `Quality`; field and source validation | [page](src/gif_editor/core/models.md) |
| `core/decoder.py` | `GifSource`: own block parser, numpy compositor with browser disposal, LRU + keyframe checkpoints, DoS limits | [page](src/gif_editor/core/decoder.md) |
| `core/timeline.py` | `plan_output`: trim → delete → speed → FPS grid → min 20 ms → cs rounding with carry → 65535 cs split | [page](src/gif_editor/core/timeline.md) |
| `core/render.py` | Crop, premultiplied LANCZOS resize, shared palette (`build_palette`), quantize with anti-shimmer | [page](src/gif_editor/core/render.md) |
| `core/encoder.py` | `write_gif`: own GIF container, lossless difference frames, atomic temp+rename, progress/cancel/verify; `read_back`, `estimate_size` | [page](src/gif_editor/core/encoder.md) |
| `core/pipeline.py` | Glue: `plan`, `summarize`, `render_output_frame`, `output_palette`, `iter_output_frames`, `generate`, `export_frame_png` | [page](src/gif_editor/core/pipeline.md) |
| `core/selftest.py` | Round trip through the undocumented Pillow internals; raises `SelfTestError` | [page](src/gif_editor/core/selftest.md) |

### User interface: `src/gif_editor/ui/` (PySide6)
| File | Summary | Page |
|---|---|---|
| `ui/__init__.py` | Package marker | [page](src/gif_editor/ui/__init__.md) |
| `ui/document.py` | `Document`: the hub holding source, `EditState`, undo stack, current frame, selection; all widgets talk to it | [page](src/gif_editor/ui/document.md) |
| `ui/commands.py` | `SetStateCommand`: generic old → new `EditState` undo step with gesture merging | [page](src/gif_editor/ui/commands.md) |
| `ui/workers.py` | `run_async`: run work on `QThreadPool`, callbacks on the GUI thread | [page](src/gif_editor/ui/workers.md) |
| `ui/qt_image.py` | `pil_to_qimage` (thread-safe copy) and `checkerboard_brush` | [page](src/gif_editor/ui/qt_image.md) |
| `ui/settings_panel.py` | Left panel: timing, size, quality, live summary and Generate *(in progress, page written by its owner)* | [page](src/gif_editor/ui/settings_panel.md) |
| `ui/main_window.py` | Main window, menus, open/Generate orchestration *(planned, orchestrator)* | [page](src/gif_editor/ui/main_window.md) |
| `ui/inspector/__init__.py` | Package marker for the right-hand inspector | [page](src/gif_editor/ui/inspector/__init__.md) |
| `ui/inspector/canvas.py` | `FrameCanvas`: zoomable, pannable view of the current frame *(in progress, page written by its owner)* | [page](src/gif_editor/ui/inspector/canvas.md) |
| `ui/inspector/timebar.py` | `TimeBar`: source timeline, playhead, green/red trim handles *(in progress, page written by its owner)* | [page](src/gif_editor/ui/inspector/timebar.md) |
| `ui/inspector/filmstrip.py` | Thumbnail strip of every source frame, selection, deleted state *(in progress, page written by its owner)* | [page](src/gif_editor/ui/inspector/filmstrip.md) |
| `ui/inspector/player.py` | `Player`: timer that steps `Document.current_index` through time *(in progress, page written by its owner)* | [page](src/gif_editor/ui/inspector/player.md) |
| `ui/inspector/transport.py` | Playback controls row: first/prev/play/next/last *(in progress, page written by its owner)* | [page](src/gif_editor/ui/inspector/transport.md) |
| `ui/inspector/inspector.py` | Composes canvas, timebar, filmstrip and transport into the right panel *(planned, orchestrator)* | [page](src/gif_editor/ui/inspector/inspector.md) |

## Tests: `tests/`
| File | Summary | Page |
|---|---|---|
| `tests/__init__.py` | Empty package marker | [page](tests/__init__.md) |
| `tests/conftest.py` | Session fixtures `corpus`, `corpus_dir` (no Qt) | [page](tests/conftest.md) |
| `tests/gifgen.py` | Simple test GIFs via Pillow: `make_gif`, `solid_frames`, `PALETTE` | [page](tests/gifgen.md) |
| `tests/corpus.py` | Raw GIF89a writer, literal-only LZW, browser reference compositor, 13 edge-case entries | [page](tests/corpus.md) |
| `tests/core/__init__.py` | Empty package marker | [page](tests/core/__init__.md) |
| `tests/core/test_models.py` | `EditState` defaults, `with_`, validation, presets (14) | [page](tests/core/test_models.md) |
| `tests/core/test_decoder.py` | `GifSource` metadata, pixels, cache, limits, threads, file release (25) | [page](tests/core/test_decoder.md) |
| `tests/core/test_decoder_corpus.py` | `GifSource` vs reference compositor; edge cases; memory-DoS guards (56) | [page](tests/core/test_decoder_corpus.md) |
| `tests/core/test_corpus.py` | The corpus vs raw Pillow; 2 strict xfails documenting Pillow's disposal-2 bug (51) | [page](tests/core/test_corpus.md) |
| `tests/core/test_timeline.py` | `plan_output` tables and 600 randomized property checks (112) | [page](tests/core/test_timeline.md) |
| `tests/core/test_render.py` | Crop/resize, quantize, transparency, shared palette, anti-shimmer (44) | [page](tests/core/test_render.md) |
| `tests/core/test_encoder.py` | Writer structure, lossless diffs, transparency/disposal, atomicity, cancel, verify (62) | [page](tests/core/test_encoder.md) |
| `tests/core/test_pipeline.py` | End to end: summary == output, cancel, loop, verify, PNG, size and flicker (24) | [page](tests/core/test_pipeline.md) |
| `tests/core/test_selftest.py` | Self-test passes fast and catches broken internals (6) | [page](tests/core/test_selftest.md) |
| `tests/ui/__init__.py` | Empty package marker | [page](tests/ui/__init__.md) |
| `tests/ui/conftest.py` | `gif_path` (8×40×30 GIF) and `doc` (open `Document`) fixtures | [page](tests/ui/conftest.md) |
| `tests/ui/test_document.py` | `Document` apply/undo/merge/delete/index/selection (11) | [page](tests/ui/test_document.md) |
| `tests/ui/test_workers.py` | `run_async` threading, errors, progress (2) | [page](tests/ui/test_workers.md) |
| `tests/ui/test_qt_image.py` | `pil_to_qimage` pixels/ownership, brush (2) | [page](tests/ui/test_qt_image.md) |
| `tests/ui/test_smoke.py` | Qt renders headlessly (1) | [page](tests/ui/test_smoke.md) |
| `tests/ui/test_settings_panel.py` | Settings panel tests *(in progress, page written by its owner)* | [page](tests/ui/test_settings_panel.md) |
| `tests/ui/test_canvas.py` | Frame canvas tests *(in progress, page written by its owner)* | [page](tests/ui/test_canvas.md) |
| `tests/ui/test_timebar.py` | Timebar tests *(in progress, page written by its owner)* | [page](tests/ui/test_timebar.md) |
| `tests/ui/test_filmstrip.py` | Filmstrip tests *(in progress, page written by its owner)* | [page](tests/ui/test_filmstrip.md) |
| `tests/ui/test_player.py` | Player tests *(in progress, page written by its owner)* | [page](tests/ui/test_player.md) |
| `tests/ui/test_transport.py` | Transport tests *(in progress, page written by its owner)* | [page](tests/ui/test_transport.md) |

## Scripts: `scripts/`
| File | Summary | Page |
|---|---|---|
| `scripts/test.sh` | Lint + all tests headlessly in the container (sets `LD_LIBRARY_PATH`, offscreen Qt) | [page](scripts/test.md) |
| `scripts/fetch-devlibs.sh` | Fetch, SHA-256-check and unpack Debian `libegl1` into `.devlibs/` | [page](scripts/fetch-devlibs.md) |

## Config and repo files
| File | Summary | Page |
|---|---|---|
| `pyproject.toml` | Pins, pytest config (`pythonpath`, `-ra`), ruff config | [config-files](config-files.md#pyprojecttoml) |
| `requirements.txt` | Runtime pins | [config-files](config-files.md#requirementstxt) |
| `requirements-dev.txt` | Runtime + pytest, pytest-qt, ruff | [config-files](config-files.md#requirements-devtxt) |
| `.github/workflows/ci.yml` | Windows CI: ruff + pytest with offscreen Qt | [config-files](config-files.md#githubworkflowsciyml) |
| `.gitignore` | Ignores venv, caches, build output, `.devlibs/`, scratch | [config-files](config-files.md#gitignore) |
| `AGENTS.md` | Contributor contract: rules, commands, interfaces, definition of done | [config-files](config-files.md#agentsmd) |
| `README.md` | Short intro and Windows dev commands | [config-files](config-files.md#readmemd) |
| `packaging/licenses/.gitkeep` | Empty placeholder for licence texts (M5) | — |

Not listed: generated/ignored paths (`.venv/`, `.devlibs/`, caches) and `docs/` itself (see [docs/README.md](../README.md)).
