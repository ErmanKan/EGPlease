# `scripts/test-hidpi.sh`

> The HiDPI pass: runs the UI tests at 150 % and 200 % scaling (`QT_SCALE_FACTOR=1.5` and `2`), the scale factors Windows uses on high-density screens.

## Where it sits
- **Layer:** tooling (bash)
- **Used by:** contributors, before committing anything that maps between screen and image pixels (canvas, crop item, timebar, filmstrip, layout). Not run by `scripts/test.sh` or CI.
- **Uses:** [`scripts/test.sh`](test.md) (once per scale factor, so lint also runs twice).

## Public API
| Usage | Effect |
|---|---|
| `scripts/test-hidpi.sh` | `scripts/test.sh tests/ui` at `QT_SCALE_FACTOR=1.5`, then at `2`. Prints `== QT_SCALE_FACTOR=<s>` and pytest's last line for each. Exit code 0 only if both runs passed. |
| `scripts/test-hidpi.sh -k canvas` | Extra arguments are passed to pytest in both runs. |

Expected output at the end of M4:
```
== QT_SCALE_FACTOR=1.5
278 passed in …s
== QT_SCALE_FACTOR=2
278 passed in …s
```

## How it works
1. `set -uo pipefail` (deliberately **not** `-e`: the second scale must run even if the first fails).
2. For each scale in `1.5 2`: run `QT_SCALE_FACTOR=$scale scripts/test.sh tests/ui "$@" | tail -1`, and record a failure from `PIPESTATUS[0]` (the exit code of `test.sh`, not of `tail`).
3. `exit $status`.

*Why `QT_SCALE_FACTOR`:* it makes Qt behave exactly as on a Windows screen at that scaling: logical pixels stay the same, physical pixels per logical pixel (device pixel ratio) become 1.5 or 2. Everything that converts between widget coordinates and image pixels (mouse drags on the canvas, crop handles and their hit areas, timebar handle positions, painting with cosmetic pens) must give the same results at every scale. The UI tests already assert those results in logical coordinates, so running them unchanged at 1.5 and 2 is the HiDPI test.

*Why it needed a bigger virtual screen:* see [`scripts/test.sh`](test.md#how-it-works) step 4 and [config-files](../config-files.md#scriptsoffscreen-screenjson). With Qt's default 800×600 offscreen screen, 200 % left only 400×400 logical pixels and mouse events beyond x=400 were not delivered; one timebar test failed for that reason only.

## Invariants & gotchas
- Only `tests/ui` runs (the core has no Qt and no scaling). 278 UI tests per scale at the end of M4.
- Each `test.sh` run has its own temp folder, so this can run alongside other test runs.
- Only the last pytest line is shown. To see failures, re-run the failing scale directly: `QT_SCALE_FACTOR=2 scripts/test.sh tests/ui`.
- It checks behaviour, not looks: crispness of the checkerboard or icons at 150 % is not asserted.

## Tests
- n/a (a test runner). End of M4: 278 passed at 1.5 and 278 passed at 2.

## History
- `d3f0297` (M4): added with `scripts/offscreen-screen.json` ([dev log, Milestone 4](../../04-development-log.md#milestone-4-hardening)).
