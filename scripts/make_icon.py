"""Generate the app icon.

The repo keeps no binary art: this script is the source. Run it after changing the design:

    .venv/bin/python scripts/make_icon.py

Two things it gets right that a naive resize does not:
- **Sizes are drawn, not scaled.** Details that read at 256 px (film sprockets, rounded
  corners) turn to mush at 16 px, where the Windows taskbar and the file list use the icon.
  So small sizes are a simplified drawing: a bigger, bolder play triangle, no sprockets.
- **Each size is rendered directly**, which keeps edges crisp; the master is only used for
  the largest entries of the .ico and for the PNGs.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src" / "gif_editor" / "resources" / "icons"

BG = (32, 34, 40, 255)  # near-black plate
ACCENT = (86, 190, 130, 255)  # green, matching the app's trim handles
WHITE = (245, 246, 248, 255)

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
PNG_SIZES = [16, 24, 32, 48, 64, 256]


def draw(size: int) -> Image.Image:
    """The icon drawn at ``size`` x ``size`` px: a dark plate with a play triangle."""
    ss = 4  # supersample, then downscale: smooth edges without blurring the shapes
    s = size * ss
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.20), fill=BG)
    small = size <= 32
    if small:
        # Below ~32 px there is room for the triangle and nothing else: make it bold and
        # centred, leaving a margin thin enough that it still reads at 16 px.
        cx, cy = s * 0.5, s * 0.5
        w, h = s * 0.46, s * 0.58
        d.polygon(
            [(cx - w * 0.5, cy - h * 0.5), (cx - w * 0.5, cy + h * 0.5), (cx + w * 0.7, cy)],
            fill=WHITE,
        )
        return img.resize((size, size), Image.LANCZOS)

    # Larger sizes: film strip on the left, play triangle in the remaining area.
    hole_w, hole_h = int(s * 0.075), int(s * 0.10)
    for i in range(3):
        y = int(s * (0.17 + i * 0.24))
        d.rounded_rectangle(
            [int(s * 0.07), y, int(s * 0.07) + hole_w, y + hole_h],
            radius=int(hole_w * 0.4),
            fill=ACCENT,
        )
    cx, cy = s * 0.60, s * 0.5
    w, h = s * 0.40, s * 0.52
    d.polygon(
        [(cx - w * 0.5, cy - h * 0.5), (cx - w * 0.5, cy + h * 0.5), (cx + w * 0.7, cy)],
        fill=WHITE,
    )
    return img.resize((size, size), Image.LANCZOS)


def check() -> int:
    """Exit 1 if the committed icons differ from what ``draw`` produces now.

    Compares decoded pixels, not file bytes: PNG/ICO compression depends on the zlib build
    inside Pillow's wheel, which differs between Windows and Linux, so a byte comparison
    could fail in CI on pixel-identical files.
    """
    stale = []
    for size in PNG_SIZES:
        path = OUT / f"icon-{size}.png"
        if not path.exists():
            stale.append(f"{path.name} missing")
            continue
        with Image.open(path) as committed:
            if committed.convert("RGBA").tobytes() != draw(size).tobytes():
                stale.append(path.name)
    ico = OUT / "icon.ico"
    if not ico.exists():
        stale.append("icon.ico missing")
    else:
        with Image.open(ico) as im:
            sizes = {s[0] for s in im.info.get("sizes", set())}
        if sizes != set(ICO_SIZES):
            stale.append(f"icon.ico sizes {sorted(sizes)} != {ICO_SIZES}")
    if stale:
        print("Stale icons (run scripts/make_icon.py and commit): " + ", ".join(stale))
        return 1
    print("Icons are up to date.")
    return 0


def main() -> None:
    import sys

    if "--check" in sys.argv:
        raise SystemExit(check())
    OUT.mkdir(parents=True, exist_ok=True)
    images = {size: draw(size) for size in sorted(set(ICO_SIZES + PNG_SIZES))}
    images[256].save(OUT / "icon.png", format="PNG")
    for size in PNG_SIZES:
        images[size].save(OUT / f"icon-{size}.png", format="PNG")
    # One multi-size .ico: Windows picks the entry it needs (16 px in lists, 256 px in the
    # large-icon view). Pillow writes every requested size into the file.
    images[256].save(
        OUT / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=[images[s] for s in ICO_SIZES],
    )
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir() if p.suffix in (".png", ".ico"))))


if __name__ == "__main__":
    main()
