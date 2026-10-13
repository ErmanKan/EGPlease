"""Tests for scripts/check_build_flags.py: it must catch the mistakes that cost real builds."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_build_flags as cbf  # noqa: E402


@pytest.fixture(scope="module")
def known() -> set[str]:
    return cbf.known_options()


def test_committed_command_lines_are_valid(known):
    """The flags actually shipped must pass for both platforms."""
    for windows in (False, True):
        name = "Windows" if windows else "Linux"
        assert cbf.check(name, windows=windows, known=known) == []


@pytest.mark.parametrize(
    "bad_flag",
    [
        "--cache-dir={TMP}",  # not a Nuitka option at all (cost one 20-minute build)
        "--no-console",  # the Linux name that does not exist (cost another)
        "--windows-icon-from-ico=/tmp/x.ico",  # Windows-only: must not be in a Linux build
        "--invented-flag=1",  # made up
    ],
)
def test_injected_bad_flag_is_caught(known, monkeypatch, bad_flag):
    """The checker must fail on each mistake that was actually made during development."""
    real = cbf.build.build_command

    def with_bad(ver, *, windows=None):
        cmd = real(ver, windows=windows)
        # Put the bad flag in only for the platform it would be wrong on, so the case that
        # must be caught is exercised (a Linux-only leak is checked on the Linux command).
        if bad_flag.startswith("--windows-icon") and windows:
            return cmd
        return [*cmd[:-1], bad_flag, cmd[-1]]

    monkeypatch.setattr(cbf.build, "build_command", with_bad)
    problems = cbf.check("Linux", windows=False, known=known) + cbf.check(
        "Windows", windows=True, known=known
    )
    assert problems, f"{bad_flag} was not caught"
    assert any(bad_flag.split("=")[0] in p for p in problems), problems


def test_missing_plugin_flag_is_caught(known, monkeypatch):
    """--noinclude-*-mode is only valid alongside a plugin flag; dropping it must be flagged."""
    real = cbf.build.build_command

    def no_plugin(ver, *, windows=None):
        return [a for a in real(ver, windows=windows) if not a.startswith("--enable-plugin")]

    monkeypatch.setattr(cbf.build, "build_command", no_plugin)
    problems = cbf.check("Linux", windows=False, known=known)
    assert problems and any("noinclude" in p for p in problems)
