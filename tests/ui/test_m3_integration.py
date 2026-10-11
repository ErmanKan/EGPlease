"""Milestone 3 wiring: geometry preview on the canvas, the size estimate in the summary
card, the crop panel inside the settings panel, and the main window's "Preview edits"."""

import pytest

from gif_editor.core.models import CropRect, OutputSize
from gif_editor.ui.inspector.canvas import FrameCanvas
from gif_editor.ui.inspector.preview import PreviewService
from gif_editor.ui.main_window import MainWindow
from gif_editor.ui.settings_panel import SettingsPanel, format_bytes
from gifgen import PALETTE


@pytest.fixture
def preview(qtbot, doc):
    svc = PreviewService(doc, debounce_ms=10)
    yield svc
    svc.dispose()


def _px(canvas):
    img = canvas.image_item.pixmap().toImage()
    c = img.pixelColor(0, 0)
    return (img.width(), img.height()), (c.red(), c.green(), c.blue())


# ------------------------------------------------------------------- canvas
def test_canvas_geometry_preview_shows_output_frame(qtbot, doc, preview):
    canvas = FrameCanvas(doc)
    qtbot.addWidget(canvas)
    canvas.set_preview(preview)
    doc.apply(doc.state.with_(crop=CropRect(5, 5, 20, 10), size=OutputSize(10, 5)), "geo")
    doc.set_current_index(3)
    assert _px(canvas)[0] == (40, 30)  # off: the source frame

    preview.geometry_enabled = True
    qtbot.waitUntil(lambda: _px(canvas)[0] == (10, 5), timeout=5000)
    assert canvas.geometry_preview
    assert canvas.image_rect().size().toSize().width() == 10  # scene = output image
    assert _px(canvas)[1] == PALETTE[3]

    doc.set_current_index(5)  # follows the playhead while on
    qtbot.waitUntil(lambda: _px(canvas)[1] == PALETTE[5], timeout=5000)

    preview.geometry_enabled = False  # back to the source frame, immediately
    assert _px(canvas)[0] == (40, 30) and not canvas.geometry_preview


def test_canvas_geometry_follows_crop_edits(qtbot, doc, preview):
    canvas = FrameCanvas(doc)
    qtbot.addWidget(canvas)
    canvas.set_preview(preview)
    preview.geometry_enabled = True
    doc.apply(doc.state.with_(crop=CropRect(0, 0, 12, 8)), "crop")
    qtbot.waitUntil(lambda: _px(canvas)[0] == (12, 8), timeout=5000)
    doc.undo_stack.undo()
    qtbot.waitUntil(lambda: _px(canvas)[0] == (40, 30), timeout=5000)


# ------------------------------------------------------------ settings panel
def test_format_bytes():
    assert format_bytes(850) == "850 B"
    assert format_bytes(12_700) == "12.4 KB"
    assert format_bytes(3_365_000) == "3.21 MB"


def test_summary_shows_size_estimate(qtbot, doc, preview):
    panel = SettingsPanel(doc, preview=preview)
    qtbot.addWidget(panel)
    preview.refresh_estimate()
    qtbot.waitUntil(lambda: preview.estimated_bytes is not None, timeout=5000)
    qtbot.waitUntil(lambda: "\u2248" in panel.summary_label.text(), timeout=2000)
    assert "Size:" in panel.summary_label.text()


def test_summary_without_preview_has_no_size_line(qtbot, doc):
    panel = SettingsPanel(doc)
    qtbot.addWidget(panel)
    assert "Size:" not in panel.summary_label.text()


def test_crop_panel_is_part_of_settings(qtbot, doc):
    panel = SettingsPanel(doc)
    qtbot.addWidget(panel)
    panel.crop_panel.crop_group.setChecked(True)
    assert doc.state.crop is not None
    # The output size follows the crop (size=None), visible in the summary card.
    c = doc.state.crop
    assert f"{c.w}\u00d7{c.h}" in panel.summary_label.text()


def test_crop_error_surfaces_in_summary(qtbot, doc):
    panel = SettingsPanel(doc)
    qtbot.addWidget(panel)
    panel.crop_panel.errorOccurred.emit("crop exceeds canvas")
    assert "crop exceeds canvas" in panel.summary_label.text()


# --------------------------------------------------------------- main window
@pytest.fixture
def win(qtbot, gif_path):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1100, 700)
    w.show()
    qtbot.waitExposed(w)
    w.open_file(gif_path)
    qtbot.waitUntil(lambda: w.doc.is_open and not w.is_busy, timeout=10000)
    yield w
    w.preview.dispose()


def test_crop_tool_starts_off_and_activates_a_box(win):
    assert not win.act_crop_tool.isChecked() and not win.crop_item.isVisible()
    win.act_crop_tool.trigger()
    assert win.crop_item.isVisible()
    assert win.doc.state.crop == CropRect(4, 3, 32, 24)  # 10% inset of 40x30
    assert win.doc.undo_stack.count() == 1


def test_crop_from_panel_turns_the_tool_on(win):
    win.settings.crop_panel.crop_group.setChecked(True)
    assert win.doc.state.crop is not None
    assert win.act_crop_tool.isChecked() and win.crop_item.isVisible()


def test_drag_on_canvas_crops_in_one_undo_step(qtbot, win):
    from PySide6.QtCore import QPoint, QPointF, Qt

    win.act_crop_tool.trigger()  # crop (4,3,32,24), 1 undo step
    canvas = win.inspector.canvas
    canvas.set_zoom(8)
    canvas.centerOn(20, 15)
    vp = canvas.viewport()

    def at(x, y):
        return canvas.mapFromScene(QPointF(x, y))

    start = at(20, 15)  # interior: move
    qtbot.mousePress(vp, Qt.MouseButton.LeftButton, pos=start)
    for k in range(1, 4):
        qtbot.mouseMove(vp, start + QPoint(8 * k, 0))
        assert win.doc.state.crop == CropRect(4, 3, 32, 24)  # untouched mid-drag
    qtbot.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=start + QPoint(24, 0))
    assert win.doc.state.crop == CropRect(7, 3, 32, 24)  # 24 view px / zoom 8 = 3 px
    assert win.doc.undo_stack.count() == 2
    # The panel followed the canvas.
    assert win.settings.crop_panel.x_spin.value() == 7
    win.act_undo.trigger()
    assert win.doc.state.crop == CropRect(4, 3, 32, 24)


def test_nudge_and_resize_shortcuts(qtbot, win):
    win.act_crop_tool.trigger()
    win.act_crop_nudge[1].trigger()  # right
    win.act_crop_resize[1].trigger()  # widen
    c = win.doc.state.crop
    assert (c.x, c.w) == (5, 33)
    assert win.doc.undo_stack.count() == 3  # activate + 2 discrete steps


def test_crop_edit_actions_follow_visibility(win):
    """Nudge/resize are only enabled while the rectangle is shown."""
    assert not win.crop_item.isVisible()
    assert not any(a.isEnabled() for a in win.act_crop_nudge + win.act_crop_resize)
    win.act_crop_tool.trigger()
    assert all(a.isEnabled() for a in win.act_crop_nudge + win.act_crop_resize)
    win.act_preview.trigger()  # rectangle hidden during output preview
    assert not any(a.isEnabled() for a in win.act_crop_nudge)
    win.act_preview.trigger()
    assert win.act_crop_nudge[0].isEnabled()


def test_remove_crop_works_with_tool_off(win):
    win.settings.crop_panel.crop_group.setChecked(True)  # crop set from the panel
    win.act_crop_tool.setChecked(False)  # user hides the rectangle
    assert win.doc.state.crop is not None and not win.crop_item.isVisible()
    win.act_crop_reset.trigger()
    assert win.doc.state.crop is None


def test_remove_crop_works_during_preview(win):
    win.act_crop_tool.trigger()
    win.act_preview.trigger()
    win.act_crop_reset.trigger()
    assert win.doc.state.crop is None


def test_crop_tool_hidden_during_output_preview(win):
    win.act_crop_tool.trigger()
    assert win.crop_item.isVisible()
    win.act_preview.trigger()
    assert not win.crop_item.isVisible()  # the shown image is already cropped
    win.act_preview.trigger()
    assert win.crop_item.isVisible()


def test_remove_crop_and_new_file_resets_tool(qtbot, win, tmp_path):
    from gifgen import make_gif, solid_frames

    win.act_crop_tool.trigger()
    win.act_crop_reset.trigger()
    assert win.doc.state.crop is None
    other = make_gif(tmp_path / "o.gif", solid_frames(3, (20, 20)), 100)
    win.open_file(other)
    qtbot.waitUntil(lambda: win.doc.path == other and not win.is_busy, timeout=10000)
    assert not win.act_crop_tool.isChecked() and not win.crop_item.isVisible()


def test_generate_applies_canvas_crop(qtbot, win, tmp_path):
    from PIL import Image

    win.act_crop_tool.trigger()
    out = tmp_path / "c.gif"
    win.generate_to(out)
    qtbot.waitUntil(lambda: win.last_result is not None, timeout=15000)
    with Image.open(out) as im:
        assert im.size == (32, 24)


def test_preview_edits_toggles_geometry(qtbot, gif_path):
    w = MainWindow()
    qtbot.addWidget(w)
    w.open_file(gif_path)
    qtbot.waitUntil(lambda: w.doc.is_open and not w.is_busy, timeout=10000)
    w.doc.apply(w.doc.state.with_(crop=CropRect(0, 0, 16, 12)), "crop")
    w.act_preview.trigger()
    assert w.player.preview_edits and w.preview.geometry_enabled
    qtbot.waitUntil(lambda: _px(w.inspector.canvas)[0] == (16, 12), timeout=5000)
    w.act_preview.trigger()
    assert not w.preview.geometry_enabled
    assert _px(w.inspector.canvas)[0] == (40, 30)
    qtbot.waitUntil(lambda: w.preview.estimated_bytes is not None, timeout=5000)
    w.preview.dispose()
