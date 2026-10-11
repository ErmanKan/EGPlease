"""Tests for the CropPanel (spec: docs/codebase/src/gif_editor/ui/crop_panel.md).

The ``doc`` fixture canvas is 40x30 (8 solid frames). A full-canvas crop normalises to
``crop=None``, so tests that want to observe a value pick something smaller.
"""

import pytest

from gif_editor.core.models import CropRect, OutputSize
from gif_editor.ui.crop_panel import ASPECTS, TIMES, CropPanel
from gif_editor.ui.document import Document


@pytest.fixture
def panel(qtbot, doc):
    p = CropPanel(doc)
    qtbot.addWidget(p)
    p.show()
    return p


def _crop(doc, x, y, w, h, key="crop"):
    """What a canvas drag does: write the crop straight to the Document."""
    doc.apply(doc.state.with_(crop=CropRect(x, y, w, h)), "Crop", merge_key=key)


def _aspect(panel, label):
    panel.aspect_combo.setCurrentIndex([a[0] for a in ASPECTS].index(label))


def _values(panel):
    return (panel.x_spin.value(), panel.y_spin.value(), panel.w_spin.value(), panel.h_spin.value())


# ------------------------------------------------------------------ initial state
def test_initial_values_no_crop(panel, doc):
    assert doc.state.crop is None
    assert not panel.crop_group.isChecked()
    assert _values(panel) == (0, 0, 40, 30)
    assert panel.aspect_combo.currentText() == "Free"
    assert panel.status_label.text() == f"No crop (full frame 40{TIMES}30)"


def test_ranges_follow_canvas(panel):
    assert (panel.x_spin.minimum(), panel.x_spin.maximum()) == (0, 39)
    assert (panel.y_spin.minimum(), panel.y_spin.maximum()) == (0, 29)
    assert (panel.w_spin.minimum(), panel.w_spin.maximum()) == (1, 40)
    assert (panel.h_spin.minimum(), panel.h_spin.maximum()) == (1, 30)
    assert panel.x_spin.suffix() == " px"
    assert panel.w_spin.accessibleName() == "Crop width"


def test_aspect_entries_and_original(panel, doc):
    labels = [panel.aspect_combo.itemText(i) for i in range(panel.aspect_combo.count())]
    assert labels == ["Free", "Original", "1:1", "4:3", "16:9", "3:2", "9:16"]
    assert panel.aspect_combo.itemData(0) is None
    assert panel.aspect_combo.itemData(1) == pytest.approx(40 / 30)
    assert panel.aspect_combo.itemData(3) == pytest.approx(4 / 3)
    doc.close()
    assert panel.aspect_combo.itemData(1) is None


# ------------------------------------------------------------- spinbox -> state
def test_x_y_edits_write_crop(panel, doc):
    panel.w_spin.setValue(20)
    panel.h_spin.setValue(15)
    panel.x_spin.setValue(10)
    panel.y_spin.setValue(7)
    assert doc.state.crop == CropRect(10, 7, 20, 15)


def test_w_edit_clamps_keeping_width(panel, doc):
    _crop(doc, 10, 0, 20, 15)
    panel.w_spin.setValue(40)
    c = doc.state.crop
    assert (c.x, c.w) == (0, 40) and c.x + c.w == 40  # origin shifted, width kept


def test_h_edit_clamps_keeping_height(panel, doc):
    _crop(doc, 0, 10, 20, 15)
    panel.h_spin.setValue(30)
    c = doc.state.crop
    assert (c.y, c.h) == (0, 30) and c.y + c.h == 30


def test_x_edit_clamped_to_right(panel, doc):
    _crop(doc, 0, 0, 30, 15)
    panel.x_spin.setValue(39)
    assert doc.state.crop.x == 10  # 40 - 30


def test_y_edit_clamped_to_bottom(panel, doc):
    _crop(doc, 0, 0, 20, 30)  # full height
    panel.y_spin.setValue(5)
    assert doc.state.crop.y == 0


def test_full_canvas_edit_normalises_to_none(panel, doc):
    _crop(doc, 0, 0, 39, 30)
    panel.w_spin.setValue(40)
    assert doc.state.crop is None


# ------------------------------------------------------------------- undo
def test_spinbox_scrub_is_one_undo_step(panel, doc):
    for w in (30, 25, 20, 18):
        panel.w_spin.setValue(w)
    assert doc.undo_stack.count() == 1
    assert doc.state.crop.w == 18


def test_button_is_its_own_undo_step(panel, doc):
    panel.w_spin.setValue(20)
    panel.full_button.click()
    assert doc.undo_stack.count() == 2


def test_undo_redo_refresh_without_new_commands(panel, doc):
    panel.w_spin.setValue(20)
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert _values(panel) == (0, 0, 40, 30) and doc.state.crop is None
    assert doc.undo_stack.count() == 1 and doc.undo_stack.index() == 0  # nothing pushed
    doc.undo_stack.redo()
    assert panel.w_spin.value() == 20 and doc.undo_stack.count() == 1


def test_canvas_drag_syncs_panel(panel, doc):
    _crop(doc, 4, 3, 12, 9, key="crop-drag-1")
    assert _values(panel) == (4, 3, 12, 9)
    assert panel.crop_group.isChecked()
    assert doc.undo_stack.count() == 1  # the refresh pushed nothing


# ------------------------------------------------------------------ aspect
def test_aspect_w_edit_updates_h(panel, doc):
    _aspect(panel, "4:3")
    panel.w_spin.setValue(20)
    assert (doc.state.crop.w, doc.state.crop.h) == (20, 15)
    _aspect(panel, "1:1")
    panel.w_spin.setValue(25)
    assert (doc.state.crop.w, doc.state.crop.h) == (25, 25)
    _aspect(panel, "9:16")
    panel.w_spin.setValue(9)
    assert (doc.state.crop.w, doc.state.crop.h) == (9, 16)


def test_aspect_h_edit_updates_w(panel, doc):
    _aspect(panel, "4:3")
    panel.h_spin.setValue(12)
    assert (doc.state.crop.w, doc.state.crop.h) == (16, 12)


def test_aspect_rounds_to_nearest_and_min_1(panel, doc):
    _aspect(panel, "16:9")
    panel.w_spin.setValue(16)
    assert doc.state.crop.h == 9
    panel.w_spin.setValue(7)
    assert doc.state.crop.h == 4  # round(3.9375)
    panel.w_spin.setValue(1)
    assert doc.state.crop.h == 1  # round(0.56) = 1, and never below 1 anyway


def test_aspect_lock_clamps_the_other_side(panel, doc):
    _aspect(panel, "9:16")
    panel.w_spin.setValue(30)  # would need h=53 > 30
    c = doc.state.crop
    assert c.h == 30 and c.y + c.h <= 30


def test_aspect_not_reapplied_on_drag(panel, doc):
    _aspect(panel, "1:1")
    _crop(doc, 0, 0, 20, 10, key="crop-drag-1")
    assert (panel.w_spin.value(), panel.h_spin.value()) == (20, 10)
    assert panel.aspect_combo.currentText() == "1:1"


# ----------------------------------------------------------------- buttons
def test_full_image_button_stores_none(panel, doc):
    _aspect(panel, "4:3")
    _crop(doc, 5, 5, 20, 15)
    panel.full_button.click()
    assert doc.state.crop is None and not panel.crop_group.isChecked()
    assert panel.aspect_combo.currentText() == "4:3"
    assert panel.status_label.text() == f"No crop (full frame 40{TIMES}30)"


def test_center_uses_current_crop_size(panel, doc):
    _crop(doc, 5, 5, 20, 15)
    panel.center_button.click()
    assert doc.state.crop == CropRect(10, 7, 20, 15)


def test_center_without_crop_uses_output_size(panel, doc):
    doc.apply(doc.state.with_(size=OutputSize(20, 20)), "size")
    panel.center_button.click()
    assert doc.state.crop == CropRect(10, 5, 20, 20)


def test_reset_clears_crop_and_combo(panel, doc):
    _aspect(panel, "16:9")
    _crop(doc, 5, 5, 20, 15)
    panel.reset_button.click()
    assert doc.state.crop is None
    assert panel.aspect_combo.currentText() == "Free"
    assert panel.status_label.text().startswith("No crop")


# ---------------------------------------------------------------- checkbox
def test_checkbox_uncheck_clears(panel, doc):
    _crop(doc, 5, 5, 20, 15)
    assert panel.crop_group.isChecked()
    panel.crop_group.setChecked(False)
    assert doc.state.crop is None


def test_checkbox_check_applies_centered_default(panel, doc):
    doc.apply(doc.state.with_(size=OutputSize(20, 20)), "size")
    panel.crop_group.setChecked(True)
    assert doc.state.crop == CropRect(10, 5, 20, 20)


def test_checkbox_check_full_size_default_still_crops(panel, doc):
    """With no size set the centred default is the full frame; checking must still crop."""
    panel.crop_group.setChecked(True)
    c = doc.state.crop
    assert c is not None and c.w < 40 and c.h < 30
    assert panel.crop_group.isChecked()


def test_inputs_greyed_until_ticked(panel, doc):
    """'Tick to crop': Qt disables a checkable group's children while it is unchecked."""
    assert not panel.crop_group.isChecked()
    assert not panel.w_spin.isEnabled()
    panel.crop_group.setChecked(True)
    assert panel.w_spin.isEnabled() and panel.center_button.isEnabled()
    panel.w_spin.setValue(20)
    assert doc.state.crop.w == 20


# ------------------------------------------------------------------ status
def test_status_line_formats(panel, doc):
    _crop(doc, 10, 7, 20, 15)
    assert panel.status_label.text() == f"Crop 20{TIMES}15 at 10,7 \u00b7 25% of the frame"
    doc.apply(doc.state.with_(crop=None), "none")
    assert panel.status_label.text() == f"No crop (full frame 40{TIMES}30)"
    doc.close()
    assert panel.status_label.text() == "No crop"


# --------------------------------------------------------------- no source
def test_disabled_without_source(qtbot):
    d = Document()
    p = CropPanel(d)
    qtbot.addWidget(p)
    assert not p.crop_group.isEnabled() and not p.crop_group.isChecked()
    for w in (p.aspect_combo, p.x_spin, p.w_spin, p.full_button, p.reset_button):
        assert not w.isEnabled()
    p.x_spin.setValue(5)  # forced: must push nothing
    assert d.undo_stack.count() == 0
    assert p.status_label.text() == "No crop"


def test_closed_document_disables(panel, doc):
    _crop(doc, 5, 5, 20, 15)
    doc.close()
    assert not panel.crop_group.isEnabled() and not panel.crop_group.isChecked()
    assert panel.status_label.text() == "No crop"


# ------------------------------------------------------------- errors etc.
def test_invalid_crop_reports_error(panel, doc, qtbot, monkeypatch):
    _crop(doc, 5, 5, 20, 15)
    real_apply = doc.apply

    def failing_apply(*_args, **_kwargs):
        raise ValueError("crop exceeds canvas")

    monkeypatch.setattr(doc, "apply", failing_apply)
    with qtbot.waitSignal(panel.errorOccurred) as sig:
        panel.w_spin.setValue(10)
    assert sig.args == ["crop exceeds canvas"]
    assert panel.last_error == "crop exceeds canvas"
    assert panel.w_spin.value() == 20  # reverted to the document
    monkeypatch.setattr(doc, "apply", real_apply)
    panel.w_spin.setValue(12)
    assert panel.last_error is None and doc.state.crop.w == 12


def test_edit_does_not_change_explicit_size(panel, doc):
    doc.apply(doc.state.with_(size=OutputSize(100, 100)), "size")
    panel.w_spin.setValue(20)
    panel.full_button.click()
    assert doc.state.size == OutputSize(100, 100)


def test_in_progress_text_not_clobbered(panel, doc):
    panel.w_spin.setFocus()
    edit = panel.w_spin.lineEdit()
    edit.setText("2")
    edit.setModified(True)
    _crop(doc, 1, 1, 10, 10, key="crop-drag-1")  # an external refresh arrives mid-typing
    if panel.w_spin.hasFocus():  # offscreen focus is best-effort; only assert when it held
        assert edit.text().startswith("2")
    assert panel.x_spin.value() == 1  # the other spinboxes did update
