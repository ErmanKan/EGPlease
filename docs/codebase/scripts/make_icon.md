# `scripts/make_icon.py`

> Draws the app icon in code and writes it as PNGs and one multi-size `.ico`; with `--check` it verifies that the committed icon files still match the drawing (M5).

## Where it sits
- **Layer:** tooling (Pillow only, no Qt)
- **Used by:** contributors after changing the icon design; [`.github/workflows/build-exe.yml`](../config-files.md#githubworkflowsbuild-exeyml) runs `--check`; [`scripts/build.py`](build.md) tells you to run it if `icon.ico` is missing.
- **Uses:** Pillow (`Image`, `ImageDraw`). Writes to `src/gif_editor/resources/icons/` ([what is in there](../config-files.md#srcgif_editorresourcesicons)).

## Public API
```bash
.venv/bin/python scripts/make_icon.py           # (re)write every icon file
.venv/bin/python scripts/make_icon.py --check   # exit 0 if the committed files match, 1 if stale
```

| Name | Kind | Purpose |
|---|---|---|
| `OUT` | constant | `src/gif_editor/resources/icons/`. |
| `BG`, `ACCENT`, `WHITE` | constants | Plate colour (near-black `32,34,40`), sprocket green (`86,190,130`, the trim-handle green), triangle white. |
| `ICO_SIZES` | constant | `[16, 24, 32, 48, 64, 128, 256]`: the entries inside `icon.ico`. |
| `PNG_SIZES` | constant | `[16, 24, 32, 48, 64, 256]`: the `icon-<n>.png` files. |
| `draw(size) -> Image` | function | The icon at `size`×`size` px, RGBA. |
| `check() -> int` | function | Compare committed files with `draw()`; print the result; 0 = up to date, 1 = stale or missing. |
| `main()` | function | `--check` → `SystemExit(check())`; otherwise write all files. |

## How it works
### The drawing
- A dark **rounded plate** (corner radius 20 % of the size) fills the square; outside the corners is transparent.
- **Sizes ≥ 48 px:** three green rounded **film sprockets** down the left edge, and a white **play triangle** centred at 60 % of the width.
- **Sizes ≤ 32 px:** no sprockets; a bigger, bolder triangle in the centre.

*Why small sizes are drawn, not downscaled:* Windows shows the 16 px and 24 px entries in Explorer's lists and in the taskbar. The detailed design, scaled down to 16 px, turned into a featureless dark square: the sprockets and the margins around a small triangle blur into the plate. So small sizes are a separate, simplified drawing that still reads as "play" at 16 px.

*Supersampling:* each size is drawn at 4× its size (`ss = 4`) and reduced with LANCZOS. That gives smooth anti-aliased edges (Pillow's polygon drawing has none) without blurring the shapes the way scaling one big master down would.

### Writing (`main`)
1. Draw every size in `ICO_SIZES ∪ PNG_SIZES` once.
2. Save `icon.png` (the 256 px image; the same pixels as `icon-256.png`) and `icon-<n>.png` for each `PNG_SIZES` entry.
3. Save `icon.ico` from the 256 px image with `sizes=` all seven `ICO_SIZES` and `append_images=` the separately drawn images, so each `.ico` entry is the drawing made for that size rather than a resize of the 256 px one. Windows picks the entry it needs (16 px in lists, 256 px in the large-icon view).

### Checking (`--check`)
- For each `PNG_SIZES` file: decode it, convert to RGBA and compare the raw **pixels** with a fresh `draw(size)`. Missing files count as stale.
- For `icon.ico`: it must exist and contain exactly the sizes in `ICO_SIZES`.

*Why pixels, not bytes:* PNG and ICO data are zlib-compressed, and the compressed bytes depend on the zlib build inside Pillow's wheel, which differs between Windows and Linux. The first CI step regenerated the icons and ran `git diff --exit-code`; on a Windows runner that could fail on files whose pixels are identical. Comparing decoded pixels removes the dependence on the compressor. As a check of the check, a 1-pixel change in the 16 px drawing was verified to be reported as stale (`icon-16.png`, exit 1).

## Invariants & gotchas
- **The script is the source of the icon.** The repo keeps no hand-made art. Change `draw()`, run the script, commit the script and the regenerated files together; CI fails otherwise.
- `--check` does **not** compare `icon.png` (it is not in `PNG_SIZES`) or the pixels of the `.ico` entries, only the `.ico`'s size list. A stale `.ico` with the right sizes would pass. In practice all files are written by the same run.
- `icon-128.png` is not written (128 px exists only inside the `.ico`).
- Pixel equality assumes Pillow's drawing and LANCZOS give identical results on every OS for the pinned Pillow 12.3.0; that held in the container (CI on Windows will confirm it on its first run).
- Output is under `src/` on purpose: the icons are package data, shipped by `--include-package-data=gif_editor` and found at runtime by [`gif_editor.resources`](../src/gif_editor/resources/__init__.md).

## Tests
- No pytest file; the `--check` mode is the test (CI step "Check the committed icons match scripts/make_icon.py").
- `tests/core/test_resources.py` checks that the icons are found at runtime.

## History
- `3531ca0` (M5): added; small sizes drawn separately after the 16 px version of the detailed design was unreadable.
- `7bac56c` (M5): `--check` (pixel comparison) replaced the CI step that regenerated the icons and compared bytes with `git diff` ([dev log, Milestone 5](../../04-development-log.md#milestone-5-packaging)).
