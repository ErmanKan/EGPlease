"""Tests for the [DIAG] crash-investigation switches and smoke_build's diagnostic variants.

The packaged Windows build crashes (0xC0000005) in the offscreen GUI smoke step. The
diagnostics rerun that step with one suspect switched off at a time; these tests make sure
each switch really changes what it claims to, so a clean run under a switch means
something.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QStyle

from gif_editor.ui.inspector.player import Player
from gif_editor.ui.inspector.transport import TransportBar

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import smoke_build  # noqa: E402


def test_std_icons_switch_uses_qt_standard_icons(doc, qtbot, monkeypatch):
    monkeypatch.setenv("GIF_EDITOR_DIAG_STD_ICONS", "1")
    bar = TransportBar(doc, Player(doc))
    qtbot.addWidget(bar)
    want = bar.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward)
    got = bar.first_button.icon()
    assert not got.isNull()
    assert got.pixmap(16, 16).toImage() == want.pixmap(16, 16).toImage()
    bar._on_playing_changed(True)  # the play/pause swap follows the switch too
    pause = bar.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
    assert bar.play_button.icon().pixmap(16, 16).toImage() == pause.pixmap(16, 16).toImage()


def test_without_switch_icons_are_the_theme_ones(doc, qtbot, monkeypatch):
    monkeypatch.delenv("GIF_EDITOR_DIAG_STD_ICONS", raising=False)
    bar = TransportBar(doc, Player(doc))
    qtbot.addWidget(bar)
    std = bar.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward)
    assert bar.first_button.icon().pixmap(16, 16).toImage() != std.pixmap(16, 16).toImage()


def test_diag_variants_switch_one_suspect_each(tmp_path):
    src = tmp_path / "in.gif"
    variants = smoke_build.diag_variants(src)
    labels = [v[0] for v in variants]
    assert labels[0].startswith("offscreen + file")
    by_env = {k: v for _label, _args, _plat, env in variants for k, v in env.items()}
    assert by_env == {"GIF_EDITOR_DIAG_QT_ARGV": "program", "GIF_EDITOR_DIAG_STD_ICONS": "1"}
    for _label, args, platform, env in variants:
        assert args[0] == "--smoke-gui"
        assert len(env) <= 1  # one variable changed per variant
        if platform is None:
            assert sys.platform == "win32"  # the native variant only exists on Windows


def test_find_cdb_returns_none_or_an_existing_file():
    found = smoke_build.find_cdb()
    assert found is None or found.exists()
