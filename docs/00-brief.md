# 00 — Brief: GIF Editor (desktop)

## Idea (restated)
A Windows desktop GIF editor. The user loads a `.gif` and adjusts global output settings: **playback speed, FPS, quality, duration, start time, output size**.
A secondary panel on the right is a **frame inspector** with a **timebar/scrubber**. There the user can step through the GIF frame by frame, **delete individual frames**, define a **crop region by dragging an interactive rectangle**, and **save the current frame** as an image.
Clicking **Generate** writes a new GIF that applies all of those edits.

- **Problem:** Trimming, retiming, cropping and shrinking GIFs today means either heavy tools (Photoshop, GIMP) or CLI tools (ffmpeg, gifsicle). Both are clumsy for quick visual edits.
- **Target user:** Anyone who wants fast, visual GIF tuning on Windows without learning a complex tool.
- **Core value:** One window, live frame-accurate preview, and a single "Generate" producing an optimized GIF.

## Intake answers
| Topic | Answer |
|---|---|
| Target OS | Windows only |
| Stack | Python desktop: PySide6 (Qt) |
| Distribution (v1) | Single portable .exe / installer |
| Export formats | GIF only (+ PNG for "save current frame") |

## Constraints
- Work lives in `F:\Projects\gif-editor` (container: `/workspace/projects/gif-editor`).
- No global installs; dependencies are project-local (`.venv`).
