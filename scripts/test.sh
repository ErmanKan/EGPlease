#!/usr/bin/env bash
# Run lint + the full test suite headlessly in the Linux dev container.
# Usage: scripts/test.sh [extra pytest args]
set -euo pipefail
cd "$(dirname "$0")/.."
LIBDIR="$PWD/.devlibs/root/usr/lib/x86_64-linux-gnu"
[ -e "$LIBDIR/libEGL.so.1" ] || scripts/fetch-devlibs.sh
export LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_QPA_PLATFORM=offscreen
.venv/bin/ruff format --check .
.venv/bin/ruff check .
exec .venv/bin/python -m pytest -q "$@"
