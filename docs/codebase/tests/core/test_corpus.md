# `tests/core/test_corpus.py`

> Validates the generated corpus itself (raw writer + reference compositor) against raw Pillow, and pins with strict xfails the exact places where Pillow differs from browsers.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `tests/corpus.py`, the `corpus`/`corpus_dir` fixtures, Pillow. It does **not** use our decoder.

## Public API
| Test | Verifies |
|---|---|
| `test_all_entries_written` | All 13 entries were written to `corpus_dir`, non-empty, each with a description. |
| `test_valid_entry_metadata` (×10) | Pillow reads the same size, frame count, loop and per-frame durations as `Expected`. |
| `test_valid_entry_pixels` (×28, one per frame) | Pillow's composited RGBA (with `LOADING_STRATEGY = RGB_ALWAYS`) equals `compose()`, **except** the two xfails below. |
| `test_truncated_decodes_two_frames_then_raises` | Pillow decodes 2 frames, then raises `OSError("...truncated...")` on the third. |
| `test_not_a_gif` | Pillow does not identify the PNG as a GIF. |
| `test_large_canvas_header` | The file is < 200 bytes, declares 20000×20000, and Pillow raises `DecompressionBombError` on open. |
| `test_interlace_order` | Row order for h=13 and permutation property for h=1..39. |
| `test_lzw_round_trip_through_pillow` (×6) | Our literal-only LZW output decodes in Pillow for 2..256 colours on a 61×37 frame (many clear codes and sub-blocks). |
| `test_lzw_rejects_out_of_range_index` | Index ≥ 2**min_code_size → `ValueError`. |
| `test_reference_compositor_semantics` | A hand-checked 2×1 sequence: disposal 1 keeps, 3 restores, 2 clears to transparent, a fully transparent frame shows the canvas underneath. |

### The xfails
`PILLOW_DISCREPANCIES` marks `disposal_background` frames **2 and 3** as `xfail(strict=True)`. The first frame has no transparency index, so Pillow keeps the canvas in RGB mode (no alpha). Disposal 2 then fills the rect of the opaque frame with the **background colour** (index 3, yellow), and the rect of the frame that has transparent index 6 with `palette[6]` (white). Browsers clear both to transparent.

`strict=True` means: if a future Pillow fixes this, the test *passes unexpectedly* and pytest reports a failure, so we notice and can reconsider our custom decoder. `tests/core/test_decoder_corpus.py` asserts the browser behaviour for our decoder on the same frames, without any xfail.

## How it works
- `_frame_params` builds one parametrized case per (entry, frame) and attaches the xfail marks.
- The `rgb_always` fixture monkeypatches `GifImagePlugin.LOADING_STRATEGY` so that Pillow returns a full-colour image for every frame, comparable to our RGBA.
- `_diff_summary` prints the first 5 differing pixels, which makes failures readable.

## Invariants & gotchas
- 51 cases, 2 of which are expected failures. The `-ra` option in `pyproject.toml` prints the xfail reasons in every run.
- This file documents **raw Pillow**. A failure here (other than an XPASS) means either the corpus writer/compositor is wrong, or Pillow changed.

## Tests
- **Gaps:** the corpus has no comment or application extensions other than NETSCAPE, and no zero-size frames.

## History
- `cc5e164`: added with the corpus; the xfails record the finding that motivated the decoder rewrite (`212b23f`).
