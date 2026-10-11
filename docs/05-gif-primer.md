# 05 — GIF primer

The GIF format concepts this codebase relies on. Each section ends with **In our code**, pointing to the file and function that handle the concept. Written for a Python developer who has never looked inside a GIF.

Throughout: "browser" means current Chrome, Firefox and Safari, which agree on everything described here. "Spec" means the GIF89a specification (1990).

---

## File structure

A GIF is a sequence of **blocks**. All integers are little-endian `uint16` unless noted.

```
"GIF89a"                         6 bytes  signature + version ("GIF87a" has no extensions)
Logical Screen Descriptor        7 bytes  canvas width, height, packed flags, background index, aspect
[Global Colour Table]            3 × 2^(n+1) bytes, if flag set
repeat:
  0x21 0xFF "NETSCAPE2.0" ...    Application Extension: loop count (usually right after the header)
  0x21 0xF9 ...                  Graphic Control Extension (GCE): delay, disposal, transparency
  0x2C ...                       Image Descriptor: left, top, width, height, packed flags
  [Local Colour Table]
  LZW min code size (1 byte)
  image data sub-blocks          [len][len bytes] ... [0]
0x3B                             Trailer
```

| Block | Bytes | What matters to us |
|---|---|---|
| **Header** | `GIF87a` or `GIF89a` | Anything else → not a GIF. |
| **Logical Screen Descriptor** | width, height, packed, bg index, aspect | The *canvas* size. Packed bit 7 = a global colour table follows; bits 0-2 = `n`, table holds `2^(n+1)` colours; bits 4-6 = colour resolution. The background index is ignored by browsers (see disposal). |
| **Global Colour Table** | RGB triples | Default palette for frames without a local table. |
| **Extension** `0x21 label` | sub-blocks | `0xF9` GCE, `0xFF` application, `0xFE` comment, `0x01` plain text. Each is a chain of length-prefixed **sub-blocks** (≤ 255 bytes each) ended by a `0` byte, so unknown extensions can be skipped without understanding them. |
| **GCE** `0x21 0xF9 0x04` | packed, delay, transparent index, `0` | Applies to the **next** image only. Packed bits 2-4 = disposal method, bit 0 = transparency flag. Delay in **centiseconds**. |
| **Image Descriptor** `0x2C` | left, top, width, height, packed | A frame is a **rectangle** that may be smaller than the canvas and placed at an offset. It may even be bigger than the canvas, or entirely off it. Packed bit 7 = local table, bit 6 = interlaced, bits 0-2 = local table size. |
| **Image data** | min code size + sub-blocks | LZW-compressed palette indices (below). |
| **Trailer** `0x3B` | | End of file. Missing in many truncated files. |

There is **no frame count** in the header and no index of frames. To know anything about frame 50 you must walk every block before it. Sub-block length bytes make that walk cheap, because image data can be skipped without decompressing it.

**In our code:**
- Parsing: `decoder._parse` and `_skip_sub_blocks` ([page](codebase/src/gif_editor/core/decoder.md#step-1-read-and-parse-open--_parse-l240-370)). Image data is only *located*, not decoded.
- Writing the container: `encoder._write_header` and `_Writer.finish`; per-frame GCE + descriptor + data come from Pillow's `GifImagePlugin.getdata` ([page](codebase/src/gif_editor/core/encoder.md)).
- Test writer: `tests/corpus.py::encode_gif` writes every block by hand ([page](codebase/tests/corpus.md)).

## LZW

Image data is the frame's palette indices (row by row) compressed with a variant of LZW:
- The **minimum code size** byte `m` (2..8) says the first codes are `m+1` bits wide.
- Code `2^m` is **Clear** (reset the dictionary) and `2^m + 1` is **End of Information**.
- As the dictionary grows, code width increases up to 12 bits. Encoders emit Clear when it is full.
- Codes are packed LSB-first into bytes, then cut into ≤ 255-byte sub-blocks.

Short or corrupt streams are common in the wild. Browsers show the pixels that decoded and leave the rest of the rectangle unchanged.

**In our code:**
- Decoding uses Pillow's C decoder through `Image.Image.frombytes(data, "gif", bits, interlace, -1)` in `decoder._decode_indices`. Short data keeps the decoded prefix (located with the 0/255 double-decode trick; see the [decoder page](codebase/src/gif_editor/core/decoder.md#step-2-decode-one-frames-indices-_decode_indices-l393-435)). The minimum code size is validated to 1..12.
- Encoding uses Pillow's encoder inside `GifImagePlugin.getdata` (`encoder._write_frame`).
- Tests: `tests/corpus.py::lzw_encode` emits only literal codes at a fixed width with frequent Clears. That is valid but uncompressed, and obviously correct.
- `core/selftest.py` checks that both Pillow internals still work.

## Palettes and quantisation

Every pixel is an **index** into a colour table of at most **256** RGB entries. A table always has a power-of-two size (2, 4, …, 256), so unused entries are padded.
- **Global table:** shared by all frames that don't bring their own.
- **Local table:** per frame. Lets each frame use different colours, at the cost of 768 bytes per frame and of index-level comparisons between frames.
- An index beyond the table is undefined. Browsers draw it as opaque black, and so do we.

**Quantisation** turns full-colour pixels (millions of possible colours) into ≤ 256 palette colours:
1. **Choose the palette.** We use median cut: split the colour cube where the pixels are densest. If an image already has few colours, use them exactly.
2. **Map** every pixel to a palette index, optionally with **dithering**. Floyd–Steinberg spreads each pixel's rounding error to its neighbours, which turns banding into noise.

Dithering has a cost in animations: when one area changes, the error pattern shifts everywhere, so static pixels flip between colours (**shimmer**). That looks bad and defeats frame differencing.

**In our code** (`core/render.py`, [page](codebase/src/gif_editor/core/render.md)):
- `build_palette`: **one shared palette** for the whole output, from ≤ 16 evenly spaced rendered frames. It takes the exact path when the colours fit, and median cut otherwise.
- `quantize(..., palette, previous)`: maps onto it. Pillow ignores `dither` for MEDIANCUT, so we build the palette first and map second. `previous` keeps the old index for unchanged pixels, so there is no shimmer.
- `Quality(colors, dither)` in `core/models.py`.
- Reading: `decoder._make_lut` turns each table into a 256-entry RGBA lookup.

## Transparency index

GIF has no alpha channel. Instead, the GCE can name one palette index as **transparent**: pixels with that index are *not drawn*, so whatever is already on the canvas shows through. Consequences:
- Transparency is **binary**: there is no semi-transparency.
- "Transparent" means "keep the pixel underneath", not "make it clear". On a fresh canvas the result is clear; over an earlier frame it is that frame's pixel. Encoders exploit this for differencing (below).
- The transparent index is **per frame**. Each GCE may choose a different one, or none.

**In our code:**
- Decoding: `decoder._Compositor.draw` masks out `f.transparent`.
- Rendering: alpha < 128 → transparent (`render.ALPHA_THRESHOLD`). A shared palette reserves its **last** index for transparency (`render.Palette.transparent_index`).
- Encoding: `encoder._Writer._marker` picks the index declared transparent per frame.
- `SourceMeta.has_transparency` ("any composited pixel not opaque") decides whether the output palette reserves a transparent slot (`pipeline.output_palette`). Gate 1 decision: source transparency is preserved.

## Disposal methods

The GCE's disposal method says what happens to the frame's rectangle **after** it has been displayed for its delay, before the next frame is drawn:

| Value | Spec name | Meaning (spec) | Browsers | Pillow 12.3 (reading) | Our decoder |
|---|---|---|---|---|---|
| 0 | unspecified | decoder's choice | keep | keep | keep |
| 1 | do not dispose | leave the frame in place | keep | keep | keep |
| 2 | restore to background | fill the rect with the **background colour** | **clear the rect to transparent** (background index ignored) | fills with an **opaque** colour (background colour, or `palette[transparent]`) when the canvas is RGB, i.e. when frame 0 had no transparency index | clear to transparent (browser) |
| 3 | restore to previous | restore the rect to what it was before this frame | restore | restore | restore |
| 4-7 | undefined | — | treated as keep | — | keep |

Because users judge results in a browser, **we follow browsers**. The Pillow behaviour is pinned by two strict xfails (`tests/core/test_corpus.py`, entry `disposal_background`, frames 2 and 3).

A frame can only *add* opaque pixels or *keep* pixels. The only way to make an opaque pixel transparent again is disposal 2 (or 3) on an earlier frame.

**In our code:**
- Decoding: `decoder._Compositor.dispose` and the module docstring "Why our own compositor" ([page](codebase/src/gif_editor/core/decoder.md#why-we-do-not-let-pillow-composite)).
- Disposal 3 needs the pre-frame state, which is why `_resume_point` cannot restart from a cached disposal-3 frame.
- Encoding: we write disposal 1 normally, and disposal 2 (full canvas) on the frame *before* an opaque→transparent change. This is decided with a one-frame look-ahead (`encoder._Writer.add`).
- Reference: `tests/corpus.py::compose`.

## Delays: centiseconds and browser clamping

- The delay is a `uint16` in **centiseconds** (1/100 s). Possible delays are 0, 10, 20, … ms up to 655.35 s. A 33.3 ms (30 fps) frame cannot be represented exactly.
- **Browser clamping:** browsers treat a delay of 0 or 1 cs (≤ 10 ms) as **10 cs (100 ms)**, because ancient GIFs used 0 to mean "as fast as possible" and would otherwise spin. The shortest delay that plays as written is therefore **2 cs = 20 ms, which means 50 fps is the real maximum**.
- A GIF with no GCE has delay 0, and so plays at 100 ms per frame in a browser.

**In our code:**
- Reading: `FrameMeta.delay_ms` (raw) vs `effective_delay_ms` (`decoder._effective_delay`: ≤ 10 → 100). The timeline uses effective delays (`SourceMeta.delays_ms`), so durations match what the user saw.
- Planning: `timeline._enforce_min_delay` (fold frames < 20 ms), `_round_cs` (round cumulative time to cs, carry the error, min 2 cs), the 65535 cs split in `plan_output` ([page](codebase/src/gif_editor/core/timeline.md)). `models.MAX_FPS = 50`.
- Writing: `encoder._check_frame` rejects delays outside 2..65535 cs.

## Loop count (NETSCAPE2.0)

Looping is not in the GIF spec. Netscape added an Application Extension `NETSCAPE2.0` whose sub-block `01 <uint16 count>` sets the loop count:
- **0 means forever.**
- **No block at all** means play once (in browsers).
- Viewers disagree on whether a count `N` includes the first play.
- `ANIMEXTS1.0` is a rare alias with the same layout.

**In our code:**
- `decoder._parse` reads both identifiers into `SourceMeta.loop` (`None` if absent).
- `encoder._write_header` writes the block unless `loop is None`.
- `pipeline.generate` passes the **source's** value through, so a GIF that played once still plays once (review finding 8).
- When looping and frame 0 has transparency, the last frame is written with disposal 2, so the restart begins from a clear canvas (`encoder._Writer.finish`).

## Interlacing

An interlaced frame stores its rows in four passes, so a slow download shows a coarse preview first:

| Pass | Rows |
|---|---|
| 1 | 0, 8, 16, … (every 8th from 0) |
| 2 | 4, 12, 20, … (every 8th from 4) |
| 3 | 2, 6, 10, … (every 4th from 2) |
| 4 | 1, 3, 5, … (every 2nd from 1) |

The pixels are identical once the frame is fully decoded; only the storage order differs. That matters in two places:
- **Partial data:** the decoded prefix is in *storage* order, so the "written" mask must map storage position → row.
- **Clipping:** for a non-interlaced frame taller than the canvas, the decoder can stop after the visible rows. An interlaced one stores row 1 near the end, so every row must be decoded.

**In our code:**
- `decoder._interlace_rows` and `_decode_indices` (Pillow de-interlaces; we compute the rank of each row for the written-mask).
- `tests/corpus.py::interlace_order` and the `interlaced` corpus entry (height 13, so every pass is partial).
- Our encoder never writes interlaced frames: `GifImagePlugin.getdata` writes the descriptor without the interlace flag.

## Frame differencing

Consecutive animation frames are usually mostly identical. Rewriting every full frame wastes space. GIF lets a frame be a smaller rectangle *and* lets pixels be transparent ("keep what's underneath"), so an encoder can write only what changed:
1. Compare frame k with frame k−1 **as decoded colours**.
2. Write only the bounding rectangle of the changed pixels (disposal 1, so k−1 stays underneath).
3. Inside the rectangle, set unchanged pixels to an index declared transparent. Long runs of one index compress very well with LZW.

Limits:
- A diff can't make a pixel transparent (transparent = keep), so an opaque→transparent change needs the previous frame disposed with method 2.
- With per-frame palettes the same colour can have different indices, so the comparison must be on colours, not indices.
- If all 256 indices are used inside the rectangle, there is no free "keep" index, and unchanged pixels are simply re-written.

**In our code:** `encoder._Writer` ([page](codebase/src/gif_editor/core/encoder.md#lossless-difference-frames-_writer-l175-276)). Comparisons use packed RGBA, so the output is lossless by construction. The global table is reused when the palette is identical (always the case with the shared palette). Before this (`8e7d34c`), re-saving a test GIF produced 679 KB; with shared palette + differencing it produces 21 KB.

## Pillow's own GIF quirks (why we wrote our own code)

| Quirk (Pillow 12.3) | Effect | Our response |
|---|---|---|
| Disposal 2 composites to an opaque colour when frame 0 has no transparency index | later frames lose transparency, wrong colours | own compositor (`decoder.py`) |
| GIF seeking is forward-only; backward = recomposite from 0 | slow scrubbing | keyframe checkpoints + LRU |
| `save_all` crops frames by comparing against the first frame's transparent colour | opaque pixels of that colour become transparent | own container writer (`encoder.py`) |
| `save_all` can emit a second header mid-file | corrupt output | same |
| `save_all` merges identical consecutive frames | frame count and durations change | same; frames are never merged |
| `quantize(MEDIANCUT)` ignores `dither` | no dithering | build the palette, then map (`render.py`) |
| The reader only returns RGBA when frame 0 declares a transparency index | readers lose alpha | the encoder declares an unused index on frame 0 |

Because we depend on Pillow internals (`frombytes(..., "gif", ...)`, `getdata`), Pillow is pinned and `core/selftest.py` verifies a round trip.
