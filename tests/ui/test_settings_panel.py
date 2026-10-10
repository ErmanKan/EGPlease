"""Tests for the left settings panel (ui/settings_panel.py).

The ``doc`` fixture is an open Document over 8 solid frames, 40x30, 100 ms each.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from gif_editor.core.models import CropRect, EditState, OutputSize, Quality
from gif_editor.ui.document import Document
from gif_editor.ui.settings_panel import TIMES, SettingsPanel


@pytest.fixture
def panel(qtbot, doc):
    p = SettingsPanel(doc)
    qtbot.addWidget(p)
    return p


def test_initial_values_reflect_default_state(panel, doc):
    st = EditState()
    assert panel.start_spin.value() == 0.0
    assert panel.to_end_check.isChecked()
    assert not panel.duration_spin.isEnabled()
    assert panel.duration_spin.value() == pytest.approx(0.8)
    assert panel.speed_spin.value() == st.speed
    assert panel.speed_slider.value() == 100
    assert not panel.fps_check.isChecked()
    assert not panel.fps_spin.isEnabled()
    assert (panel.width_spin.value(), panel.height_spin.value()) == (40, 30)
    assert panel.scale_spin.value() == 100
    assert panel.lock_check.isChecked()
    assert panel.colors_spin.value() == 256
    assert panel.dither_check.isChecked()
    assert panel.preset_combo.currentText() == "High"
    assert panel.timing_group.isEnabled()
    assert panel.sizeHint().width() == 280


def test_speed_changes_merge_into_one_undo_step(panel, doc):
    for v in (1.05, 1.10, 1.5, 2.0):
        panel.speed_spin.setValue(v)
    assert doc.state.speed == 2.0
    assert doc.undo_stack.count() == 1
    assert panel.speed_slider.value() == 200


def test_speed_slider_syncs_spinbox(panel, doc):
    panel.speed_slider.setValue(50)
    assert doc.state.speed == 0.5
    assert panel.speed_spin.value() == 0.5


def test_undo_restores_controls_without_new_commands(panel, doc):
    panel.speed_spin.setValue(2.0)
    panel.fps_check.setChecked(True)
    assert doc.undo_stack.count() == 2
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert doc.state == EditState()
    assert panel.speed_spin.value() == 1.0
    assert panel.speed_slider.value() == 100
    assert not panel.fps_check.isChecked()
    # Refreshing must not have pushed anything: the redo history is intact.
    assert doc.undo_stack.count() == 2
    assert doc.undo_stack.index() == 0


def test_to_end_toggles_duration_none(panel, doc):
    panel.to_end_check.setChecked(False)
    assert doc.state.trim_duration_ms == 800
    assert panel.duration_spin.isEnabled()
    panel.duration_spin.setValue(0.3)
    assert doc.state.trim_duration_ms == 300
    panel.to_end_check.setChecked(True)
    assert doc.state.trim_duration_ms is None
    assert not panel.duration_spin.isEnabled()


def test_start_time_and_duration_clamped(panel, doc):
    panel.start_spin.setValue(0.5)
    assert doc.state.trim_start_ms == 500
    panel.to_end_check.setChecked(False)
    panel.duration_spin.setValue(0.8)  # too long for what's left: clamped, not an error
    assert doc.state.trim_duration_ms == 300
    assert panel.duration_spin.value() == pytest.approx(0.3)


def test_fps_checkbox_maps_to_none_or_value(panel, doc):
    panel.fps_spin.setValue(5.0)  # disabled spin: no state change yet
    assert doc.state.fps is None
    panel.fps_check.setChecked(True)
    assert doc.state.fps == 5.0
    panel.fps_spin.setValue(4.0)
    assert doc.state.fps == 4.0
    panel.fps_check.setChecked(False)
    assert doc.state.fps is None


def test_aspect_lock_keeps_ratio(panel, doc):
    panel.width_spin.setValue(80)
    assert doc.state.size == OutputSize(80, 60)
    assert panel.height_spin.value() == 60
    assert panel.scale_spin.value() == 200
    panel.height_spin.setValue(15)
    assert doc.state.size == OutputSize(20, 15)


def test_aspect_unlocked_changes_one_side(panel, doc):
    panel.lock_check.setChecked(False)
    panel.width_spin.setValue(10)
    assert doc.state.size == OutputSize(10, 30)


def test_aspect_uses_crop_as_base(panel, doc):
    doc.apply(doc.state.with_(crop=CropRect(0, 0, 20, 20)), "crop")
    assert (panel.width_spin.value(), panel.height_spin.value()) == (20, 20)
    panel.width_spin.setValue(10)
    assert doc.state.size == OutputSize(10, 10)


def test_scale_and_reset(panel, doc):
    panel.scale_spin.setValue(50)
    assert doc.state.size == OutputSize(20, 15)
    assert panel.reset_size_button.isEnabled()
    panel.reset_size_button.click()
    assert doc.state.size is None
    assert (panel.width_spin.value(), panel.height_spin.value()) == (40, 30)


def test_preset_sets_quality_and_editing_switches_to_custom(panel, doc):
    panel.preset_combo.activated.emit(2)  # what a user pick emits
    assert doc.state.quality == Quality.preset("low")
    assert panel.colors_spin.value() == 64
    assert not panel.dither_check.isChecked()
    panel.colors_spin.setValue(100)
    assert doc.state.quality == Quality(100, False)
    assert panel.preset_combo.currentText() == "Custom"
    panel.colors_spin.setValue(64)  # back to a preset's values
    assert panel.preset_combo.currentText() == "Low"


def test_summary_shows_output_and_updates(panel, doc):
    text = panel.summary_label.text()
    assert f"8 frames · 0.80 s · 40{TIMES}30" in text  # source and output identical
    doc.delete_frames([0, 1, 2])
    assert "<b>Output:</b> 5 frames" in panel.summary_label.text()


def test_empty_output_disables_generate(panel, doc):
    doc.set_trim(0, 100)
    doc.delete_frames([0])
    assert "empty" in panel.summary_label.text()
    assert not panel.generate_button.isEnabled()


def test_invalid_edit_reverted_and_reported(panel, doc, monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("nope, invalid")

    monkeypatch.setattr(doc, "apply", boom)
    panel.speed_spin.setValue(3.0)
    assert panel.speed_spin.value() == 1.0
    assert "nope, invalid" in panel.summary_label.text()


def test_generate_signal(panel, doc, qtbot):
    assert panel.generate_button.isEnabled()
    with qtbot.waitSignal(panel.generateRequested, timeout=1000):
        qtbot.mouseClick(panel.generate_button, Qt.MouseButton.LeftButton)


def test_generate_disabled_after_close(panel, doc):
    doc.close()
    assert not panel.generate_button.isEnabled()
    assert not panel.timing_group.isEnabled()


def test_empty_document_everything_disabled(qtbot):
    d = Document()
    p = SettingsPanel(d)
    qtbot.addWidget(p)
    p.show()
    for w in (p.timing_group, p.size_group, p.quality_group, p.generate_button):
        assert not w.isEnabled()
    assert "No file open" in p.summary_label.text()
    p.speed_spin.setValue(2.0)  # even if forced, nothing is pushed
    assert d.undo_stack.count() == 0
