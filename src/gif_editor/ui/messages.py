"""Plain-language explanations for errors the user can hit.

The core raises precise technical errors (``GifLoadError``, ``OSError``...). Those messages
are right for logs and tests but wrong for a dialog: "Frame 3 is 70000x2 ... malformed" or
"[Errno 13] Permission denied: '...\\.out.gif.1f3a.tmp'" tell a user neither what happened
in their terms nor what to do next.

Each function here turns an exception into an :class:`Explanation`: a window title, a
one-line headline, a short "what happened / what to do" body, and the original message as
``details`` (the dialog shows it behind "Show Details...", so nothing is lost for bug
reports).

The functions are pure (no Qt), so every branch is unit-tested in tests/ui/test_messages.py.
"""

from __future__ import annotations

import errno
from dataclasses import dataclass
from pathlib import Path

from gif_editor.core.decoder import GifLoadError

__all__ = ["Explanation", "explain_generate_error", "explain_load_error", "explain_load_warnings"]

# Windows reports a file locked by another program as OSError.winerror 32/33, with an
# errno (EACCES) that would otherwise read as "no permission".
_WINERROR_SHARING_VIOLATION = 32
_WINERROR_LOCK_VIOLATION = 33


@dataclass(frozen=True)
class Explanation:
    """What to show: ``title`` (window title), ``headline`` (bold first line),
    ``body`` (what happened and what to do) and ``details`` (technical text)."""

    title: str
    headline: str
    body: str
    details: str = ""

    @property
    def text(self) -> str:
        """Headline and body as one string (status bar, logs, ``last_error``)."""
        return f"{self.headline}\n{self.body}" if self.body else self.headline


def _q(name: str) -> str:
    return f"\u201c{name}\u201d"


def explain_load_error(exc: BaseException, path: str | Path) -> Explanation:
    """Explain why ``path`` could not be opened."""
    name = _q(Path(path).name)
    title = "Can't open file"
    details = str(exc) or type(exc).__name__
    kind = getattr(exc, "kind", None)
    info = getattr(exc, "info", {}) or {}

    if kind == GifLoadError.NOT_FOUND:
        return Explanation(
            title,
            f"{name} no longer exists.",
            "It may have been moved, renamed or deleted. Open it again from its new location.",
            details,
        )
    if kind == GifLoadError.IS_DIRECTORY:
        return Explanation(title, f"{name} is a folder.", "Choose a .gif file inside it.", details)
    if kind == GifLoadError.UNREADABLE:
        return Explanation(
            title,
            f"{name} can't be read.",
            "You may not have permission to read it, or another program has it locked. "
            "Close other programs using it, or copy it somewhere else and open the copy.",
            details,
        )
    if kind == GifLoadError.EMPTY:
        return Explanation(
            title,
            f"{name} is empty (0 bytes).",
            "The file has no content, often because a download or copy did not finish.",
            details,
        )
    if kind == GifLoadError.NOT_GIF:
        return Explanation(
            title,
            f"{name} is not a GIF.",
            "Its content is a different format, even if the name ends in .gif. "
            "Convert it to GIF first, or choose another file.",
            details,
        )
    if kind == GifLoadError.TOO_LARGE:
        w, h, side = info.get("width"), info.get("height"), info.get("max_side")
        size = f" ({w}\u00d7{h} pixels)" if w and h else ""
        limit = f" The largest supported size is {side:,} pixels on a side." if side else ""
        return Explanation(
            title,
            f"{name} is too large to edit{size}.",
            f"Opening it could use more memory than is safe.{limit}",
            details,
        )
    if kind == GifLoadError.TOO_MANY_FRAMES:
        n = info.get("max_frames")
        return Explanation(
            title,
            f"{name} has too many frames.",
            f"The editor supports up to {n:,} frames per GIF." if n else "",
            details,
        )
    if isinstance(exc, GifLoadError):  # MALFORMED, and any kind added later
        return Explanation(
            title,
            f"{name} is damaged.",
            "It looks like a GIF but its data is broken, so no frame could be shown. "
            "If you downloaded it, try downloading it again.",
            details,
        )
    if isinstance(exc, MemoryError):
        return Explanation(
            title,
            f"Not enough memory to open {name}.",
            "Close other programs and try again.",
            details,
        )
    return Explanation(
        title,
        f"{name} could not be opened.",
        "An unexpected error occurred. The details can help when reporting it.",
        details,
    )


def explain_load_warnings(warnings: list[str], path: str | Path, frames: int) -> Explanation:
    """The file opened, but only partly (e.g. truncated). Say so: it changes the output."""
    plural = "s" if frames != 1 else ""
    return Explanation(
        "Opened with problems",
        f"{_q(Path(path).name)} is damaged; {frames} frame{plural} could be loaded.",
        "Everything that could be read is shown, and you can edit and generate as usual. "
        "Anything after the damage is missing, so the result may be shorter than the "
        "original.",
        "\n".join(warnings),
    )


def explain_generate_error(
    exc: BaseException, path: str | Path, title: str = "Generate failed"
) -> Explanation:
    """Explain why writing ``path`` failed (Generate, or Save frame with another ``title``).

    Both writers write a temporary file and rename it at the end, so on any failure the
    destination is untouched; every message says so, because users fear losing a file.
    """
    p = Path(path)
    details = str(exc) or type(exc).__name__
    keep = "Nothing was written; any existing file with that name is unchanged."

    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        if winerror in (_WINERROR_SHARING_VIOLATION, _WINERROR_LOCK_VIOLATION):
            return Explanation(
                title,
                f"{_q(p.name)} is open in another program.",
                f"Close it there, or choose a different name, and generate again. {keep}",
                details,
            )
        code = exc.errno
        if code in (errno.EACCES, errno.EPERM):
            return Explanation(
                title,
                f"No permission to save in {_q(p.parent.name or str(p.parent))}.",
                "The folder is read-only or protected, or the file is open in another "
                f"program. Choose another folder, such as Pictures or Documents. {keep}",
                details,
            )
        if code == errno.ENOSPC:
            return Explanation(
                title,
                "The disk is full.",
                f"Free some space or save to another drive. {keep}",
                details,
            )
        if code == errno.ENOENT:
            return Explanation(
                title,
                f"The folder {_q(str(p.parent))} no longer exists.",
                f"Choose another location. {keep}",
                details,
            )
        if code == errno.ENAMETOOLONG:
            return Explanation(
                title,
                "The file name or path is too long.",
                f"Choose a shorter name or a folder closer to the drive root. {keep}",
                details,
            )
        return Explanation(
            title,
            f"{_q(p.name)} could not be saved.",
            f"The system reported an error while writing. {keep}",
            details,
        )
    if isinstance(exc, MemoryError):
        return Explanation(
            title,
            "Not enough memory to generate this GIF.",
            f"Make the output smaller (size or number of frames) or close other programs. {keep}",
            details,
        )
    return Explanation(
        title,
        "The GIF could not be generated.",
        f"An unexpected error occurred. {keep} The details can help when reporting it.",
        details,
    )
