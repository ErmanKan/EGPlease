"""Tests for gif_editor.resources: finding bundled files from source and from a frozen build."""

from __future__ import annotations

from pathlib import Path

from gif_editor.resources import icon_path, resource_path


def test_resource_path_finds_the_icons():
    icons = resource_path("icons")
    assert icons.is_dir()
    assert (icons / "icon.ico").exists()


def test_icon_path_prefers_the_platform_format(monkeypatch):
    """Windows gets the .ico (Explorer/taskbar); elsewhere the PNG (Linux icon consumers)."""
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    assert icon_path() is not None and icon_path().suffix == ".ico"
    monkeypatch.setattr(sys, "platform", "linux")
    assert icon_path() is not None and icon_path().suffix == ".png"


def test_icon_path_returns_none_when_nothing_is_bundled(monkeypatch):
    monkeypatch.setattr("gif_editor.resources.resource_path", lambda *p: Path("/nonexistent/x"))
    assert icon_path() is None


def test_resource_path_uses_the_onefile_env_var(monkeypatch, tmp_path):
    """Inside a Nuitka onefile the tree is unpacked elsewhere; NUITKA_ONEFILE_DIR locates it."""
    bundled = tmp_path / "gif_editor" / "resources" / "icons"
    bundled.mkdir(parents=True)
    (bundled / "icon.ico").write_bytes(b"x")
    monkeypatch.setenv("NUITKA_ONEFILE_DIR", str(tmp_path))
    # Pretend the package directory does not exist (as happens mid-unpack) so the env var is
    # the only route to the file.
    import gif_editor.resources as res

    monkeypatch.setattr(res, "__file__", str(tmp_path / "elsewhere" / "__init__.py"))
    assert resource_path("icons", "icon.ico").read_bytes() == b"x"


def test_missing_resource_returns_the_expected_path(monkeypatch):
    """Callers check .exists(); the path must be informative, not raise."""
    monkeypatch.delenv("NUITKA_ONEFILE_DIR", raising=False)
    p = resource_path("icons", "not-there.xyz")
    assert str(p).endswith("not-there.xyz") and not p.exists()
