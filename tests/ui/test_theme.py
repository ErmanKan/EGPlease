"""Tests for the light/dark colour fixes (``ui/theme.py``) and where they are used.

The "dark" palette is an approximation of Qt's Windows dark-mode palette: #1E1E1E window,
buttons one step lighter, white text, the Windows accent. Rendered checks grab real
widgets under that palette and measure WCAG contrast on the pixels.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from gif_editor.ui import theme
from gif_editor.ui.inspector.player import Player
from gif_editor.ui.inspector.transport import TransportBar
from gif_editor.ui.settings_panel import SettingsPanel

Role = QPalette.ColorRole
Group = QPalette.ColorGroup
WINDOWS_ACCENT = QColor(0x00, 0x78, 0xD4)


def dark_palette(accent: QColor = WINDOWS_ACCENT) -> QPalette:
    bg, fg = QColor(0x1E, 0x1E, 0x1E), QColor(255, 255, 255)
    button = bg.lighter(200)
    pal = QPalette()
    for role, c in {
        Role.Window: bg, Role.WindowText: fg, Role.Base: bg.lighter(150), Role.Text: fg,
        Role.Button: button, Role.ButtonText: fg, Role.Highlight: accent,
        Role.HighlightedText: fg, Role.Light: button.lighter(200),
        Role.Midlight: button.lighter(150), Role.Mid: button.darker(150),
        Role.Dark: button.darker(200),
    }.items():  # fmt: skip
        pal.setColor(Group.All, role, c)
    for role in (Role.WindowText, Role.Text, Role.ButtonText):
        pal.setColor(Group.Disabled, role, QColor(120, 120, 120))
    return pal


@pytest.fixture
def app_palette(qapp):
    """Lets a test set the app palette; the system palette is restored afterwards."""
    yield qapp
    set_app_palette(qapp, QPalette())  # empty palette = back to the system colours


def set_app_palette(app: QApplication, pal: QPalette) -> None:
    """Set the app palette and let shown widgets receive their (posted) PaletteChange."""
    app.setPalette(pal)
    app.processEvents()


def fill_and_glyph(widget) -> tuple[QColor, float]:
    """Button fill colour (left edge, inside the border) and best glyph contrast on it."""
    img = widget.grab().toImage()
    w, h = img.width(), img.height()
    fill = QColor(img.pixel(4, h // 2))
    best = max(
        theme.contrast_ratio(QColor(img.pixel(x, y)), fill)
        for y in range(2, h - 2)
        for x in range(3, w - 3)
    )
    return fill, best


# ----------------------------------------------------------------------- colour maths
def test_contrast_ratio_known_values():
    assert theme.contrast_ratio(QColor("black"), QColor("white")) == pytest.approx(21.0)
    assert theme.contrast_ratio(QColor("#777777"), QColor("#777777")) == pytest.approx(1.0)
    # Symmetric.
    a, b = QColor("#0078d4"), QColor("#ffffff")
    assert theme.contrast_ratio(a, b) == pytest.approx(theme.contrast_ratio(b, a))


def test_mix_endpoints_and_midpoint():
    a, b = QColor(0, 0, 0), QColor(200, 100, 50)
    assert theme.mix(a, b, 0).name() == "#000000"
    assert theme.mix(a, b, 1).name() == b.name()
    assert theme.mix(a, b, 0.5).name() == "#643219"


def test_is_dark():
    assert theme.is_dark(dark_palette())
    light = QPalette(QColor("#efefef"))  # Qt derives a light palette from the button colour
    assert not theme.is_dark(light)


# ----------------------------------------------------------------------- palette
def test_tuned_palette_lifts_dark_buttons_off_the_window():
    base = dark_palette()
    window = base.color(Role.Window)
    before = theme.contrast_ratio(base.color(Role.Button), window)
    tuned = theme.tuned_palette(base)
    for group in (Group.Active, Group.Inactive):
        assert theme.contrast_ratio(tuned.color(group, Role.Button), window) >= 2.0 > before
    # Disabled buttons: dimmer than enabled ones, text still readable on them.
    off = tuned.color(Group.Disabled, Role.Button)
    assert theme.relative_luminance(off) < theme.relative_luminance(tuned.color(Role.Button))
    assert theme.contrast_ratio(tuned.color(Group.Disabled, Role.ButtonText), off) >= 2.5


def test_tuned_palette_never_darkens_and_leaves_light_alone():
    base = dark_palette()
    base.setColor(Group.All, Role.Button, QColor("#808080"))  # already light enough
    assert theme.tuned_palette(base).color(Role.Button).name() == "#808080"
    light = QPalette(QColor("#efefef"))
    tuned = theme.tuned_palette(light)
    for group in (Group.Active, Group.Disabled):
        for role in (Role.Button, Role.ButtonText, Role.Window):
            assert tuned.color(group, role) == light.color(group, role)


def test_apply_starts_from_the_system_palette(app_palette):
    """Re-applying after a light/dark switch must not stack on the old tuned colours."""
    app_palette.setPalette(dark_palette())
    theme.apply(app_palette)  # offscreen's system palette is light
    assert not theme.is_dark(app_palette.palette())
    theme.install(app_palette)
    theme.install(app_palette)  # idempotent: connects the scheme signal once
    assert not theme.is_dark(app_palette.palette())


# ----------------------------------------------------------------------- media icons
@pytest.mark.parametrize("kind", theme.MEDIA_KINDS)
def test_media_icon_uses_the_button_text_colour(kind):
    pal = dark_palette()
    icon = theme.media_icon(kind, pal)
    for mode, group in ((QIcon.Mode.Normal, Group.Active), (QIcon.Mode.Disabled, Group.Disabled)):
        img = icon.pixmap(16, 16, mode).toImage()
        opaque = [
            QColor.fromRgba(img.pixel(x, y))
            for y in range(16)
            for x in range(16)
            if QColor.fromRgba(img.pixel(x, y)).alpha() == 255
        ]
        assert len(opaque) >= 20, "icon shape is missing"
        want = pal.color(group, Role.ButtonText).rgb()
        assert all(c.rgb() == want for c in opaque)


def test_media_icon_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown media icon"):
        theme.media_icon("rewind", QPalette())


# ----------------------------------------------------------------------- primary button
@pytest.mark.parametrize(
    "accent", ["#0078d4", "#308cc6", "#60cdff", "#ffb900", "#003e92", "#e81123", "#00cc6a"]
)
def test_primary_colors_are_readable_for_any_accent(accent):
    pal = dark_palette(QColor(accent))
    fill, text = theme.primary_colors(pal)
    assert theme.contrast_ratio(fill, text) >= theme.PRIMARY_MIN_CONTRAST
    assert text.name() in ("#000000", "#ffffff")


def test_mark_primary_follows_palette_changes(app_palette, qtbot):
    button = QPushButton("Generate")
    qtbot.addWidget(button)
    button.show()  # Qt sends palette events only to shown (polished) widgets
    theme.mark_primary(button)
    assert button.property("primary") is True
    first = button.styleSheet()
    assert theme.primary_colors(QApplication.palette())[0].name() in first
    set_app_palette(app_palette, dark_palette(QColor("#e81123")))
    fill = theme.primary_colors(QApplication.palette())[0].name()
    assert fill in button.styleSheet() and button.styleSheet() != first


# ----------------------------------------------------------------------- in the widgets
def test_transport_buttons_framed_and_icons_follow_the_palette(app_palette, doc, qtbot):
    bar = TransportBar(doc, Player(doc))
    qtbot.addWidget(bar)
    bar.show()  # Qt sends palette events only to shown (polished) widgets
    tools = [bar.first_button, bar.prev_button, bar.play_button, bar.next_button, bar.last_button]
    assert all(isinstance(b, QToolButton) and not b.autoRaise() for b in tools)

    def icon_colour(button) -> QColor:
        img = button.icon().pixmap(16, 16).toImage()
        return next(
            QColor.fromRgba(img.pixel(x, y))
            for y in range(16)
            for x in range(16)
            if QColor.fromRgba(img.pixel(x, y)).alpha() == 255
        )

    set_app_palette(app_palette, dark_palette())
    assert icon_colour(bar.first_button).name() == "#ffffff"
    set_app_palette(app_palette, QPalette(QColor("#efefef")))
    assert icon_colour(bar.first_button).lightness() < 60
    # The play/pause swap keeps the current palette colour.
    set_app_palette(app_palette, dark_palette())
    bar._on_playing_changed(True)
    assert icon_colour(bar.play_button).name() == "#ffffff"


def test_rendered_dark_mode_buttons_are_visible(app_palette, doc, qtbot):
    """Grab real widgets under the tuned dark palette and measure the pixels."""
    set_app_palette(app_palette, theme.tuned_palette(dark_palette()))
    window = QApplication.palette().color(Role.Window)
    bar = TransportBar(doc, Player(doc))
    panel = SettingsPanel(doc)
    for w in (bar, panel):
        qtbot.addWidget(w)
        w.show()
    qtbot.waitExposed(panel)

    for button in (bar.first_button, bar.play_button, bar.save_button):
        fill, glyph = fill_and_glyph(button)
        assert theme.contrast_ratio(fill, window) >= 2.0, button.accessibleName()
        assert glyph >= 4.5, button.accessibleName()

    assert panel.generate_button.isEnabled()
    fill, glyph = fill_and_glyph(panel.generate_button)
    assert theme.contrast_ratio(fill, window) >= 3.0
    assert glyph >= theme.PRIMARY_MIN_CONTRAST
