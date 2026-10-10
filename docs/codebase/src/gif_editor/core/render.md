# `src/gif_editor/core/render.py`

> Per-frame image work: crop, resize with premultiplied alpha, build one shared palette for the animation, and quantize RGBA frames to GIF-ready `"P"` images.

## Where it sits
- **Layer:** core (Pillow + numpy, no Qt)
- **Used by:** `core/pipeline.py` (everything), the tests. The M3 edited preview is expected to use `render_frame` via `pipeline.render_output_frame`.
- **Uses:** `core/models.py` (`CropRect`, `OutputSize`, `Quality`).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `ALPHA_THRESHOLD = 128` | constant | GIF alpha is binary: alpha < 128 → transparent. |
| `TRANSPARENT_RGB = (0, 0, 0)` | constant | Colour stored in the reserved transparent palette slot. |
| `output_dimensions(canvas_w, canvas_h, crop, size)` | function | Final size: `size`, else the crop size, else the canvas (L17-25). |
| `render_frame(img_rgba, crop, size)` | function | Crop then LANCZOS-resize in premultiplied alpha. Never mutates or returns the input object (L28-47). `ValueError` for non-RGBA input or a crop outside the image. |
| `Palette(colors, transparent=False)` | frozen dataclass | One palette for a whole output GIF. `colors` are opaque entries `0..n-1`; if `transparent`, index `n` is reserved for transparency (L56-86). Properties: `transparent_index`, `size`. Method: `flat()`. |
| `PALETTE_SAMPLE_FRAMES = 16`, `PALETTE_SAMPLE_PIXELS = 2**20`, `EXACT_SCAN_PIXELS = 2**23` | constants | Sampling budgets for `build_palette`. |
| `sample_indices(count, max_samples=16)` | function | Up to `max_samples` evenly spaced indices, first and last always included (L94-100). |
| `build_palette(sample_rgba_frames, quality, *, transparent=False)` | function | Shared palette from rendered sample frames (L103-145). |
| `quantize(img_rgba, quality, palette=None, previous=None)` | function | RGBA → `"P"`. Sets `info["transparency"]` iff any pixel is transparent (L171-215). |

## How it works

### Crop and resize (`render_frame`)
1. Validate the crop against the image and crop it.
2. If an output size is set and differs from the current size, resize: `convert("RGBa")` (premultiplied) → `resize(LANCZOS)` → `convert("RGBA")`. *Why premultiplied:* in straight alpha a fully transparent pixel still has an RGB value (usually black). LANCZOS would blend that black into the visible edge pixels and leave dark fringes. Premultiplying makes transparent pixels contribute nothing (`test_premultiplied_resize_no_dark_fringe`).
3. If nothing changed, return a copy, so callers can always mutate the result.

### Shared palette (`build_palette`)
GIFs have at most 256 colours per frame. Before `8e7d34c` every frame got its own palette, which made colours flicker between frames and stopped the encoder from writing frames as small differences (the files were about 10× larger). Now one palette is built for the whole output:
1. Take up to 16 evenly spaced frames (`sample_indices`). The pipeline passes frames that are *already* cropped and resized, so the palette fits what is actually written.
2. Collect the opaque pixels (alpha ≥ 128). If any sampled pixel is transparent, or the caller passes `transparent=True`, reserve one slot for transparency. The opaque budget is then `quality.colors − 1`.
3. **Exact path:** pack the RGB values into `uint32`, then `np.unique`. If the distinct colours fit the budget, use them exactly: no quantization error, which is ideal for flat-colour GIFs. Above 8 Mpx this check runs on a strided subsample, and the exact path is not taken from a subsample.
4. **Median cut path:** randomly subsample at most 1 Mpx (with a fixed seed `0x61F`, so it is deterministic), lay the pixels out as a 1-row RGB image, `quantize(n, MEDIANCUT, dither=NONE)`, and keep only the palette entries actually used.
5. If there are no opaque pixels at all: `Palette(((0,0,0),), reserve)`.

### Quantization (`quantize`)
**Why palette first, then map:** Pillow **ignores the `dither` argument for MEDIANCUT** quantization. So the palette is built first (`_build_palette`) and the image is then mapped onto it with `Image.quantize(palette=…, dither=FLOYDSTEINBERG|NONE)` (`_map_to_palette`), where dithering does work. `_map_to_palette` checks that no index is ≥ the palette length, a defence against Pillow returning a padded palette.

Two modes:
- **Per-frame palette** (`palette=None`, kept for single images and tests):
  - fully opaque → median cut with `quality.colors` entries;
  - fully transparent → a 1-colour palette with index 0 as transparent;
  - mixed → `colors − 1` opaque entries plus the transparent slot.
- **Shared palette** (`_quantize_shared`, what the pipeline uses):
  - every frame is mapped onto `palette.colors`;
  - transparent pixels are set to `palette.transparent_index`;
  - `palette.flat()` is attached, so every frame carries an *identical* palette and identical indices. That is what lets the encoder omit local colour tables and diff by index;
  - a transparent pixel with a palette that reserves no slot is a `ValueError`.

**Transparent pixels and dither error:** before mapping, transparent pixels are filled with an exact palette colour (`colors[0]`). Their colour then injects no Floyd–Steinberg error into neighbouring visible pixels. Afterwards they are overwritten with the transparent index.

**Anti-shimmer (`previous`):** Floyd–Steinberg spreads error to neighbours. If a moving object changes the error pattern, *static* background pixels can flip between two palette colours from frame to frame. That flicker is visible, and it also makes the encoder's difference rectangles bigger. With `previous=(prev_rgba, prev_p)` and dithering on, every pixel whose RGBA is unchanged and opaque in both frames keeps its previous index (`test_previous_keeps_indices_of_unchanged_pixels`, `test_resave_size_and_no_flicker`). Without dithering the mapping is deterministic per colour, so `previous` is not needed and is ignored.

## Invariants & gotchas
- Inputs must be RGBA (`ValueError` otherwise); outputs never alias the inputs.
- With a shared palette the output has exactly `palette.flat()` as its palette and indices `< palette.size`. The transparent index, if any, is always the **last** entry.
- `info["transparency"]` is set **only** when a transparent pixel exists. The encoder treats a frame as transparent iff that key is set.
- After a LANCZOS resize, alpha is continuous. The 128 threshold turns it back into binary, so edges of a semi-transparent sprite can move by up to about a pixel.
- `build_palette` reads at most 16 frames: pass a lazy sequence if you like (`test_build_palette_uses_at_most_16_frames`).
- Determinism: the same input gives the same palette and indices (fixed RNG seed; Pillow's quantizers are deterministic).

## Tests
- `tests/core/test_render.py`: `output_dimensions`; exact crop; out-of-bounds crop; resize sizes; copy semantics; premultiplied fringe; input immutability; opaque quantization at 2/16/256 colours with and without dither; transparency (index exclusivity, the 127/128 boundary, fully transparent frames, GIF round trip); `sample_indices`; `Palette`; exact vs median-cut `build_palette` within budget; the transparency flag; determinism; shared-palette mapping; the anti-shimmer `previous`; the out-of-range index guard.
- **Gaps:** the `EXACT_SCAN_PIXELS` strided path (> 8 Mpx of samples) is not tested; neither is the speed of `build_palette` on large frames.

## History
- `719c05c`: crop → premultiplied LANCZOS → quantize; the "Pillow ignores dither for MEDIANCUT" workaround.
- `8e7d34c`: `Palette`, `build_palette`, `sample_indices`, shared-palette mapping and `previous` (review finding 2). See [dev log](../../../../04-development-log.md#independent-review--fixes).
