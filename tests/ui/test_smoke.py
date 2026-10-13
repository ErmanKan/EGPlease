"""Qt smoke test: the toolkit loads headlessly and widgets render."""

from PySide6.QtWidgets import QLabel


def test_qt_renders_offscreen(qtbot):
    w = QLabel("GIF Editor")
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    img = w.grab().toImage()
    assert img.width() > 0 and img.height() > 0


def test_failed_selftest_explains_and_exits(qtbot, monkeypatch):
    """A broken build stops with a plain message (details kept) instead of misbehaving."""
    from PySide6.QtWidgets import QMessageBox

    from gif_editor import app
    from gif_editor.core import selftest

    def broken() -> None:
        raise selftest.SelfTestError("gif decoder args changed")

    shown = []

    def fake_exec(box: QMessageBox) -> int:
        shown.append((box.text(), box.informativeText(), box.detailedText()))
        return 0

    monkeypatch.setattr(selftest, "run_selftest", broken)
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    assert app.main(["gif-editor"]) == 1
    ((text, info, details),) = shown
    assert "can't start" in text and "Download it again" in info
    assert "gif decoder args changed" in details


def test_edit_spec_without_arguments_is_a_usage_error(capsys):
    """`--edit-spec` with missing arguments exits 2 and prints usage, without starting Qt."""
    from gif_editor import app

    assert app.main(["gif-editor", "--edit-spec"]) == 2
    assert "usage" in capsys.readouterr().out


def test_edit_spec_branch_runs_headless(tmp_path, capsys):
    """The packaged-build check path: app.main runs one edit and returns its exit code."""
    from gif_editor import app
    from gifgen import make_gif, solid_frames

    src = make_gif(tmp_path / "in.gif", solid_frames(4, (16, 16)), 100)
    out = tmp_path / "out.gif"
    assert app.main(["gif-editor", "--edit-spec", str(src), f"size=8x8,out={out}"]) == 0
    assert out.exists() and capsys.readouterr().out.startswith("RESULT ")


def test_smoke_gui_opens_the_file_and_quits(qtbot, tmp_path, capsys):
    """`--smoke-gui FILE` shows the real window, loads the GIF, then exits 0 by itself."""
    from gif_editor import app
    from gifgen import make_gif, solid_frames

    src = make_gif(tmp_path / "in.gif", solid_frames(5, (20, 10)), 100)
    assert app.main(["gif-editor", "--smoke-gui", str(src)]) == 0
    assert "GUI OK opened 5 frames 20x10" in capsys.readouterr().out


def test_smoke_gui_reports_a_failed_open(qtbot, tmp_path, capsys):
    from gif_editor import app

    assert app.main(["gif-editor", "--smoke-gui", str(tmp_path / "missing.gif")]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert any(ln.startswith("GUI FAIL") for ln in lines)
    # Stage markers are printed (flushed) in smoke mode, ending at the exit.
    assert lines[0] == "GUI STAGE importing Qt" and lines[-1] == "GUI STAGE exiting"


def test_smoke_gui_fails_fast_on_a_broken_selftest(qtbot, monkeypatch, capsys):
    """No modal dialog in smoke mode: a broken build must fail at once, not at a timeout."""
    from PySide6.QtWidgets import QMessageBox

    from gif_editor import app
    from gif_editor.core import selftest

    def broken() -> None:
        raise selftest.SelfTestError("gif decoder args changed")

    def must_not_block(_box):
        raise AssertionError("a modal dialog was shown in smoke mode")

    monkeypatch.setattr(selftest, "run_selftest", broken)
    monkeypatch.setattr(QMessageBox, "exec", must_not_block)
    assert app.main(["gif-editor", "--smoke-gui"]) == 1
    assert "GUI FAIL startup self-test: gif decoder args changed" in capsys.readouterr().out
