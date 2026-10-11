# `scripts/stress_probe.py`

> A manual M4 probe (not a test): opens big and corrupt GIFs through the real `MainWindow` and measures how long the GUI thread is blocked during open, backward scrubbing, playback, preview and Generate.

## Where it sits
- **Layer:** tooling (Python + Qt; run by hand, not by pytest)
- **Used by:** contributors checking responsiveness after changes to decoding, the canvas, the preview service or the workers.
- **Uses:** `ui/main_window.py` (`MainWindow`), `tests/corpus.py` (`build_all`), Pillow + numpy (to make big GIFs), `QElapsedTimer`/`QTimer`.

## Public API
Run from the repo root (inside the container):
```bash
LD_LIBRARY_PATH=$PWD/.devlibs/root/usr/lib/x86_64-linux-gnu QT_QPA_PLATFORM=offscreen \
  PYTHONPATH=src:tests .venv/bin/python scripts/stress_probe.py
PROBE_ONLY=huge  …same command…     # run only the cases whose label contains "huge"
```
| Environment | Effect |
|---|---|
| `PROBE_ONLY=<substring>` | Run only cases whose label contains the substring (e.g. `huge`, `corpus:truncated`). |

Output per case: file size, then one line per phase: `worst stall <ms>   stalls>100ms: <count>`, plus whether the file opened, `last_error` and the status-bar message.

## How it works
- **`StallMeter`**: a `QTimer` firing every 10 ms on the GUI thread. Each tick records the time since the previous tick (`QElapsedTimer.restart()`). If the GUI thread is busy for 300 ms, the next tick comes ~300 ms late, so the largest gap is the **worst stall**: how long the window would have looked frozen. Gaps over 100 ms are counted (100 ms is roughly where users notice lag).
- **Cases**:
  - `big 1280x720x150`: 150 frames of 720p random-colour noise with a moving inverted band (64 colours, 40 ms), made with Pillow (`make_big`);
  - `huge 1920x1080x200 (> cache)`: 200 frames of 1080p, **larger than the decoder's 512 MiB frame cache** (1920 × 1080 × 4 bytes × 200 ≈ 1.6 GB), so frames must be re-composited from checkpoints when scrubbing;
  - five corpus files: `truncated`, `not_a_gif`, `large_canvas_header`, `zero_delays`, `interlaced` (to see the plain error/warning messages in a real window).
- **Phases per case** (only if the file opened): `open` (until `not w.is_busy`, max 60 s), `scrub backwards` (about 40 `set_current_index` steps from the last frame to the first, `processEvents` after each), `play 2 s`, `preview edits on/off` (1.5 s), `generate` (to `out/stress/out.gif`, max 120 s). After each case it waits for the thread pool.
- **Where files go:** everything is written to `out/stress/` (inside the project, gitignored): the two big GIFs, the corpus, the generated output.
- The window is created with `MainWindow()` and then `resize(1300, 820)`, on the default offscreen screen.

## Results (end of M4)
| Case / phase | Before the fix (`5c40830`) | After |
|---|---|---|
| 1280×720×150: open | 0.69 s, worst stall 51 ms | same |
| 1920×1080×200: open | 1.9 s | same |
| 1920×1080×200: scrub backwards | worst stall **384 ms**, 10 stalls > 100 ms | worst stall **28 ms**, none > 100 ms |
| corrupt corpus files | — | the plain-language messages from `ui/messages.py` |

*Why scrubbing stalled:* the canvas decoded the source frame on the GUI thread. For a GIF bigger than the cache, stepping backwards means re-compositing from the nearest checkpoint, up to ~30 full 1080p frames. *The fix:* `GifSource.frames_to_decode(i)` tells the canvas the cost up front; above `SYNC_DECODE_PIXELS` (4,000,000 frames × pixels, about 25 ms) the canvas asks `PreviewService.request_frame` for the plain frame in the background and keeps the old frame up meanwhile. The first version still stalled **643 ms**: `frames_to_decode` waited on the decoder lock held by the background render. Making it non-blocking (it returns `GifSource.BUSY` when the lock is taken) fixed that. Details: [canvas page](../src/gif_editor/ui/inspector/canvas.md#async-source-frames-m4), [decoder page](../src/gif_editor/core/decoder.md#frames_to_decode-and-busy).

## Invariants & gotchas
- Not collected by pytest (it lives in `scripts/`, and it takes minutes). Numbers depend on the machine; compare before/after on the same machine.
- `play 2 s` uses real time, so its stalls include normal frame decoding during playback.
- The 1080p case needs several GB of RAM (Pillow builds the frames in memory before saving).
- Writes only inside `out/stress/`. Never point it at `/tmp`.

## Tests
- n/a (a measurement tool). The behaviour it measured is covered by `tests/ui/test_canvas.py::test_expensive_source_frame_renders_off_thread` and `tests/core/test_decoder.py::test_frames_to_decode_*`.

## History
- `d3f0297` (M4): added.
- `c4b9329` (M4): work folder moved from the container's `/tmp` into `out/stress/`.
- `5c40830` (M4): `PROBE_ONLY` filter; big GIFs quantized with `FASTOCTREE` (much faster to build than the default median cut); used to measure the async source-frame fix ([dev log, Milestone 4](../../04-development-log.md#milestone-4-hardening)).
