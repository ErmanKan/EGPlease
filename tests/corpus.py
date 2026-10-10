"""Code-generated corpus of tricky GIFs plus an independent reference compositor.

Pillow's GIF writer cannot produce several structures we must decode correctly (partial frames
at offsets with a chosen disposal, local colour tables only, interlacing, 0 cs delays, no
NETSCAPE loop block, truncation), so this module contains a tiny raw GIF89a writer:

* ``encode_gif(spec)`` turns a :class:`GifSpec` into bytes.
* ``compose(spec)`` is a reference compositor implementing *browser* disposal semantics:
  the canvas starts fully transparent; disposal 0/1 leave the frame in place, 2 clears the
  frame rectangle to transparent (browsers ignore the background colour), 3 restores the canvas
  as it was before the frame was drawn.
* ``ENTRIES`` maps corpus names to builders; ``build_all(dir)`` writes every entry and returns
  ``{name: (path, Expected)}``.

Nothing here imports the decoder under test, and no binary fixture is ever committed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]

TRANSPARENT: RGBA = (0, 0, 0, 0)

# Default 8-colour palette (index -> RGB). Distinct, saturated colours so offset bugs show up.
PAL8: tuple[RGB, ...] = (
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (0, 255, 255),
    (255, 0, 255),
    (255, 255, 255),
    (0, 0, 0),
)


# --------------------------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameSpec:
    """One GIF image block. ``indices`` is row-major (``width * height`` palette indices)."""

    width: int
    height: int
    indices: bytes
    left: int = 0
    top: int = 0
    local_palette: Sequence[RGB] | None = None
    disposal: int = 1
    delay_cs: int = 10
    transparent: int | None = None
    interlace: bool = False
    gce: bool = True  # write a Graphic Control Extension before the image descriptor

    def __post_init__(self) -> None:
        if len(self.indices) != self.width * self.height:
            raise ValueError("indices length must equal width*height")
        if not 0 <= self.disposal <= 7:
            raise ValueError("disposal out of range")


@dataclass(frozen=True)
class GifSpec:
    width: int
    height: int
    frames: Sequence[FrameSpec]
    global_palette: Sequence[RGB] | None = PAL8
    background: int = 0
    loop: int | None = 0  # None -> no NETSCAPE2.0 extension
    trailer: bool = True


@dataclass(frozen=True)
class Expected:
    """What a correct (browser-like) decoder should report for a corpus file.

    kind: "valid" | "truncated" (first ``frame_count`` frames decodable, then an error)
          | "invalid" (not a GIF) | "huge" (header only; frames not composited).
    """

    kind: str
    description: str
    canvas_size: tuple[int, int] | None = None
    frame_count: int = 0
    delays_cs: tuple[int, ...] = ()
    loop: int | None = None
    has_transparency: bool = False
    frames: tuple[Image.Image, ...] = field(default=(), repr=False)
    declared_frame_count: int | None = None  # frames present in the stream (truncated: 3)

    @property
    def delays_ms(self) -> tuple[int, ...]:
        return tuple(d * 10 for d in self.delays_cs)


# --------------------------------------------------------------------------------------------
# Raw GIF89a writer
# --------------------------------------------------------------------------------------------


def _table_bits(n_colours: int) -> int:
    """Smallest b >= 1 such that 2**b >= n_colours (colour tables hold 2**b entries)."""
    b = 1
    while (1 << b) < n_colours:
        b += 1
    if b > 8:
        raise ValueError("a GIF colour table holds at most 256 colours")
    return b


def _colour_table(palette: Sequence[RGB]) -> tuple[int, bytes]:
    """Return (size field 0..7, padded table bytes)."""
    bits = _table_bits(len(palette))
    padded = list(palette) + [(0, 0, 0)] * ((1 << bits) - len(palette))
    return bits - 1, b"".join(bytes(c) for c in padded)


def lzw_encode(indices: bytes, min_code_size: int) -> bytes:
    """Minimal, always-correct GIF LZW encoder (no compression).

    Only literal codes are emitted, at the constant width ``min_code_size + 1``. A decoder adds
    one dictionary entry per code after the first following a clear code and widens its codes
    when the next free code reaches ``2**width``; emitting a clear code every
    ``2**min_code_size - 2`` literals keeps the next free code below that, so the width never
    changes. Returns the packed code stream (LSB-first), not yet split into sub-blocks.
    """
    clear = 1 << min_code_size
    eoi = clear + 1
    width = min_code_size + 1
    run = clear - 2
    codes: list[int] = []
    for i, px in enumerate(indices):
        if px >= clear:
            raise ValueError(f"index {px} does not fit min code size {min_code_size}")
        if i % run == 0:
            codes.append(clear)
        codes.append(px)
    if not indices:
        codes.append(clear)
    codes.append(eoi)

    out = bytearray()
    acc = 0
    nbits = 0
    for code in codes:
        acc |= code << nbits
        nbits += width
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits:
        out.append(acc & 0xFF)
    return bytes(out)


def _sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i : i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)  # block terminator
    return bytes(out)


def interlace_order(height: int) -> list[int]:
    """Source row numbers in the order they are stored in an interlaced GIF image."""
    return [
        *range(0, height, 8),
        *range(4, height, 8),
        *range(2, height, 4),
        *range(1, height, 2),
    ]


def _u16(v: int) -> bytes:
    return v.to_bytes(2, "little")


def encode_gif(spec: GifSpec) -> tuple[bytes, list[int]]:
    """Serialise ``spec``. Returns (bytes, offset of each frame's image data sub-blocks)."""
    out = bytearray(b"GIF89a")
    out += _u16(spec.width) + _u16(spec.height)
    if spec.global_palette is not None:
        size_field, gct = _colour_table(spec.global_palette)
        out += bytes([0x80 | (7 << 4) | size_field, spec.background, 0])
        out += gct
    else:
        out += bytes([7 << 4, spec.background, 0])

    if spec.loop is not None:
        out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01" + _u16(spec.loop) + b"\x00"

    data_offsets: list[int] = []
    for f in spec.frames:
        palette = f.local_palette if f.local_palette is not None else spec.global_palette
        if palette is None:
            raise ValueError("frame has no colour table (no local and no global)")
        if f.gce:
            packed = (f.disposal << 2) | (1 if f.transparent is not None else 0)
            out += b"\x21\xf9\x04" + bytes([packed]) + _u16(f.delay_cs)
            out += bytes([f.transparent or 0, 0])
        packed = 0x40 if f.interlace else 0
        lct = b""
        if f.local_palette is not None:
            size_field, lct = _colour_table(f.local_palette)
            packed |= 0x80 | size_field
        out += b"\x2c" + _u16(f.left) + _u16(f.top) + _u16(f.width) + _u16(f.height)
        out += bytes([packed]) + lct

        rows = interlace_order(f.height) if f.interlace else range(f.height)
        stored = b"".join(f.indices[r * f.width : (r + 1) * f.width] for r in rows)
        min_code_size = max(2, _table_bits(len(palette)))
        out.append(min_code_size)
        data_offsets.append(len(out))
        out += _sub_blocks(lzw_encode(stored, min_code_size))

    if spec.trailer:
        out += b"\x3b"
    return bytes(out), data_offsets


# --------------------------------------------------------------------------------------------
# Reference compositor (browser semantics)
# --------------------------------------------------------------------------------------------


def compose(spec: GifSpec, *, frames: int | None = None) -> list[Image.Image]:
    """Composite the first ``frames`` frames of ``spec`` into full-canvas RGBA images."""
    w, h = spec.width, spec.height
    canvas: list[RGBA] = [TRANSPARENT] * (w * h)
    result: list[Image.Image] = []
    for f in list(spec.frames)[:frames]:
        palette = f.local_palette if f.local_palette is not None else spec.global_palette
        assert palette is not None
        before = list(canvas)
        for y in range(f.height):
            cy = f.top + y
            if not 0 <= cy < h:
                continue
            for x in range(f.width):
                cx = f.left + x
                if not 0 <= cx < w:
                    continue
                idx = f.indices[y * f.width + x]
                if f.transparent is not None and idx == f.transparent:
                    continue
                canvas[cy * w + cx] = (*palette[idx], 255)
        result.append(_to_image(canvas, w, h))
        if f.disposal == 2:
            for y in range(max(0, f.top), min(h, f.top + f.height)):
                for x in range(max(0, f.left), min(w, f.left + f.width)):
                    canvas[y * w + x] = TRANSPARENT
        elif f.disposal == 3:
            canvas = before
    return result


def _to_image(pixels: Sequence[RGBA], w: int, h: int) -> Image.Image:
    return Image.frombytes("RGBA", (w, h), b"".join(bytes(p) for p in pixels))


def normalize_rgba(img: Image.Image) -> bytes:
    """RGBA bytes with the RGB of fully transparent pixels zeroed (their colour is irrelevant)."""
    raw = bytearray(img.convert("RGBA").tobytes())
    for i in range(0, len(raw), 4):
        if raw[i + 3] == 0:
            raw[i : i + 3] = b"\x00\x00\x00"
    return bytes(raw)


def _expected_from_spec(spec: GifSpec, description: str) -> Expected:
    return Expected(
        kind="valid",
        description=description,
        canvas_size=(spec.width, spec.height),
        frame_count=len(spec.frames),
        delays_cs=tuple(f.delay_cs if f.gce else 0 for f in spec.frames),
        loop=spec.loop,
        has_transparency=any(f.transparent is not None for f in spec.frames),
        frames=tuple(compose(spec)),
        declared_frame_count=len(spec.frames),
    )


# --------------------------------------------------------------------------------------------
# Pixel pattern helpers
# --------------------------------------------------------------------------------------------


def pattern(w: int, h: int, fn: Callable[[int, int], int]) -> bytes:
    return bytes(fn(x, y) for y in range(h) for x in range(w))


def solid(w: int, h: int, idx: int) -> bytes:
    return bytes([idx]) * (w * h)


def diag(w: int, h: int, offset: int = 0, mod: int = 8) -> bytes:
    """Diagonal stripes: index = (x + y + offset) % mod — catches row/column offset bugs."""
    return pattern(w, h, lambda x, y: (x + y + offset) % mod)


# --------------------------------------------------------------------------------------------
# Corpus entries: each builder returns (spec | raw bytes, Expected)
# --------------------------------------------------------------------------------------------


def spec_basic() -> GifSpec:
    return GifSpec(
        12,
        10,
        [FrameSpec(12, 10, diag(12, 10, i), delay_cs=d) for i, d in enumerate((10, 20, 30))],
    )


def spec_partial_offsets() -> GifSpec:
    return GifSpec(
        16,
        12,
        [
            FrameSpec(16, 12, diag(16, 12)),
            FrameSpec(4, 3, diag(4, 3, 3, 5), left=2, top=3),
            FrameSpec(5, 4, solid(5, 4, 6), left=9, top=6, delay_cs=20),
        ],
    )


def spec_disposal_background() -> GifSpec:
    return GifSpec(
        16,
        12,
        [
            FrameSpec(16, 12, diag(16, 12)),
            # disposal 2, no transparent index -> rect cleared to transparent (browser)
            FrameSpec(6, 4, solid(6, 4, 2), left=2, top=2, disposal=2),
            # disposal 2 with a transparent index (idx 6 pixels show through)
            FrameSpec(
                5,
                4,
                pattern(5, 4, lambda x, y: 6 if (x + y) % 2 else 4),
                left=9,
                top=6,
                disposal=2,
                transparent=6,
            ),
            FrameSpec(3, 3, solid(3, 3, 5), left=0, top=9),
        ],
        background=3,
    )


def spec_disposal_previous() -> GifSpec:
    return GifSpec(
        16,
        12,
        [
            FrameSpec(16, 12, diag(16, 12)),
            FrameSpec(6, 6, solid(6, 6, 7), left=1, top=1, disposal=3),
            FrameSpec(4, 4, solid(4, 4, 6), left=8, top=4, disposal=3),
            FrameSpec(2, 2, solid(2, 2, 2), left=12, top=0),
        ],
    )


def spec_local_palettes() -> GifSpec:
    p2: list[RGB] = [(10, 20, 30), (200, 100, 50)]
    p4: list[RGB] = [(0, 0, 0), (80, 80, 80), (160, 160, 160), (240, 240, 240)]
    p16: list[RGB] = [(i * 16, 255 - i * 16, (i * 37) % 256) for i in range(16)]
    return GifSpec(
        10,
        8,
        [
            FrameSpec(10, 8, diag(10, 8, 0, 2), local_palette=p2),
            FrameSpec(10, 8, diag(10, 8, 1, 4), local_palette=p4),
            FrameSpec(6, 4, diag(6, 4, 0, 16), left=3, top=2, local_palette=p16),
        ],
        global_palette=None,
    )


def spec_transparency_changes() -> GifSpec:
    first = bytearray(diag(12, 10, 0, 6))  # indices 0..5
    for i in (0, 1, 13, 50, 119):  # a few first-frame transparent pixels (index 7)
        first[i] = 7
    return GifSpec(
        12,
        10,
        [
            FrameSpec(12, 10, bytes(first), transparent=7),
            # transparent=1: index 1 shows earlier content, index 0 (red) is drawn
            FrameSpec(5, 4, pattern(5, 4, lambda x, y: (x + y) % 2), left=1, top=1, transparent=1),
            # transparent=0 now: index 0 shows through, index 1 (green) is drawn; overlaps frame 1
            FrameSpec(5, 5, pattern(5, 5, lambda x, y: x % 2), left=3, top=3, transparent=0),
        ],
    )


def spec_zero_delays() -> GifSpec:
    return GifSpec(
        8,
        8,
        [FrameSpec(8, 8, solid(8, 8, i), delay_cs=d) for i, d in enumerate((0, 1, 0))],
    )


def spec_no_loop() -> GifSpec:
    return GifSpec(
        8, 6, [FrameSpec(8, 6, solid(8, 6, 1)), FrameSpec(8, 6, solid(8, 6, 2))], loop=None
    )


def spec_single_frame() -> GifSpec:
    # Plain single image: no NETSCAPE block and no Graphic Control Extension at all.
    return GifSpec(7, 5, [FrameSpec(7, 5, diag(7, 5), gce=False)], loop=None)


def spec_interlaced() -> GifSpec:
    # Height 13 (not a multiple of 8) so every interlace pass is partially filled.
    return GifSpec(
        9,
        13,
        [
            FrameSpec(9, 13, pattern(9, 13, lambda x, y: y % 8), interlace=True),
            FrameSpec(
                4, 5, pattern(4, 5, lambda x, y: 7 - y), left=4, top=6, interlace=True, delay_cs=5
            ),
        ],
    )


def spec_truncated() -> GifSpec:
    return GifSpec(
        10,
        10,
        [FrameSpec(10, 10, diag(10, 10, i)) for i in range(3)],
        trailer=False,
    )


def spec_large_canvas_header() -> GifSpec:
    return GifSpec(20000, 20000, [FrameSpec(2, 2, bytes([0, 1, 2, 3]))])


@dataclass(frozen=True)
class Entry:
    name: str
    build: Callable[[], tuple[bytes, Expected]]


def _valid(name: str, spec_fn: Callable[[], GifSpec], description: str) -> Entry:
    def build() -> tuple[bytes, Expected]:
        spec = spec_fn()
        return encode_gif(spec)[0], _expected_from_spec(spec, description)

    return Entry(name, build)


def _build_truncated() -> tuple[bytes, Expected]:
    spec = spec_truncated()
    data, offsets = encode_gif(spec)
    cut = offsets[2] + 6  # inside the third frame's LZW data (after its descriptor)
    assert cut < len(data) - 2
    full = _expected_from_spec(spec, "")
    exp = Expected(
        kind="truncated",
        description="3 full frames declared; bytes cut mid third frame's image data; no trailer",
        canvas_size=full.canvas_size,
        frame_count=2,
        delays_cs=full.delays_cs[:2],
        loop=0,
        frames=full.frames[:2],
        declared_frame_count=3,
    )
    return data[:cut], exp


def _build_not_a_gif() -> tuple[bytes, Expected]:
    buf = BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue(), Expected(kind="invalid", description="PNG bytes with a .gif extension")


def _build_large_canvas_header() -> tuple[bytes, Expected]:
    spec = spec_large_canvas_header()
    return encode_gif(spec)[0], Expected(
        kind="huge",
        description="logical screen 20000x20000 with a single 2x2 frame (limit tests)",
        canvas_size=(20000, 20000),
        frame_count=1,
        delays_cs=(10,),
        loop=0,
        declared_frame_count=1,
    )


ENTRIES: dict[str, Entry] = {
    e.name: e
    for e in (
        _valid("basic", spec_basic, "3 full frames, global palette, delays 10/20/30 cs"),
        _valid(
            "partial_offsets",
            spec_partial_offsets,
            "full first frame, then small rects at offsets, disposal 1",
        ),
        _valid(
            "disposal_background",
            spec_disposal_background,
            "partial frames with disposal 2 (one opaque, one with transparent index); bg idx 3",
        ),
        _valid("disposal_previous", spec_disposal_previous, "partial frames with disposal 3"),
        _valid(
            "local_palettes",
            spec_local_palettes,
            "no global table; local tables of 2, 4 and 16 colours",
        ),
        _valid(
            "transparency_changes",
            spec_transparency_changes,
            "transparent index 7 -> 1 -> 0; partial frames over earlier content",
        ),
        _valid("zero_delays", spec_zero_delays, "delays 0, 1, 0 cs"),
        _valid("no_loop", spec_no_loop, "2 frames, no NETSCAPE2.0 extension"),
        _valid("single_frame", spec_single_frame, "one frame, no GCE, no loop extension"),
        _valid("interlaced", spec_interlaced, "interlaced full frame (h=13) + interlaced rect"),
        Entry("truncated", _build_truncated),
        Entry("not_a_gif", _build_not_a_gif),
        Entry("large_canvas_header", _build_large_canvas_header),
    )
}

VALID_ENTRIES: tuple[str, ...] = tuple(
    n for n in ENTRIES if n not in {"truncated", "not_a_gif", "large_canvas_header"}
)


def write_entry(name: str, directory: Path) -> tuple[Path, Expected]:
    data, expected = ENTRIES[name].build()
    path = Path(directory) / f"{name}.gif"
    path.write_bytes(data)
    return path, expected


def build_all(directory: Path) -> dict[str, tuple[Path, Expected]]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return {name: write_entry(name, directory) for name in ENTRIES}
