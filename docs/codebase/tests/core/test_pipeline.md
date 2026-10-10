# `tests/core/test_pipeline.py`

> End-to-end tests: source + `EditState` → `generate` → read back, plus size, flicker and lossless checks.

## Where it sits
- **Layer:** tests (core, no Qt)
- **Used by:** pytest.
- **Uses:** `core/pipeline.py`, `core/decoder.py`, `core/encoder.py` (`Cancelled`, `read_back`), `core/models.py`, `tests/gifgen.py`, the `corpus` fixture.

## Public API
| Group | Tests | Verifies |
|---|---|---|
| Round trips | `test_identity_roundtrip`, `test_combined_edits_match_summary`, `test_fps_resample` | No edits → 8 frames × 100 ms, same colours, correct `GenerateResult`. All edits at once: the frame count, durations and size equal `summarize`/`plan`, deleted frames are absent, colours follow `src_index`. fps 5 on 100 ms frames → 4 × 200 ms. |
| Errors | `test_invalid_state_rejected`, `test_cancel_leaves_no_output` | An oversized crop raises `ValueError`; all frames deleted → `ValueError` and no file; cancel at frame 3 → `Cancelled` and only the input file remains. |
| Semantics | `test_transparency_preserved`, `test_loop_preserved_and_defaulted` | Source transparency survives; the loop value 3 / 0 / `None` is kept (no NETSCAPE block for `None`). |
| Verification | `test_verify_failure_leaves_destination_untouched`, `test_verify_runs_on_temp_before_replace` | A patched `read_back` mismatch raises "verification" and the old destination survives; `verify` reads the temp file before the destination exists. |
| PNG | `test_export_frame_png` | Raw frame 40×30 with the right colour; edited (crop 8×6 → 4×3); no temp files left. |
| Corpus | `test_corpus_generates_valid_gif` (×10) | Every valid corpus GIF re-generates with a count and duration equal to its summary. |
| Size & flicker | `test_resave_size_and_no_flicker` (×2), `test_output_is_exactly_the_quantized_frames`, `test_transparent_moving_sprite_lossless` | On a 160×120×24 gradient with a moving rect: output ≤ 1.5× Pillow's optimized re-save and **zero** flicker in unchanged areas, with and without dither. The decoded output equals exactly the frames `iter_output_frames` produced. A transparent sprite round-trips. |

## How it works
The `src` fixture is an 8-frame 40×30 solid-colour GIF. `gradient_gif` (module scope) builds a gradient animation, decodes it, and records Pillow's own optimized re-save size as the baseline. The 1.5× bound guards against regressions to the old "palette per frame, full frames" behaviour, which was about 10× larger (dev log review finding 2).

## Invariants & gotchas
- 24 cases. `VALID` duplicates `corpus.VALID_ENTRIES` by hand; keep them in sync if entries are added.

## Tests
- **Gaps:** `progress` sequence from `generate`; `render_output_frame` directly; `output_palette` on an empty plan; PNG export with an invalid state.

## History
- `f9add66`, extended in `e8bcb7e`, `8e7d34c`, `f7056d9`.
