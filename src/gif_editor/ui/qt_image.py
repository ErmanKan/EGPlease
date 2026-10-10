"""Conversions between Pillow images and Qt images, plus small paint helpers.

Workers may call ``pil_to_qimage`` from any thread (QImage is thread-safe to create);
QPixmap must only be created on the GUI thread (``QPixmap.fromImage``).
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap


def pil_to_qimage(img: Image.Image) -> QImage:
    """Return an independent RGBA8888 QImage copy of ``img`` (any Pillow mode)."""
    rgba = img if img.mode == "RGBA" else img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    w, h = rgba.size
    # .copy() detaches the QImage from the Python bytes buffer, which would otherwise
    # be freed when ``data`` goes out of scope.
    return QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


def checkerboard_brush(cell: int = 8) -> QBrush:
    """A light-grey checkerboard brush, the usual backdrop for transparent pixels."""
    tile = QPixmap(cell * 2, cell * 2)
    tile.fill(QColor(255, 255, 255))
    p = QPainter(tile)
    grey = QColor(204, 204, 204)
    p.fillRect(0, 0, cell, cell, grey)
    p.fillRect(cell, cell, cell, cell, grey)
    p.end()
    brush = QBrush(tile)
    brush.setStyle(Qt.BrushStyle.TexturePattern)
    return brush
