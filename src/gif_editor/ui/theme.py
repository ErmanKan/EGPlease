"""Light/dark colour fixes on top of the system palette: button contrast, icons, Generate.

The app uses Qt's Fusion style, which takes its colours from the system palette. In
Windows dark mode that leaves buttons hard to see: Fusion draws a button's border as the
window colour darkened (near-black on a near-black window), and Qt's built-in media icons
are dark grey glyphs (1.2:1 against the dark window, practically invisible). Three fixes:

* ``tuned_palette``: in a dark palette, lighten the button fill until it stands out
  from the window (light palettes are returned unchanged).
* ``media_icon``: transport icons drawn as vector shapes in the palette's button-text
  colour, so they are dark on light and light on dark.
* ``mark_primary``: the main action (Generate) is filled with the accent colour. This one
  uses a style sheet with exact colours, because Fusion lightens and desaturates a
  palette-coloured button (white text on the result measured only 2.2:1); the colours are
  picked so the text has at least ``PRIMARY_MIN_CONTRAST`` against the fill.

``install(app)`` applies the palette and re-applies it when Windows switches between
light and dark while the app runs. Widgets that hold palette-derived colours (the
transport icons, the primary button) refresh on ``QEvent.PaletteChange``. Not on
``ApplicationPaletteChange``: Qt sends that one only to top-level windows, and before
their palette is updated. Qt also skips palette events for a widget that was never shown
or polished (its palette is resolved when it is), which only matters in tests.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QAbstractButton, QApplication

Role = QPalette.ColorRole
Group = QPalette.ColorGroup

#: Button fill in dark mode: this far from the window colour towards the text colour.
#: 0.22 turns Windows' #1E1E1E window into a #4F4F4F button (2.1:1 against the window).
BUTTON_MIX = 0.22
#: Same for disabled buttons: still visibly a button, but clearly dimmer than enabled ones.
DISABLED_BUTTON_MIX = 0.10
#: Disabled button text in dark mode: dim, but still readable (about 3:1 on the fill).
DISABLED_TEXT_MIX = 0.55
#: Minimum text contrast on the primary button (WCAG AA for normal text).
PRIMARY_MIN_CONTRAST = 4.5
#: Pixel sizes the media icons are pre-rendered at (16 px at 100-300 % scaling).
ICON_SIZES = (16, 20, 24, 32, 48)

MEDIA_KINDS = ("first", "prev", "play", "pause", "next", "last")


# ----------------------------------------------------------------------- colours
def relative_luminance(c: QColor) -> float:
    """WCAG relative luminance of an sRGB colour, 0 (black) to 1 (white)."""

    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(c.redF()) + 0.7152 * channel(c.greenF()) + 0.0722 * channel(c.blueF())


def contrast_ratio(a: QColor, b: QColor) -> float:
    """WCAG contrast ratio, 1.0 (identical) to 21.0 (black on white)."""
    hi, lo = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """``a`` moved the fraction ``t`` (0..1) of the way towards ``b``."""
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
    )


def is_dark(palette: QPalette) -> bool:
    """True when the window background is darker than its text (a dark theme)."""
    return relative_luminance(palette.color(Role.Window)) < relative_luminance(
        palette.color(Role.WindowText)
    )


def tuned_palette(base: QPalette) -> QPalette:
    """``base`` with button fills lifted off the window colour in a dark theme.

    Only ever lightens (a system palette that already has light enough buttons is kept).
    Touches ``Button`` in every group and the disabled ``ButtonText``; light palettes come
    back unchanged.
    """
    pal = QPalette(base)
    if not is_dark(base):
        return pal
    for group, amount in (
        (Group.Active, BUTTON_MIX),
        (Group.Inactive, BUTTON_MIX),
        (Group.Disabled, DISABLED_BUTTON_MIX),
    ):
        window = base.color(group, Role.Window)
        target = mix(window, base.color(group, Role.WindowText), amount)
        current = base.color(group, Role.Button)
        if relative_luminance(current) < relative_luminance(target):
            pal.setColor(group, Role.Button, target)
    window = base.color(Group.Disabled, Role.Window)
    text = mix(window, base.color(Group.Active, Role.WindowText), DISABLED_TEXT_MIX)
    if relative_luminance(base.color(Group.Disabled, Role.ButtonText)) < relative_luminance(text):
        pal.setColor(Group.Disabled, Role.ButtonText, text)
    return pal


# ----------------------------------------------------------------------- install
_installed: set[int] = set()


def apply(app: QApplication) -> None:
    """Replace the app palette by the tuned system palette.

    The app palette is first reset (an empty palette resolves to the system one), so
    calling this again after a light/dark switch starts from the new system colours, not
    from the previously tuned ones.
    """
    app.setPalette(QPalette())
    app.setPalette(tuned_palette(app.palette()))


def install(app: QApplication) -> None:
    """Apply the tuned palette now and again whenever the system colour scheme changes."""
    apply(app)
    if id(app) in _installed:
        return
    _installed.add(id(app))
    # Deferred: the scheme signal can arrive before Qt has loaded the new system palette.
    app.styleHints().colorSchemeChanged.connect(lambda *_: QTimer.singleShot(0, lambda: apply(app)))


# ----------------------------------------------------------------------- media icons
def _media_path(kind: str) -> QPainterPath:
    """Shape of a transport icon on a 16 x 16 grid (filled, no stroke)."""
    path = QPainterPath()

    def tri(x0: float, x1: float) -> None:  # triangle pointing from x0 to x1
        path.moveTo(x0, 3)
        path.lineTo(x1, 8)
        path.lineTo(x0, 13)
        path.closeSubpath()

    def bar(x: float) -> None:
        path.addRect(QRectF(x, 3, 2, 10))

    if kind == "play":
        tri(4, 13)
    elif kind == "pause":
        bar(4)
        bar(10)
    elif kind == "next":  # bar, then a triangle: step one frame forward
        bar(3)
        tri(6, 13)
    elif kind == "prev":
        bar(11)
        tri(10, 3)
    elif kind == "last":  # two triangles into a bar: jump to the end
        tri(1, 7)
        tri(6, 12)
        bar(12)
    elif kind == "first":
        bar(2)
        tri(15, 9)
        tri(10, 4)
    else:
        raise ValueError(f"unknown media icon {kind!r}; expected one of {MEDIA_KINDS}")
    path.setFillRule(Qt.FillRule.WindingFill)
    return path


def _render(path: QPainterPath, color: QColor, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 16, size / 16)
    p.fillPath(path, color)
    p.end()
    return pm


def media_icon(kind: str, palette: QPalette) -> QIcon:
    """A transport icon in the palette's button-text colour (normal and disabled)."""
    path = _media_path(kind)
    icon = QIcon()
    for mode, group in ((QIcon.Mode.Normal, Group.Active), (QIcon.Mode.Disabled, Group.Disabled)):
        color = palette.color(group, Role.ButtonText)
        for size in ICON_SIZES:
            icon.addPixmap(_render(path, color, size), mode)
    return icon


# ----------------------------------------------------------------------- primary button
def primary_colors(palette: QPalette) -> tuple[QColor, QColor]:
    """``(fill, text)`` for the primary button: the accent colour with readable text.

    Text is black or white, whichever contrasts more with the accent; the fill is then
    moved away from the text colour until the contrast reaches ``PRIMARY_MIN_CONTRAST``.
    (In dark mode that gives a light accent with black text, in light mode a dark accent
    with white text, as Windows 11 does.)
    """
    accent = palette.color(Group.Active, Role.Highlight)
    black, white = QColor(0, 0, 0), QColor(255, 255, 255)
    text = black if contrast_ratio(accent, black) >= contrast_ratio(accent, white) else white
    away = white if text == black else black
    fill = accent
    step = 0
    while contrast_ratio(fill, text) < PRIMARY_MIN_CONTRAST and step < 20:
        step += 1
        fill = mix(accent, away, step * 0.05)
    return fill, text


def primary_style_sheet(palette: QPalette) -> str:
    """Style sheet for the primary button, from the current palette (all states)."""
    fill, text = primary_colors(palette)
    away = QColor(0, 0, 0) if text.lightness() > 127 else QColor(255, 255, 255)
    hover = mix(fill, text, 0.12)
    pressed = mix(fill, away, 0.15)
    border = mix(fill, away, 0.25)
    off_fill = palette.color(Group.Disabled, Role.Button)
    off_text = palette.color(Group.Disabled, Role.ButtonText)
    focus = palette.color(Group.Active, Role.WindowText)
    return (
        f"QPushButton {{ background-color: {fill.name()}; color: {text.name()};"
        f" border: 1px solid {border.name()}; border-radius: 4px; padding: 4px 12px; }}\n"
        f"QPushButton:hover {{ background-color: {hover.name()}; }}\n"
        f"QPushButton:pressed {{ background-color: {pressed.name()}; }}\n"
        f"QPushButton:focus {{ border: 2px solid {focus.name()}; }}\n"
        f"QPushButton:disabled {{ background-color: {off_fill.name()};"
        f" color: {off_text.name()}; border-color: {mix(off_fill, focus, 0.15).name()}; }}"
    )


class _PrimaryRefresher(QObject):
    """Re-colours a primary button when the application palette changes."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.PaletteChange and isinstance(obj, QAbstractButton):
            sheet = primary_style_sheet(QApplication.palette())
            # Applying a style sheet re-polishes the button, which sends PaletteChange
            # again; the sheet is then unchanged, which ends the loop.
            if obj.styleSheet() != sheet:
                obj.setStyleSheet(sheet)
        return False


def mark_primary(button: QAbstractButton) -> None:
    """Fill ``button`` with the accent colour (the window's main action)."""
    button.setProperty("primary", True)
    button.setStyleSheet(primary_style_sheet(QApplication.palette()))
    refresher = _PrimaryRefresher(button)  # parented: lives as long as the button
    button.installEventFilter(refresher)
