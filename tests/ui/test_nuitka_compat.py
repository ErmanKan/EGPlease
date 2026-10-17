"""Tests for gif_editor.nuitka_compat (the workaround for Nuitka's PySide6 connect probe)."""

from __future__ import annotations

import sys
from pathlib import Path

import PySide6
import pytest
from PySide6 import QtCore

from gif_editor import nuitka_compat


def fake_patched_connect(globals_: dict):
    """A function whose __globals__ is ``globals_``, like Nuitka's patched_connect."""
    return type(lambda: None)((lambda self, slot, type=None: None).__code__, globals_)


def test_noop_when_connect_is_not_patched():
    # Plain Python: connect is PySide6's own (a method descriptor without __globals__).
    assert "not a compiled build" in nuitka_compat.skip_pyside_connect_probe()


def test_pre_answers_the_probe(monkeypatch):
    cache = {nuitka_compat.PROBE_RESULT: None}
    monkeypatch.setattr(QtCore.SignalInstance, "connect", fake_patched_connect(cache))
    assert nuitka_compat.skip_pyside_connect_probe() == "Nuitka connect probe skipped"
    assert cache[nuitka_compat.PROBE_RESULT] is False  # False: the probe never runs


def test_leaves_an_existing_answer_alone(monkeypatch):
    cache = {nuitka_compat.PROBE_RESULT: True}
    monkeypatch.setattr(QtCore.SignalInstance, "connect", fake_patched_connect(cache))
    assert "already run (result True)" in nuitka_compat.skip_pyside_connect_probe()
    assert cache[nuitka_compat.PROBE_RESULT] is True


def test_other_patch_without_the_cache_is_left_alone(monkeypatch):
    cache: dict = {}
    monkeypatch.setattr(QtCore.SignalInstance, "connect", fake_patched_connect(cache))
    assert "not a compiled build" in nuitka_compat.skip_pyside_connect_probe()
    assert cache == {}


def test_pyside6_is_a_limited_api_build():
    """The workaround answers 'not needed', which is only right for limited-API (abi3)
    builds of PySide6. If this fails, a new PySide6 wheel changed that: re-check
    nuitka_compat before shipping."""
    package = Path(PySide6.__file__).parent
    pattern = "*pyside6.abi3*.dll" if sys.platform == "win32" else "libpyside6.abi3.so*"
    found = list(package.glob(pattern))
    if not found and sys.platform == "darwin":
        pytest.skip("macOS layout not checked")
    assert found, f"no {pattern} in {package}: PySide6 is not a limited-API build"


def test_app_main_calls_it_before_any_widget_exists():
    """The call must come before MainWindow (whose Player makes the first connect)."""
    src = (Path(nuitka_compat.__file__).parent / "app.py").read_text(encoding="utf-8")
    call = src.index("skip_pyside_connect_probe()")
    assert call < src.index("QApplication.instance() or QApplication(")
    assert call < src.index("MainWindow()")
