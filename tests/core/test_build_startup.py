"""Tests for the onefile start-up cache: the build flag and smoke_build's step-4 helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402
import smoke_build  # noqa: E402


@pytest.mark.parametrize("windows", [True, False])
def test_unpack_folder_is_static_so_nuitka_caches(windows):
    specs = [a for a in build.build_command("1.2.3", windows=windows) if "tempdir-spec" in a]
    assert len(specs) == 1
    spec = specs[0].split("=", 1)[1]
    # A static path makes Nuitka reuse the folder ("cached" mode); any per-run part
    # ({PID}, {TIME}, {TIME_US}, {RANDOM}) or {TEMP} would bring back unpacking every start.
    for per_run in ("{PID}", "{TIME", "{RANDOM}", "{TEMP}"):
        assert per_run not in spec
    assert spec.startswith("{CACHE_DIR}/")
    assert "{VERSION}" in spec  # a new version gets its own folder


def test_unpack_cache_dirs_finds_the_version_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke_build.sys, "platform", "linux")
    assert smoke_build.unpack_cache_dirs(tmp_path) == []
    folder = tmp_path / "cache" / "Erman K" / "GIF Editor" / "0.1.0.0"
    folder.mkdir(parents=True)
    (folder.parent / "stray.txt").write_text("not a folder")
    assert smoke_build.unpack_cache_dirs(tmp_path) == [folder]


def test_temp_leftovers_lists_only_onefile_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke_build.sys, "platform", "linux")
    (tmp_path / "onefile_123_456").mkdir()
    (tmp_path / "onefile_note.txt").write_text("a file, not a folder")
    (tmp_path / "cache").mkdir()
    assert smoke_build.temp_leftovers(tmp_path) == [tmp_path / "onefile_123_456"]
