"""M4 stress probe: open hard GIFs through the real window and measure GUI-thread stalls.

Not a test (too slow for the suite). Run:
  LD_LIBRARY_PATH=.devlibs/root/usr/lib/x86_64-linux-gnu QT_QPA_PLATFORM=offscreen \\
    PYTHONPATH=src:tests .venv/bin/python scripts/stress_probe.py
A 10 ms QTimer records the gap between ticks; a gap far above 10 ms means the GUI thread
was blocked (the window would look frozen for that long).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QElapsedTimer, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")
from corpus import build_all  # noqa: E402
from gif_editor.ui.main_window import MainWindow  # noqa: E402


class StallMeter:
    def __init__(self) -> None:
        self.gaps: list[float] = []
        self.clock = QElapsedTimer()
        self.timer = QTimer()
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        if self.clock.isValid():
            self.gaps.append(self.clock.restart())
        else:
            self.clock.start()

    def __enter__(self) -> StallMeter:
        self.gaps.clear()
        self.clock.invalidate()
        self.timer.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.timer.stop()

    def report(self, label: str) -> None:
        worst = max(self.gaps, default=0)
        over = sum(1 for g in self.gaps if g > 100)
        print(f"  {label:34s} worst stall {worst:6.0f} ms   stalls>100ms: {over}")


def pump(seconds: float, until=None) -> None:
    t = time.time()
    while time.time() - t < seconds:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.002)


def make_big(path: Path, w: int, h: int, n: int) -> Path:
    rng = np.random.default_rng(1)
    base = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    frames = []
    for i in range(n):
        a = base.copy()
        a[(i * 3) % h : (i * 3) % h + 40, :, :] = 255 - a[(i * 3) % h : (i * 3) % h + 40, :, :]
        frames.append(Image.fromarray(a).quantize(64))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40, loop=0)
    return path


def main() -> None:
    d = Path(__file__).resolve().parent.parent / "out" / "stress"  # inside the project
    d.mkdir(parents=True, exist_ok=True)
    meter = StallMeter()
    w = MainWindow()
    w.resize(1300, 820)
    w.show()

    cases = {
        "big 1280x720x150": make_big(d / "big.gif", 1280, 720, 150),
        "huge 1920x1080x200 (> cache)": make_big(d / "huge.gif", 1920, 1080, 200),
    }
    corpus = build_all(d / "corpus")
    for name in ("truncated", "not_a_gif", "large_canvas_header", "zero_delays", "interlaced"):
        cases[f"corpus:{name}"] = corpus[name][0]

    for label, path in cases.items():
        print(f"{label}  ({path.stat().st_size / 1e6:.1f} MB)")
        w.last_error = None
        with meter:
            t0 = time.time()
            w.open_file(path)
            pump(60, until=lambda: not w.is_busy)
            dt = time.time() - t0
        meter.report(f"open ({dt:.2f} s)")
        print(f"    opened={w.doc.is_open and w.doc.path == path}  error={w.last_error!r}")
        print(f"    status={w.statusBar().currentMessage()!r}")
        if not (w.doc.is_open and w.doc.path == path):
            continue
        n = w.doc.meta.frame_count
        with meter:
            for i in range(n - 1, -1, -max(1, n // 40)):  # scrub backwards
                w.doc.set_current_index(i)
                app.processEvents()
        meter.report("scrub backwards")
        with meter:
            w.act_play.trigger()
            pump(2)
            w.act_play.trigger()
        meter.report("play 2 s")
        with meter:
            w.act_preview.trigger()
            pump(1.5)
            w.act_preview.trigger()
        meter.report("preview edits on/off")
        with meter:
            w.generate_to(d / "out.gif")
            pump(120, until=lambda: not w.is_busy)
        meter.report(
            f"generate -> {w.last_result.size_bytes / 1e6:.2f} MB" if w.last_result else "generate"
        )
        QThreadPool.globalInstance().waitForDone()
    w.close()


if __name__ == "__main__":
    main()
