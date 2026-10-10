"""Shared fixtures. Keep light: no Qt imports (must work with ``-p no:pytest-qt``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from corpus import Expected, build_all


@pytest.fixture(scope="session")
def _corpus_entries(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, Expected]]:
    return build_all(tmp_path_factory.mktemp("gif_corpus"))


@pytest.fixture(scope="session")
def corpus_dir(_corpus_entries: dict[str, tuple[Path, Expected]]) -> Path:
    """Directory holding every corpus GIF (written once per session)."""
    return next(iter(_corpus_entries.values()))[0].parent


@pytest.fixture(scope="session")
def corpus(_corpus_entries: dict[str, tuple[Path, Expected]]) -> dict[str, tuple[Path, Expected]]:
    """name -> (path, Expected). Treat as read-only."""
    return _corpus_entries
