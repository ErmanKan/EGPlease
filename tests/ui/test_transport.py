"""Tests for the transport bar (``ui/inspector/transport.py``)."""

from __future__ import annotations

from PySide6.QtCore import Qt

from gif_editor.ui.document import Document
from gif_editor.ui.inspector.player import Player
from gif_editor.ui.inspector.transport import EMPTY_TEXT, TransportBar, format_frame_info


def make(doc, qtbot):
    player = Player(doc, time_scale=0.2)
    bar = TransportBar(doc, player)
    qtbot.addWidget(bar)
    return bar, player


def test_format_frame_info():
    assert format_frame_info(36, 120, 1480, 40, False) == "Frame 37 / 120 · 1.48 s · 40 ms"
    assert format_frame_info(0, 1, 0, 100, True) == "Frame 1 / 1 · 0.00 s · 100 ms · deleted"


def test_label_follows_current_index_and_deletion(doc, qtbot):
    bar, _ = make(doc, qtbot)
    assert bar.info_label.text() == "Frame 1 / 8 · 0.00 s · 100 ms"
    doc.set_current_index(3)
    assert bar.info_label.text() == "Frame 4 / 8 · 0.30 s · 100 ms"
    doc.delete_frames({3})
    assert bar.info_label.text().endswith(" · deleted")
    doc.undo_stack.undo()
    assert not bar.info_label.text().endswith("deleted")


def test_play_button_reflects_playing(doc, qtbot):
    bar, player = make(doc, qtbot)
    assert not bar.play_button.isChecked()
    qtbot.mouseClick(bar.play_button, Qt.MouseButton.LeftButton)
    assert player.is_playing and bar.play_button.isChecked()
    player.pause()
    assert not bar.play_button.isChecked()
    player.play()
    assert bar.play_button.isChecked()
    qtbot.mouseClick(bar.play_button, Qt.MouseButton.LeftButton)
    assert not player.is_playing and not bar.play_button.isChecked()


def test_play_button_unchecks_on_empty_plan(doc, qtbot):
    bar, player = make(doc, qtbot)
    doc.apply(doc.state.with_(trim_start_ms=10_000), "trim past end")
    bar.preview_check.setChecked(True)
    qtbot.mouseClick(bar.play_button, Qt.MouseButton.LeftButton)
    assert not player.is_playing and not bar.play_button.isChecked()


def test_buttons_move_frames(doc, qtbot):
    bar, _ = make(doc, qtbot)
    click = Qt.MouseButton.LeftButton
    qtbot.mouseClick(bar.next_button, click)
    assert doc.current_index == 1
    qtbot.mouseClick(bar.prev_button, click)
    qtbot.mouseClick(bar.prev_button, click)
    assert doc.current_index == 7  # wraps
    qtbot.mouseClick(bar.first_button, click)
    assert doc.current_index == 0
    qtbot.mouseClick(bar.last_button, click)
    assert doc.current_index == 7


def test_preview_checkbox_bound_both_ways(doc, qtbot):
    bar, player = make(doc, qtbot)
    bar.preview_check.setChecked(True)
    assert player.preview_edits
    player.preview_edits = False
    assert not bar.preview_check.isChecked()


def test_save_frame_requested(doc, qtbot):
    bar, _ = make(doc, qtbot)
    with qtbot.waitSignal(bar.saveFrameRequested):
        qtbot.mouseClick(bar.save_button, Qt.MouseButton.LeftButton)


def test_tooltips_name_shortcuts(doc, qtbot):
    bar, _ = make(doc, qtbot)
    for button, key in [
        (bar.first_button, "Home"),
        (bar.prev_button, "Left"),
        (bar.play_button, "Space"),
        (bar.next_button, "Right"),
        (bar.last_button, "End"),
    ]:
        assert key in button.toolTip()


def test_disabled_without_source(qtbot):
    doc = Document()
    bar, _ = make(doc, qtbot)
    assert not bar.isEnabled()
    for w in (bar.play_button, bar.next_button, bar.preview_check, bar.save_button):
        assert not w.isEnabled()
    assert bar.info_label.text() == EMPTY_TEXT


def test_close_disables_and_resets(doc, qtbot):
    bar, player = make(doc, qtbot)
    assert bar.save_button.isEnabled()
    player.play()
    doc.close()
    assert not bar.isEnabled()
    assert bar.info_label.text() == EMPTY_TEXT
    assert not bar.play_button.isChecked()
