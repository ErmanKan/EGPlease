import pytest

from gif_editor.core.models import CropRect, EditState
from gif_editor.ui.document import Document


def test_open_resets_everything(doc, qtbot):
    assert doc.is_open and doc.meta.frame_count == 8
    assert doc.state == EditState() and doc.current_index == 0
    assert doc.summary().frame_count == 8


def test_apply_undo_redo(doc, qtbot):
    seen = []
    doc.stateChanged.connect(seen.append)
    doc.apply(doc.state.with_(speed=2.0), "Speed")
    assert doc.state.speed == 2.0 and seen[-1].speed == 2.0
    doc.undo_stack.undo()
    assert doc.state.speed == 1.0
    doc.undo_stack.redo()
    assert doc.state.speed == 2.0


def test_noop_apply_pushes_nothing(doc):
    doc.apply(doc.state, "nothing")
    assert doc.undo_stack.count() == 0


def test_invalid_state_rejected(doc):
    with pytest.raises(ValueError):
        doc.apply(doc.state.with_(crop=CropRect(0, 0, 41, 30)), "bad crop")
    assert doc.undo_stack.count() == 0


def test_merge_key_collapses_gesture(doc):
    for start in (100, 200, 300):
        doc.set_trim(start, None)
    assert doc.undo_stack.count() == 1 and doc.state.trim_start_ms == 300
    doc.undo_stack.undo()
    assert doc.state.trim_start_ms == 0


def test_gesture_back_to_start_is_dropped(doc):
    doc.set_trim(100, None)
    doc.set_trim(0, None)
    assert doc.undo_stack.count() == 0


def test_delete_restore(doc):
    doc.delete_frames({1, 2})
    assert doc.state.deleted == {1, 2} and doc.summary().frame_count == 6
    doc.restore_frames({2})
    assert doc.state.deleted == {1}
    doc.undo_stack.undo()
    assert doc.state.deleted == {1, 2}
    with pytest.raises(ValueError):
        doc.delete_frames(range(8))


def test_current_index_clamped_and_signalled(doc, qtbot):
    with qtbot.waitSignal(doc.currentIndexChanged) as blocker:
        doc.set_current_index(99)
    assert blocker.args == [7] and doc.current_index == 7
    doc.set_current_index(-5)
    assert doc.current_index == 0


def test_selection(doc, qtbot):
    with qtbot.waitSignal(doc.selectionChanged):
        doc.set_selection([3, 4])
    assert doc.selection == {3, 4}


def test_frame_start_ms(doc):
    assert doc.frame_start_ms(3) == 300


def test_closed_document(qtbot):
    d = Document()
    assert d.plan() is None and d.summary() is None and not d.is_open
    d.set_current_index(3)
    assert d.current_index == 0
