# 01 — Research

Four read-only research agents ran in parallel on 2026-10-10. Below is a synthesis of their findings. Versions were checked against PyPI JSON on 2026-10-10 by the tech-stack agent.

---

## 1. Prior art

| Product | Licence | Strengths worth borrowing | Gaps vs our brief |
|---|---|---|---|
| **ScreenToGif** (C#/WPF, Windows) | Ms-PL | Thumbnail filmstrip with multi-select, Delete / delete-before / delete-after, Remove Duplicates, frame-count reduction, side panel that previews an action, rich keyboard shortcuts | Built around recording first; dense ribbon; no single panel of output settings with one Generate step |
| **ezgif.com** (web) | Proprietary | Simple single-purpose tools (crop, resize, speed, cut, optimize, frame editor); crop by drag *or* numeric W/H; speed as % or exact delay | Online only (privacy, size limits); one tool per page, re-upload between steps; no local scrubber |
| **gifsicle** (C CLI) | GPL-2.0 | Reference optimizer: `-O3`, `--lossy`, `--colors` | No GUI; GPL → can only be shipped as a separate exe |
| **gifski** (Rust) | AGPL-3.0 / commercial | Best quality (cross-frame palettes, temporal dithering) | AGPL → not bundleable in a non-AGPL app |
| **Kap** (Electron, macOS) | MIT | Minimal trim handles + FPS/size at export | No Windows, no frame-level editing |
| **LICEcap** | GPL-2 | Extremely simple | Recorder only, no editing |
| **GIMP** | GPL-3 | Pixel-level power | Frames are layers; delays are set via layer-name tags like "(100ms)"; no timeline. This is the pain point we remove |
| **GIPHY Maker** | Proprietary | Friendly trim slider and live preview | Online, tied to the platform, not frame-accurate |
| Python/Qt hobby projects (GIFCraft – Tkinter, Pyside6-GIF-Maker, faith289/GIF-maker – PyQt6) | Licences not verified | Pillow frame operations as reference | None combine GIF-in → frame inspector → crop → Generate |

**Takeaway:** combine ezgif's toolset (crop, resize, speed, cut, optimize) offline in one window, add ScreenToGif's filmstrip and shortcuts, and use Kap-style trim handles. Our differentiators: **non-destructive edits** with one Generate step, a **live summary** of output frames, duration, size and estimated file size, an interactive crop rectangle, and a portable offline build.

Sources: https://github.com/NickeManarin/ScreenToGif · https://github.com/NickeManarin/ScreenToGif/wiki/Help-%E2%96%AA-Editor-%E2%9C%8F%EF%B8%8F · https://ezgif.com/crop · https://ezgif.com/speed · https://github.com/kohler/gifsicle/ · https://www.lcdf.org/gifsicle/man.html · https://gif.ski/license.html · https://github.com/ImageOptim/gifski/issues/327 · https://github.com/wulkano/kap · https://cockos.com/licecap/ · https://docs.gimp.org/3.2/en/file-gif-export.html · https://giphy.com/create/gifmaker · https://github.com/coraxcode/GIFCraft · https://github.com/ADDag-src/Pyside6-GIF-Maker · https://github.com/faith289/GIF-maker

---

## 2. Tech stack

**Current versions (PyPI, 2026-10-10):** PySide6 / PySide6-Essentials 6.12.0 (Py ≥3.10,<3.16) · Pillow 12.3.0 · numpy 2.5.3 (Py ≥3.12) · PyInstaller 6.22.3 (<3.16) · pyinstaller-hooks-contrib 2026.8 · Nuitka 4.3 · Briefcase 0.4.5 · pytest 9.1.1 · pytest-qt 4.5.0 · ruff 0.17.0 · Inno Setup 6.7.3 (external tool).
→ The Python versions all of these support overlap at 3.12–3.15. **Target Python 3.13 x64.**

**Candidate stacks compared:**
- **A. PySide6-Essentials + Pillow (+ numpy) + PyInstaller one-dir + Inno Setup.** Fewest dependencies; permissive licences apart from Qt's LGPL; fastest builds; best documented. ✅ recommended
- **B. Same, frozen with Nuitka (standalone or onefile).** Starts faster, fewer antivirus hits, can produce a true single exe. Needs a C toolchain and slow builds.
- **C. Adds FFmpeg (PyAV/imageio-ffmpeg) or bundled gifsicle/gifski, packaged with Briefcase MSI.** Best compression, but +50–100 MB and GPL/AGPL licensing problems.

**GIF I/O with Pillow:**
- Pillow already applies disposal methods and returns fully composited frames.
- Use `LOADING_STRATEGY = RGB_ALWAYS` and `convert('RGBA')` so preview frames are consistent.
- Encode from full canvases, not from original sub-frames.
- Save with `save_all`, `append_images`, a per-frame `duration` list, an explicit `loop=0` and `disposal`.
- `optimize=True` only prunes the palette, and Pillow merges identical consecutive frames.

**Quality knobs (Pillow):**
- Colour count from 2 to 256.
- Dither: Floyd–Steinberg or none.
- Quantize method: MEDIANCUT for opaque frames, FASTOCTREE for RGBA frames.
- Optional shared palette to reduce flicker.
- Official Pillow wheels do **not** include libimagequant (GPLv3), so `Quantize.LIBIMAGEQUANT` is unavailable.

**Timing:**
- GIF delays are stored in centiseconds. Browsers clamp delays ≤10 ms to 100 ms, so the practical maximum is **50 fps (20 ms)**.
- Speed changes scale the delays and round them to whole centiseconds, carrying the rounding error forward.
- Higher speeds or FPS are reached by **dropping frames**, not by shrinking delays.

**Testing and tooling:** pytest + pytest-qt (`QT_QPA_PLATFORM=offscreen` in CI), golden-file tests on small generated GIFs, ruff for lint and formatting.

Sources: https://pypi.org/pypi/PySide6-Essentials/json · https://pypi.org/pypi/pillow/json · https://pypi.org/pypi/numpy/json · https://pypi.org/pypi/pyinstaller/json · https://pypi.org/pypi/nuitka/json · https://pypi.org/pypi/pytest-qt/json · https://pypi.org/pypi/ruff/json · https://github.com/python-pillow/Pillow/blob/main/docs/handbook/image-file-formats.rst · https://github.com/python-pillow/Pillow/blob/main/docs/installation/building-from-source.rst · https://github.com/Nuitka/Nuitka/blob/main/LICENSE-RUNTIME.txt · https://github.com/pyinstaller/pyinstaller/blob/develop/doc/operating-mode.rst · https://jrsoftware.org/isdl.php · https://bugzilla.mozilla.org/show_bug.cgi?id=232822 · https://learn.microsoft.com/en-us/archive/blogs/ieinternals/trivia-animated-gif-timing

---

## 3. Risks & constraints (prioritised)

1. **Memory.**
   - A full RGBA frame takes w×h×4 bytes: 1000×1000 is 4 MB per frame, so 1000 frames is about 4 GB.
   - Mitigation: index the file on load (metadata + 96 px thumbnails), composite full frames on demand into a byte-budgeted LRU cache with keyframe checkpoints, and convert to QPixmap only for the current frame.
2. **Random seeking is O(n).** Pillow seeks sequentially, so scrubbing backwards replays from frame 0. Mitigation: keyframe checkpoints, a debounced scrubber, and showing the thumbnail first.
3. **UI responsiveness.**
   - Decoding, thumbnail creation, quantising and Generate all run in QThreadPool workers.
   - QPixmap objects are created on the GUI thread only.
   - Generate reports progress, can be cancelled, writes to a temp file and then renames it atomically.
   - Frames are fed to the encoder by a generator so RAM doesn't spike.
4. **Pillow read/write bugs.**
   - Reading: local palettes, transparency on later frames, disposal 2/3 with offsets (#3735, #5755, #4640, #7787).
   - Writing: frame merging changes the frame count; transparency is lost; without `loop=` the GIF plays only once (#8746).
   - Mitigation: pin Pillow, keep a regression set of test GIFs, read the output back and check it, and pass loop, durations and disposal explicitly.
5. **Conflicting timing controls.** Speed, FPS and duration depend on each other, so setting all three over-constrains the output. Mitigation: start time and duration together define a **trim**; **Speed** is the one timing driver; **Output FPS** is an optional resample; output duration is **derived and read-only**. Resolved in the plan.
6. **Hostile input files.**
   - Keep `MAX_IMAGE_PIXELS` enabled.
   - Add app-level caps on canvas size, frame count and estimated decoded bytes.
   - Catch decode errors per frame and load whatever frames decoded successfully.
7. **LGPL obligations for PySide6.**
   - Qt DLLs must stay replaceable, which favours a one-dir build over onefile.
   - Ship the LGPL/GPL texts and a link to the Qt source; don't forbid reverse engineering.
   - Include THIRD_PARTY_LICENSES covering Pillow (HPND), PSF and the bundled libraries.
8. **Antivirus and SmartScreen.**
   - PyInstaller onefile builds often trigger antivirus false positives, and unsigned exes get the SmartScreen warning.
   - Mitigation: one-dir build, no UPX, optionally rebuild the bootloader, and code-sign. Azure Artifact Signing is about $9.99/month (individuals only in the US/CA); OV certificates run about $200–600/year.
9. **HiDPI.** Store crop coordinates in source pixels and use cosmetic pens. Test at 150% and 200% scaling.

Sources: https://github.com/python-pillow/Pillow/pull/6402 · https://github.com/python-pillow/Pillow/issues/8920 · https://github.com/python-pillow/Pillow/issues/7787 · https://github.com/python-pillow/Pillow/issues/8746 · https://github.com/python-pillow/Pillow/issues/5755 · https://github.com/orgs/pyinstaller/discussions/5499 · https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html · https://www.pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/ · https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options · https://azure.microsoft.com/en-us/pricing/details/artifact-signing/

---

## 4. UX patterns

**Reference layouts:**
- ScreenToGif: ribbon, centre viewer, action sidebar and bottom filmstrip.
- Photoshop: a timeline of frame thumbnails with a delay setting per frame.
- Shotcut and other video editors: a ruler with a playhead and green (in) / red (out) trim handles.

**De-facto shortcuts:**

| Action | Keys |
|---|---|
| Step one frame | ←/→ |
| Step ten frames | Shift+←/→ |
| Jump to start/end | Home/End |
| Play/pause | Space |
| Set trim in/out at the playhead | I / O |
| Delete frame(s) | Del |
| Undo/redo | Ctrl+Z / Ctrl+Y |

**Timebar:** a custom-painted ruler (ticks, playhead, trim handles; deleted frames hatched) plus a thumbnail filmstrip (QListView IconMode with lazy QPixmapCache thumbnails). Deleted frames **stay visible, greyed out**, and can be restored.

**Undo:** QUndoStack/QUndoCommand on top of a non-destructive edit state. `mergeWith` folds a whole drag into one undo step.

**Crop:**
- Built in-house: a QGraphicsView with a custom rectangle item that has 8 handles kept at a fixed screen size and can be dragged by its interior.
- Aspect presets: Free, Original, 1:1, 4:3, 16:9, 9:16.
- X/Y/W/H spinboxes sync with the rectangle in both directions.
- The area outside the crop is dimmed to about 50%, with a rule-of-thirds grid while dragging.
- QRubberBand was rejected (no handles); pyqtgraph ROI was rejected (too heavy a dependency); the C++ ImageCropper was rejected (LGPL, would need porting).

**Preview:** a live, timing-accurate preview built from cached frames. The exact frame count, duration and W×H are shown, plus a file size estimate ("≈ X MB") from sample-encoding a few frames in a worker. Palette and quality differences only appear after Generate.

**HiDPI and accessibility:** keep Qt 6's per-monitor DPI awareness, use the Fusion style, and give the custom widgets accessible names. Mirror their state into a standard QSlider and spinboxes so they work with the keyboard and screen readers.

Sources: https://github.com/NickeManarin/ScreenToGif/wiki/Help-▪-Editor-✏️-▪-Ribbon · https://helpx.adobe.com/photoshop/desktop/add-video-and-animation/create-animation-frames/timeline-panel-controls-and-features.html · https://www.shotcut.com/howtos/keyboard-shortcuts/ · https://ezgif.com/cut · https://pzgif.com/crop-gif · https://stackoverflow.com/questions/76763380/how-to-implement-resizable-rectangle-in-pyside6-qgraphicsview · https://doc.qt.io/qt-6/qrubberband.html · https://github.com/dimkanovikov/ImageCropper · https://doc.qt.io/qtforpython-6/PySide6/QtGui/QUndoStack.html · https://doc.qt.io/qt-6/highdpi.html · https://doc.qt.io/qt-6/accessible-qwidget.html

---

## Contradictions between agents

- **Frame caching.** The tech-stack agent suggested "cache all frames as RGBA up front"; the risks agent warned this can need ~4 GB for large GIFs. **Resolution:** decode everything eagerly while it fits under a byte budget (about 512 MB). Otherwise fall back to an LRU cache with keyframe checkpoints.
- **"Single portable .exe".** The intake answer asked for a single exe or installer. Every agent recommends a **one-dir build + installer + portable zip** over onefile, because of LGPL relinking, antivirus false positives and slow cold starts. A true single exe (Nuitka onefile) remains possible but is not the default. **Needs a user decision.**
- **Version provenance.** Two agents cited PySide6 6.12.0 from aggregator sites; the tech-stack agent confirmed it directly on PyPI JSON. The Pillow bug statuses (#7787, #8746, #3735) may already be fixed in 12.3.0, so verify them with the test corpus.
- **Optional optimizers.** The prior-art agent floated bundling gifsicle; the tech-stack and risks agents advise against it for v1 (GPL obligations, unverified Windows builds). **Resolution:** Pillow only in v1.
