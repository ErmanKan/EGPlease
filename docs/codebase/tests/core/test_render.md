# `tests/core/test_render.py`

> Tests for `core/render.py`: output size, crop/resize, per-frame and shared-palette quantization, transparency, anti-shimmer.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/render.py`, `core/models.py`.

## Public API
| Group | Tests | Verifies |
|---|---|---|
| `output_dimensions` | `test_output_dimensions_canvas`, `_crop`, `_size_wins` | Precedence: size > crop > canvas. |
| `render_frame` | `test_crop_exact_pixels`, `test_crop_out_of_bounds_raises`, `test_resize_dimensions`, `test_same_size_returns_copy_equal`, `test_premultiplied_resize_no_dark_fringe`, `test_non_rgba_raises`, `test_input_not_mutated` | Exact crop pixels; bounds checking; sizes; copy semantics; **no dark fringe** when downscaling or upscaling half-transparent red next to transparent black; input never mutated. |
| Opaque quantize | `test_quantize_opaque` (×3), `test_quantize_dither_changes_result`, `test_quantize_deterministic`, `test_quantize_colors_reasonable` | ≤ n colours, no transparency key, dithering has an effect (proves the MEDIANCUT workaround works), determinism, exact colours when they fit. |
| Transparency | `test_quantize_transparency` (×8), `test_alpha_boundary_127_128`, `test_no_transparency_key_when_alpha_128`, `test_fully_transparent_frame`, `test_gif_round_trip_transparency` | The transparent index is used by exactly the alpha < 128 pixels; boundary 127 vs 128; no key when nothing is transparent; an all-transparent frame; survives a GIF save/load. |
| Shared palette | `test_sample_indices`, `test_palette_dataclass`, `test_build_palette_exact_for_few_colours`, `test_build_palette_respects_colour_budget` (×4), `test_build_palette_transparency_flag_and_detection`, `test_build_palette_deterministic_and_validates`, `test_build_palette_uses_at_most_16_frames`, `test_quantize_onto_shared_palette` (×2), `test_quantize_shared_exact_colours_and_dither_flag`, `test_quantize_shared_opaque_palette_rejects_transparent_frame` | Sampling, `Palette` rules (no empty palette, ≤ 256 entries including the transparent slot), exact vs median cut, budget including the reserved slot, determinism, at most 16 frames read (spy list), identical palette on every frame, transparent mapping. |
| Anti-shimmer | `test_previous_keeps_indices_of_unchanged_pixels` | With `previous`, unchanged pixels keep their old indices, changed pixels equal a fresh mapping, and the test proves that Floyd–Steinberg *alone* would have changed them. |
| Defence | `test_map_to_palette_raises_on_out_of_range` | A Pillow result with an index beyond the palette → `RuntimeError`. |

## How it works
`_gradient` builds a smooth RGB gradient, which is a worst case for quantization. `_moving` builds frames with a moving yellow block and an optional transparent top band.

## Invariants & gotchas
- 44 cases.

## Tests
- **Gaps:** the `EXACT_SCAN_PIXELS` strided path; `PALETTE_SAMPLE_PIXELS` subsampling on > 1 Mpx inputs; colour accuracy (only counts and indices are checked, not error metrics).

## History
- `719c05c`, extended in `8e7d34c`.
