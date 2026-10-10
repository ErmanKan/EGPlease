"""Tests for ui/inspector/filmstrip.py (model, view syncing, keys, context menu)."""

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage, QPixmap

from gif_editor.ui.document import Document
from gif_editor.ui.inspector.filmstrip import Filmstrip, FrameListModel
from gifgen import PALETTE

DR = FrameListModel.DeletedRole
TR = FrameListModel.InTrimRole


@pytest.fixture
def strip(qtbot, doc):
    w = Filmstrip(doc)
    qtbot.addWidget(w)
    w.resize(600, 140)
    w.show()
    yield w
    # pytest-qt has already close()d + deleteLater()ed the widget at this point, so do
    # not poll the model; just let in-flight thumbnail jobs finish before the doc
    # fixture closes the source.
    QThreadPool.globalInstance().waitForDone(5000)


def _select(strip, rows):
    sm = strip.selectionModel()
    sm.clearSelection()
    for r in rows:
        sm.select(strip.model().index(r), QItemSelectionModel.SelectionFlag.Select)


def _actions(strip, row=None):
    menu = strip.build_context_menu(row)
    return {a.text(): a for a in menu.actions() if a.text()}


def test_row_count_and_roles(strip, doc):
    m = strip.model()
    assert m.rowCount() == doc.meta.frame_count == 8
    assert m.data(m.index(2)) == "#3\n100 ms"
    tip = m.data(m.index(2), Qt.ItemDataRole.ToolTipRole)
    assert tip == "Frame 3 · starts 0.20 s · delay 100 ms"
    assert m.data(m.index(0), DR) is False and m.data(m.index(0), TR) is True
    assert strip.accessibleName() == "Frame strip"


def test_thumbnails_load(qtbot, strip):
    m = strip.frame_model
    m.data(m.index(1), Qt.ItemDataRole.DecorationRole)  # ask like a paint would

    def loaded():
        pm = m.data(m.index(1), Qt.ItemDataRole.DecorationRole)
        return m.has_thumbnail(1) and pm.toImage().pixelColor(5, 5) == QColor(*PALETTE[1])

    qtbot.waitUntil(loaded, timeout=5000)
    pm = m.data(m.index(1), Qt.ItemDataRole.DecorationRole)
    assert (pm.width(), pm.height()) == (40, 30)


def test_placeholder_has_aspect_ratio(strip):
    pm = strip.frame_model.placeholder()
    assert (pm.width(), pm.height()) == (40, 30)


def test_selection_syncs_to_doc(strip, doc):
    _select(strip, [1, 3])
    assert doc.selection == frozenset({1, 3})
    doc.set_selection({4})
    assert {i.row() for i in strip.selectionModel().selectedIndexes()} == {4}


def test_current_index_syncs_both_ways(strip, doc):
    doc.set_current_index(5)
    assert strip.currentIndex().row() == 5
    strip.setCurrentIndex(strip.model().index(2))
    assert doc.current_index == 2


def test_delete_key_one_undo_step(qtbot, strip, doc):
    _select(strip, [1, 2])
    qtbot.keyClick(strip, Qt.Key.Key_Delete)
    assert doc.state.deleted == frozenset({1, 2})
    assert doc.undo_stack.count() == 1
    m = strip.model()
    assert m.data(m.index(1), DR) and m.data(m.index(2), DR) and not m.data(m.index(0), DR)
    assert "deleted" in m.data(m.index(1), Qt.ItemDataRole.ToolTipRole)
    doc.undo_stack.undo()
    assert doc.state.deleted == frozenset()


def test_backspace_and_restore_keys(qtbot, strip, doc):
    _select(strip, [3])
    qtbot.keyClick(strip, Qt.Key.Key_Backspace)
    assert doc.state.deleted == frozenset({3})
    ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    qtbot.keyClick(strip, Qt.Key.Key_Delete, ctrl_shift)
    assert doc.state.deleted == frozenset()
    qtbot.keyClick(strip, Qt.Key.Key_Delete)
    qtbot.keyClick(strip, Qt.Key.Key_Insert)
    assert doc.state.deleted == frozenset()


def test_delete_all_emits_error(qtbot, strip, doc):
    strip.selectAll()
    before = doc.state
    with qtbot.waitSignal(strip.errorOccurred, timeout=1000) as sig:
        qtbot.keyClick(strip, Qt.Key.Key_Delete)
    assert "every frame" in sig.args[0]
    assert doc.state == before and doc.undo_stack.count() == 0


def test_context_menu_delete_restore_select_all(strip, doc):
    _select(strip, [0])
    acts = _actions(strip)
    assert acts["Delete frame(s)"].isEnabled() and not acts["Restore frame(s)"].isEnabled()
    acts["Delete frame(s)"].trigger()
    assert doc.state.deleted == frozenset({0})
    acts = _actions(strip)
    assert not acts["Delete frame(s)"].isEnabled() and acts["Restore frame(s)"].isEnabled()
    acts["Restore frame(s)"].trigger()
    assert doc.state.deleted == frozenset()
    _actions(strip)["Select all"].trigger()
    assert doc.selection == frozenset(range(8))


def test_context_menu_trim(strip, doc):
    _actions(strip, 2)["Set trim start here"].trigger()
    assert (doc.state.trim_start_ms, doc.state.trim_duration_ms) == (200, None)
    _actions(strip, 5)["Set trim end here"].trigger()
    assert (doc.state.trim_start_ms, doc.state.trim_duration_ms) == (200, 400)
    assert doc.undo_stack.count() == 2  # merge_key=None: separate steps
    m = strip.model()
    assert [m.data(m.index(r), TR) for r in range(8)] == [
        False, False, True, True, True, True, False, False
    ]  # fmt: skip
    assert "outside trim" in m.data(m.index(0), Qt.ItemDataRole.ToolTipRole)
    # Moving the start keeps the end fixed; trimming the end at the last frame -> None.
    _actions(strip, 3)["Set trim start here"].trigger()
    assert (doc.state.trim_start_ms, doc.state.trim_duration_ms) == (300, 300)
    _actions(strip, 7)["Set trim end here"].trigger()
    assert doc.state.trim_duration_ms is None


def test_trim_end_before_start_emits_error(qtbot, strip, doc):
    doc.set_trim(500, None, merge_key=None)
    with qtbot.waitSignal(strip.errorOccurred, timeout=1000):
        _actions(strip, 1)["Set trim end here"].trigger()
    assert doc.state.trim_start_ms == 500 and doc.state.trim_duration_ms is None


def test_in_trim_role_false_outside_trim(strip, doc):
    doc.set_trim(250, 300, merge_key=None)  # window [250, 550): frames 2..5 visible
    m = strip.model()
    assert [r for r in range(8) if m.data(m.index(r), TR)] == [2, 3, 4, 5]


def test_stale_thumbnail_result_ignored(qtbot, strip, doc, gif_path):
    m = strip.frame_model
    old = m.generation
    from gif_editor.core.decoder import GifSource

    doc.set_source(GifSource.open(gif_path), gif_path)  # sourceChanged
    assert m.generation == old + 1
    img = QImage(40, 30, QImage.Format.Format_RGBA8888)
    img.fill(QColor(1, 2, 3))
    m.on_thumbnails_loaded(old, [(0, img)])
    assert not m.has_thumbnail(0)
    pm = m.data(m.index(0), Qt.ItemDataRole.DecorationRole)
    assert pm.toImage().pixelColor(0, 0) != QColor(1, 2, 3)
    # The current generation is accepted.
    m.on_thumbnails_loaded(m.generation, [(0, img)])
    assert m.has_thumbnail(0)


def test_empty_doc(qtbot):
    d = Document()
    w = Filmstrip(d)
    qtbot.addWidget(w)
    w.show()
    assert w.model().rowCount() == 0 and not w.isEnabled()
    assert w.model().data(w.model().index(0)) is None
    acts = _actions(w)
    assert not any(a.isEnabled() for a in acts.values())
    w.delete_selected()
    w.restore_selected()
    qtbot.keyClick(w, Qt.Key.Key_Delete)
    w.grab()  # paints without crashing
    assert isinstance(w.frame_model.placeholder(), QPixmap)


def test_close_resets_rows(qtbot, strip, doc):
    doc.close()
    assert strip.model().rowCount() == 0 and not strip.isEnabled()


def test_paints_all_states(qtbot, strip, doc):
    doc.delete_frames({1})
    doc.set_trim(300, None, merge_key=None)
    doc.set_current_index(4)
    img = strip.grab().toImage()
    assert not img.isNull()
