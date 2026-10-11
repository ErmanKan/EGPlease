#!/usr/bin/env bash
# Run lint + the full test suite headlessly in the Linux dev container.
# Usage: scripts/test.sh [extra pytest args]
set -euo pipefail
cd "$(dirname "$0")/.."
LIBDIR="$PWD/.devlibs/root/usr/lib/x86_64-linux-gnu"
[ -e "$LIBDIR/libEGL.so.1" ] || scripts/fetch-devlibs.sh
export LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
# A virtual 3840x2160 screen. Qt's default offscreen screen is only 800x600 physical px,
# which at QT_SCALE_FACTOR=2 is 400x400 logical: smaller than the test windows, so mouse
# events past x=400 were never delivered. See scripts/test-hidpi.sh.
export QT_QPA_PLATFORM="offscreen:configfile=$PWD/scripts/offscreen-screen.json"
.venv/bin/ruff format --check .
.venv/bin/ruff check .
exec .venv/bin/python -m pytest -q "$@"
