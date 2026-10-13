"""Tests for scripts/check_build_flags.py: it must catch the mistakes that cost real builds.

The checker parses flags with Nuitka's own parser, so these tests also pin down Nuitka 4.3
behaviour the build relies on (plugin options exist only when the plugin is enabled).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_build_flags as cbf  # noqa: E402


def test_committed_command_lines_are_valid():
    """The flags actually shipped must pass for both platforms, in either order."""
    assert cbf.check("Linux", windows=False) == []
    assert cbf.check("Windows", windows=True) == []
    assert cbf.check("Linux", windows=False) == []  # a second fresh parser still works


@pytest.mark.parametrize(
    "bad_flag",
    [
        "--cache-dir=out/cache",  # not a Nuitka option (cost one full build)
        "--no-console",  # does not exist (cost another)
        "--onefile-tempdir-spec-typo={TEMP}",  # misspelt
        "--invented-flag=1",
    ],
)
def test_injected_bad_flag_is_rejected(monkeypatch, bad_flag):
    real = cbf.build.build_command

    def with_bad(ver, *, windows=None):
        cmd = real(ver, windows=windows)
        return [*cmd, bad_flag]

    monkeypatch.setattr(cbf.build, "build_command", with_bad)
    for windows in (False, True):
        problems = cbf.check("x", windows=windows)
        assert any(bad_flag in p for p in problems), (bad_flag, problems)


def test_windows_only_flag_must_not_reach_a_linux_build(monkeypatch):
    real = cbf.build.build_command

    def leak(ver, *, windows=None):
        cmd = real(ver, windows=windows)
        return cmd if windows else [*cmd, "--windows-icon-from-ico=x.ico"]

    monkeypatch.setattr(cbf.build, "build_command", leak)
    assert any("windows-icon-from-ico" in p for p in cbf.check("Linux", windows=False))


def test_plugin_options_need_their_plugin(monkeypatch):
    """--noinclude-qt-plugins belongs to the pyside6 plugin: without it Nuitka rejects it."""
    real = cbf.build.build_command

    def no_plugin(ver, *, windows=None):
        return [a for a in real(ver, windows=windows) if not a.startswith("--enable-plugin")]

    monkeypatch.setattr(cbf.build, "build_command", no_plugin)
    problems = cbf.check("Linux", windows=False)
    assert any("noinclude-qt-plugins" in p for p in problems), problems


def test_rejected_flags_uses_prefix_matching():
    """optparse accepts unambiguous prefixes: --enable-plugin is --enable-plugins."""
    assert cbf.rejected_flags(["--enable-plugin=pyside6", "--onefile"]) == []
