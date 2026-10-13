"""Headless one-shot edit, used by the packaging smoke test and by scripted use.

    GifEditor --edit-spec IN.gif "trim=0:400,delete=2,crop=8:6:40:30,size=32x24,out=OUT.gif"

Why this exists: a packaged GUI app cannot be checked automatically, so a broken bundle
(missing plugin, missing data file, a bad import) would only be discovered by a user. This
path runs one complete edit + generate with no window and prints a `RESULT ...` line, so
`scripts/smoke_build.py` (and CI) can assert that the built executable really opens, edits
and writes a GIF.

The spec is a comma-separated list of `key=value` items, applied in the order written.
Because a comma separates items, a list uses colons inside the value:

    trim=START:END           keep frames in [START, END); END optional = to the end.
                             Whole numbers are milliseconds, decimals are seconds
                             (end=400 -> 400 ms, start=0.5 -> 500 ms).
    duration=MS              keep MS from the trim start (integer milliseconds)
    delete=0:3:5             delete these source frame indexes (colon-separated)
    crop=X:Y:W:H             crop the frame (source pixels)
    speed=1.5                playback speed
    fps=12                   FPS limit
    size=WxH                 output size
    colors=N                 palette size (2..256)
    dither=0|1               dithering
    out=PATH                 where to write (required)

It is a thin wrapper over `core.pipeline.generate` / `render_output_frame`, so it exercises
exactly the code the GUI uses.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from gif_editor.core.decoder import GifSource
from gif_editor.core.models import CropRect, EditState, OutputSize
from gif_editor.core.pipeline import generate


def _ms(value: str) -> int:
    """A time in the spec: a whole number is milliseconds, a decimal is seconds.

    Documented behaviour, and the reason `trim=0.5:1.5` works: writing 1.5 for "1.5 ms"
    would be a trap, while 1.5 s is what a human means by it.
    """
    return round(float(value) * 1000) if "." in value else int(value)


def parse_spec(spec: str, state: EditState) -> tuple[EditState, Path]:
    """Apply ``spec`` to ``state``; return the new state and the output path."""
    out: Path | None = None
    for item in [p.strip() for p in spec.split(",") if p.strip()]:
        if "=" not in item:
            raise ValueError(f"bad spec item {item!r} (expected key=value)")
        key, _, value = item.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key == "trim":
            start_s, _, end_s = value.partition(":")
            start = _ms(start_s)
            if end_s:
                end = _ms(end_s)
                state = state.with_(trim_start_ms=start, trim_duration_ms=end - start)
            else:
                state = state.with_(trim_start_ms=start, trim_duration_ms=None)
        elif key == "duration":
            state = state.with_(trim_duration_ms=int(value))
        elif key == "delete":
            state = state.with_(deleted=frozenset(int(v) for v in value.split(":") if v != ""))
        elif key == "crop":
            x, y, w, h = (int(v) for v in value.replace("x", ":").split(":"))
            state = state.with_(crop=CropRect(x, y, w, h))
        elif key == "speed":
            state = state.with_(speed=float(value))
        elif key == "fps":
            state = state.with_(fps=float(value))
        elif key == "size":
            w, h = (int(v) for v in value.lower().split("x"))
            state = state.with_(size=OutputSize(w, h))
        elif key == "colors":
            state = state.with_(quality=replace(state.quality, colors=int(value)))
        elif key == "dither":
            state = state.with_(quality=replace(state.quality, dither=bool(int(value))))
        elif key == "out":
            out = Path(value)
        else:
            raise ValueError(f"unknown spec key {key!r}")
    if out is None:
        raise ValueError("spec needs out=PATH")
    return state, out


def run_edit_spec(source_path: str | Path, spec: str) -> int:
    """Open ``source_path``, apply ``spec``, generate; print RESULT...; return an exit code."""
    try:
        state, out = parse_spec(spec, EditState())
        with GifSource.open(source_path) as source:
            result = generate(source, state, out)
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")
        return 1
    print(
        f"RESULT frames={result.frame_count} size={result.width}x{result.height} "
        f"bytes={result.size_bytes} ms={result.duration_ms} path={result.path}"
    )
    return 0
