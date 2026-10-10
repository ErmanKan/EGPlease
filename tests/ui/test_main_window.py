"""Integration tests: the whole window, driven the way a user would (actions, shortcuts,
drag-and-drop), with real decoding and real Generate in background threads."""

import pytest
from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from gif_editor.core.encoder import read_back
from gif_editor.core.models import CropRect
from gif_editor.ui.main_window import MainWindow
from gifgen import PALETTE, make_gif, solid_frames


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    yield w
    qtbot.waitUntil(lambda: not w.is_busy, timeout=10000)


def _open(qtbot, w, path):
    w.open_file(path)
    qtbot.waitUntil(lambda: w.doc.is_open and not w.is_busy, timeout=10000)


def test_starts_empty_with_doc_actions_disabled(win):
    assert not win.doc.is_open and win.windowTitle() == "GIF Editor"
    assert win.act_open.isEnabled() and not win.act_generate.isEnabled()
    assert not win.settings.generate_button.isEnabled()


def test_open_file_async(qtbot, win, gif_path):
    _open(qtbot, win, gif_path)
    assert win.doc.meta.frame_count == 8
    assert win.windowTitle().startswith("in.gif")
    assert win.act_generate.isEnabled() and win.act_play.isEnabled()
    assert "8 frames" in win.statusBar().currentMessage()


def test_open_bad_file_reports_error(qtbot, win, tmp_path):
    bad = tmp_path / "bad.gif"
    bad.write_bytes(b"not a gif at all")
    win.open_file(bad)
    qtbot.waitUntil(lambda: win.last_error is not None, timeout=5000)
    assert "bad.gif" in win.last_error and not win.doc.is_open
    assert win.act_open.isEnabled()


def test_drop_gif_opens_it(qtbot, win, gif_path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(gif_path))])
    ev = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )  # fmt: skip
    win.dropEvent(ev)
    qtbot.waitUntil(lambda: win.doc.is_open and not win.is_busy, timeout=10000)
    assert win.doc.path == gif_path


def test_navigation_and_delete_via_actions(qtbot, win, gif_path):
    _open(qtbot, win, gif_path)
    win.act_next.trigger()
    win.act_next.trigger()
    assert win.doc.current_index == 2
    win.act_last.trigger()
    assert win.doc.current_index == 7
    win.act_first.trigger()
    win.act_next10.trigger()  # wraps within 8 frames
    assert win.doc.current_index == 10 % 8
    win.doc.set_selection({1, 3})
    win.act_delete.trigger()
    assert win.doc.state.deleted == {1, 3}
    win.act_undo.trigger()
    assert win.doc.state.deleted == frozenset()
    win.act_redo.trigger()
    assert win.doc.state.deleted == {1, 3}


def test_keyboard_shortcut_reaches_action(qtbot, win, gif_path):
    _open(qtbot, win, gif_path)
    win.inspector.canvas.setFocus()
    qtbot.keyClick(win.inspector.canvas, Qt.Key.Key_Right)
    assert win.doc.current_index == 1
    qtbot.keyClick(win.inspector.canvas, Qt.Key.Key_End)
    assert win.doc.current_index == 7


def test_trim_in_out_at_playhead(qtbot, win, gif_path):
    _open(qtbot, win, gif_path)
    win.doc.set_current_index(2)
    win.act_trim_in.trigger()
    assert (win.doc.state.trim_start_ms, win.doc.state.trim_duration_ms) == (200, None)
    win.doc.set_current_index(5)
    win.act_trim_out.trigger()
    assert (win.doc.state.trim_start_ms, win.doc.state.trim_duration_ms) == (200, 400)
    assert win.doc.summary().frame_count == 4
    win.doc.set_current_index(1)
    win.act_trim_out.trigger()  # before the start: refused
    assert win.last_error and win.doc.state.trim_duration_ms == 400
    win.act_trim_reset.trigger()
    assert (win.doc.state.trim_start_ms, win.doc.state.trim_duration_ms) == (0, None)
    assert win.doc.undo_stack.count() == 3


def test_generate_writes_edited_gif(qtbot, win, gif_path, tmp_path):
    _open(qtbot, win, gif_path)
    win.doc.delete_frames({0, 7})
    win.doc.apply(win.doc.state.with_(speed=2.0), "speed")
    out = tmp_path / "out.gif"
    win.generate_to(out)
    assert win.is_busy and not win.act_generate.isEnabled()
    qtbot.waitUntil(lambda: win.last_result is not None, timeout=15000)
    assert read_back(out) == (6, [50] * 6)
    assert win.last_result.frame_count == 6 and "Saved out.gif" in win.statusBar().currentMessage()
    assert win.act_generate.isEnabled()


def test_generate_cancel_leaves_nothing(qtbot, win, tmp_path):
    big = make_gif(tmp_path / "big.gif", solid_frames(200, (300, 200)), 50)
    _open(qtbot, win, big)
    out = tmp_path / "out.gif"
    win.generate_to(out)
    win.cancel_generate()
    qtbot.waitUntil(lambda: not win.is_busy, timeout=15000)
    if win.last_result is None:  # cancelled before finishing (the normal case)
        assert not out.exists()
        assert "cancelled" in win.statusBar().currentMessage().lower()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_save_frame_png(qtbot, win, gif_path, tmp_path):
    _open(qtbot, win, gif_path)
    win.doc.set_current_index(3)
    p = win.save_frame_to(tmp_path / "f.png")
    with Image.open(p) as im:
        assert im.size == (40, 30) and im.convert("RGB").getpixel((0, 0)) == PALETTE[3]
    win.doc.apply(win.doc.state.with_(crop=CropRect(0, 0, 10, 10)), "crop")
    p2 = win.save_frame_to(tmp_path / "g.png", with_edits=True)
    with Image.open(p2) as im:
        assert im.size == (10, 10)


def test_preview_action_bound_to_player(qtbot, win, gif_path):
    _open(qtbot, win, gif_path)
    win.act_preview.trigger()
    assert win.player.preview_edits and win.inspector.transport.preview_check.isChecked()
    win.inspector.transport.preview_check.setChecked(False)
    assert not win.act_preview.isChecked()


def test_play_pause_and_close(qtbot, win, gif_path):
    _open(qtbot, win, gif_path)
    win.act_play.trigger()
    assert win.player.is_playing
    qtbot.waitUntil(lambda: win.doc.current_index > 0, timeout=3000)
    win.act_play.trigger()
    assert not win.player.is_playing
    win.act_close.trigger()
    assert not win.doc.is_open and not win.act_generate.isEnabled()
    assert win.windowTitle() == "GIF Editor"


def test_reopen_replaces_document(qtbot, win, gif_path, tmp_path):
    _open(qtbot, win, gif_path)
    win.doc.delete_frames({2})
    other = make_gif(tmp_path / "other.gif", solid_frames(3, (20, 20)), 100)
    _open(qtbot, win, other)
    qtbot.waitUntil(lambda: win.doc.path == other, timeout=5000)
    assert win.doc.meta.frame_count == 3 and win.doc.state.deleted == frozenset()
    assert win.doc.undo_stack.count() == 0
    assert win.inspector.filmstrip.model().rowCount() == 3


def test_app_main_runs_selftest_and_window(qtbot, monkeypatch, gif_path):
    from gif_editor import app as app_mod

    created = {}

    def fake_exec():
        created["windows"] = [
            w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()
        ]
        return 0

    monkeypatch.setattr(QApplication, "exec", staticmethod(fake_exec))
    assert app_mod.main(["gif-editor"]) == 0
    assert created["windows"]
    for w in created["windows"]:
        w.close()
