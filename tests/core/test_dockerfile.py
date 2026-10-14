"""Static checks on the Dockerfile and .dockerignore (Docker itself is not needed).

The image is built and exercised by .github/workflows/docker.yml; these tests catch the
cheap mistakes before that: the wrong default stage, an unpinned base image, a COPY of a
path that does not exist or that .dockerignore removes from the build context.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if not (ROOT / "Dockerfile").exists():  # e.g. inside the test image, which has no Dockerfile
    pytest.skip("Dockerfile not present (not a full checkout)", allow_module_level=True)
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
IGNORE = [
    line.strip()
    for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]


def instructions(name: str) -> list[str]:
    return [m.group(1) for m in re.finditer(rf"^{name}\s+(.+)$", DOCKERFILE, re.MULTILINE)]


def ignored(path: str) -> bool:
    """True if ``path`` (repo-relative, '/'-separated) is excluded by .dockerignore."""
    for pat in IGNORE:
        pat = pat.rstrip("/")
        parts = path.split("/")
        prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        if pat.startswith("**/"):
            if any(fnmatch.fnmatch(p, pat[3:]) for p in parts):
                return True
        elif any(fnmatch.fnmatch(p, pat) for p in prefixes):
            return True
    return False


def test_runtime_is_the_last_stage_so_a_plain_build_gives_the_app():
    stages = [line.split()[-1] for line in instructions("FROM")]
    assert stages[-1] == "runtime", stages
    assert "test" in stages


def test_base_image_is_pinned_by_digest_and_matches_python_313():
    base = instructions("FROM")[0].split()[0]
    assert re.fullmatch(r"python:3\.13\.\d+-slim-trixie@sha256:[0-9a-f]{64}", base), base


def test_every_copy_source_exists_and_is_in_the_build_context():
    for args in instructions("COPY"):
        *sources, _dest = args.split()
        for src in sources:
            assert (ROOT / src).exists(), f"COPY source missing: {src}"
            assert not ignored(src.rstrip("/")), f".dockerignore excludes COPY source {src}"


def test_dockerignore_keeps_local_state_out():
    for path in (".git", ".venv", ".devlibs", "out", "src/gif_editor/__pycache__"):
        assert ignored(path), path
    for path in ("src/gif_editor/app.py", "tests/gifgen.py", "requirements.txt"):
        assert not ignored(path), path


def test_vnc_default_and_no_root():
    assert "QT_QPA_PLATFORM=vnc:" in DOCKERFILE
    assert "EXPOSE 5900" in DOCKERFILE
    users = instructions("USER")
    assert users[-1] == "app", "the last USER (inherited by runtime) must not be root"


def test_readme_publishes_vnc_on_localhost_only():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    published = re.findall(r"-p\s+(\S+):5900", readme)
    assert published and all(p.startswith("127.0.0.1:") for p in published), published
