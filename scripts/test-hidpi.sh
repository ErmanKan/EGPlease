#!/usr/bin/env bash
# HiDPI pass: run the UI tests at 150 % and 200 % scaling (Qt's QT_SCALE_FACTOR), the same
# scale factors Windows uses on high-density monitors. Everything that maps between screen
# and image pixels (mouse drags on the canvas, crop handles, timebar handles, hit areas
# measured in screen pixels) must behave identically at every scale.
# Usage: scripts/test-hidpi.sh [extra pytest args]
set -uo pipefail
cd "$(dirname "$0")/.."
status=0
for scale in 1.5 2; do
  echo "== QT_SCALE_FACTOR=$scale"
  QT_SCALE_FACTOR=$scale scripts/test.sh tests/ui "$@" | tail -1
  [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
done
exit $status
