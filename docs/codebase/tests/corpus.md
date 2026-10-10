# `tests/corpus.py`

> A code-generated corpus of tricky GIFs. It contains a raw GIF89a writer that can express things Pillow cannot write, and an independent reference compositor with browser semantics that defines the "correct" frames.

## Where it sits
- **Layer:** tests (helper module, not a test file)
- **Used by:** `tests/conftest.py` (`build_all`, `Expected`), `tests/core/test_corpus.py`, `tests/core/test_decoder_corpus.py`, `tests/core/test_pipeline.py` (via the `corpus` fixture).
- **Uses:** Pillow only (to build the PNG for `not_a_gif`). It deliberately does **not** import `gif_editor.core.decoder`, so the decoder is checked against an independent implementation.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `FrameSpec(width, height, indices, left=0, top=0, local_palette=None, disposal=1, delay_cs=10, transparent=None, interlace=False, gce=True)` | frozen dataclass | One image block. `indices` is row-major `bytes` of palette indices. `gce=False` omits the Graphic Control Extension. |
| `GifSpec(width, height, frames, global_palette=PAL8, background=0, loop=0, trailer=True)` | frozen dataclass | A whole file. `global_palette=None` means no global table; `loop=None` means no NETSCAPE block; `trailer=False` omits `;`. |
| `Expected(kind, description, canvas_size, frame_count, delays_cs, loop, has_transparency, frames, declared_frame_count)` | frozen dataclass | What a correct, browser-like decoder must report. `kind` ∈ `valid`, `truncated`, `invalid`, `huge`. `.delays_ms` property. |
| `encode_gif(spec) -> (bytes, data_offsets)` | function | Serialise a spec; also return the offset of each frame's image-data sub-blocks, so tests can corrupt them precisely. |
| `lzw_encode(indices, min_code_size)` | function | Minimal always-correct LZW encoder (no compression). |
| `interlace_order(height)` | function | Row order of an interlaced image. |
| `compose(spec, *, frames=None)` | function | Reference compositor → list of RGBA images. |
| `normalize_rgba(img)` | function | RGBA bytes with the RGB of fully transparent pixels zeroed, so tests compare only what is visible. |
| `pattern(w, h, fn)`, `solid(w, h, idx)`, `diag(w, h, offset=0, mod=8)` | functions | Index patterns. Diagonal stripes catch row/column offset bugs. |
| `PAL8` | constant | 8 saturated colours (red, green, blue, yellow, cyan, magenta, white, black). |
| `ENTRIES: dict[str, Entry]` | constant | The 13 corpus entries (below). |
| `VALID_ENTRIES` | constant | The 10 `valid` entry names. |
| `write_entry(name, dir)`, `build_all(dir)` | functions | Write one or all entries; return `(path, Expected)` / `{name: (path, Expected)}`. |

Private helpers used by tests: `_u16`, `_sub_blocks`, `_table_bits`, `_colour_table`.

### The entries
| Name | Kind | What it exercises |
|---|---|---|
| `basic` | valid | 3 full frames, global palette, delays 10/20/30 cs |
| `partial_offsets` | valid | full first frame, then small rects at offsets (disposal 1) |
| `disposal_background` | valid | disposal 2 on an opaque rect and on a rect with a transparent index; background index 3 (which browsers ignore) |
| `disposal_previous` | valid | disposal 3 restoring earlier content |
| `local_palettes` | valid | no global table; local tables of 2, 4 and 16 colours |
| `transparency_changes` | valid | transparent index 7 → 1 → 0 across overlapping partial frames |
| `zero_delays` | valid | delays 0, 1, 0 cs (→ 100 ms effective) |
| `no_loop` | valid | no NETSCAPE block |
| `single_frame` | valid | one frame, no GCE, no loop block |
| `interlaced` | valid | interlaced full frame of height 13 (every pass partial) + an interlaced rect |
| `truncated` | truncated | 3 frames declared, cut 6 bytes into frame 3's LZW data, no trailer; expect 2 frames |
| `not_a_gif` | invalid | PNG bytes in a `.gif` |
| `large_canvas_header` | huge | 20000×20000 logical screen with a single 2×2 frame (< 200 bytes); for limit tests |

## How it works
**Why a hand-written writer:** Pillow's GIF writer cannot produce partial frames at chosen offsets with chosen disposals, local tables only, interlacing, 0 cs delays, a missing loop block, or truncation. Committing binary fixtures is forbidden (AGENTS.md), so the corpus is generated at test time.

**`lzw_encode` trick:** real LZW grows its code width as the dictionary fills, which is fiddly to get right. This encoder emits only *literal* codes at a constant width of `min_code_size + 1`, and a clear code every `2**min_code_size − 2` literals. The decoder's next free code therefore never reaches the width-increase threshold. The output is valid GIF LZW, just uncompressed, which is ideal for an "obviously correct" test writer. `test_lzw_round_trip_through_pillow` verifies it.

**`encode_gif`:**
1. Header `GIF89a` + logical screen; the global table is padded to a power of two (`_colour_table`).
2. An optional NETSCAPE2.0 block.
3. For each frame: optional GCE (packed disposal + transparent flag, delay, transparent index), image descriptor (interlace and local-table flags), optional local table, rows reordered by `interlace_order` if interlaced, min code size `max(2, bits)`, LZW split into ≤ 255-byte sub-blocks.
4. An optional trailer.

**`compose` (reference compositor, browser semantics):**
- A pure-Python list of RGBA tuples, starting fully transparent.
- Each frame paints its non-transparent pixels clipped to the canvas, and a copy of the canvas is emitted.
- Disposal 2 then clears the clipped rect to transparent (ignoring the background colour, as browsers do); disposal 3 restores the pre-frame canvas; others keep it.

It is deliberately slow and simple, the opposite of the decoder's numpy compositor.

## Invariants & gotchas
- No binary files are ever committed; everything is rebuilt per test session in a temp dir.
- `FrameSpec` validates `len(indices) == w*h` and disposal 0..7. `lzw_encode` rejects indices ≥ `2**min_code_size`.
- Indices beyond a short colour table are allowed in specs (the LZW code size may exceed the table). `compose` would index out of range for them, so such tests compute the expected pixels by hand (`test_no_global_palette_and_out_of_table_index`).
- `Expected.has_transparency` for valid specs is "any frame declares a transparency index". That matches the decoder's alpha-based flag for the current entries, but the two definitions differ in general (see decoder page).

## Tests
- `tests/core/test_corpus.py` validates the corpus itself against Pillow, plus writer/compositor unit checks.

## History
- `cc5e164`: added in Wave 1. It is where the Pillow disposal-2 discrepancy was found ([dev log](../../04-development-log.md#wave-1-five-parallel-workers)).
