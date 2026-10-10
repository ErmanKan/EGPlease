# `src/gif_editor/ui/qt_image.py`

> Converts Pillow images to `QImage`, and provides the checkerboard brush drawn behind transparent pixels.

## Where it sits
- **Layer:** ui (Qt: `QImage`, `QPixmap`, `QPainter`, `QBrush`)
- **Used by:** `ui/inspector/canvas.py` (`pil_to_qimage` for the frame, `checkerboard_brush` for the background) and `ui/inspector/filmstrip.py` (thumbnails, converted on the worker thread); `tests/ui/test_qt_image.py`.
- **Uses:** nothing in the project.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `pil_to_qimage(img)` | function | Any Pillow mode → an independent `QImage` in `Format_RGBA8888`. Safe on worker threads. |
| `checkerboard_brush(cell=8)` | function | A light-grey/white checkerboard `QBrush` (texture). **GUI thread only** (it uses `QPixmap`). |

## How it works
- `pil_to_qimage` converts the image to RGBA if needed, takes the raw bytes, and wraps them as a `QImage` with stride `w*4`. It then calls **`.copy()`**: `QImage(bytes, ...)` does not own the buffer, so without the copy the image would point at freed memory once the Python `bytes` object is collected. `test_pil_to_qimage_pixels` deletes the source and reads pixels again to prove the copy owns its data.
- `Format_RGBA8888` matches Pillow's byte order exactly (R, G, B, A in memory), so no channel swizzling is needed. Alpha is *not* premultiplied.
- `checkerboard_brush` paints a 2×2-cell tile (white with two `#CCCCCC` cells) onto a `QPixmap` and uses it as a `TexturePattern` brush. Fill the widget background with it before drawing the frame.

## Invariants & gotchas
- QImage may be created on any thread; **QPixmap only on the GUI thread** (Qt rule; AGENTS.md architecture rule). So `pil_to_qimage` is fine in `run_async` work, and `QPixmap.fromImage` belongs in the `on_done` callback.
- The conversion copies the pixel data twice (Pillow → bytes → QImage copy). For a 1280×720 frame that is about 3.7 MB each time. That is fine for scrubbing, but cache the QPixmaps if you repaint often.
- On HiDPI screens, set the device pixel ratio on the texture yourself if cells must stay 8 *logical* pixels. The current brush uses device pixels.

## Tests
- `tests/ui/test_qt_image.py`: exact pixel values and alpha, buffer ownership, P-mode input, a non-null brush texture.
- **Gaps:** brush cell geometry; `LA`/`I;16` modes.

## History
- `0137178`: orchestrator M2 foundation.
