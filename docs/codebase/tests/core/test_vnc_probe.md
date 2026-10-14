# `tests/core/test_vnc_probe.py`

> Tests `scripts/vnc_probe.py` against a fake VNC (RFB) server running in a thread on localhost.

## What it covers (6 test functions, 7 cases)
| Test | Checks |
|---|---|
| `test_colourful_frame_passes` (RFB 3.3 and 3.8) | exit 0 and the `OK frame 16x8, 128 colours` line, for both handshake variants |
| `test_frame_is_stitched_from_rects` | the frame (sent as two rectangles) is reassembled byte for byte |
| `test_blank_frame_is_retried_then_passes` | two blank frames, then a real one: exit 0 after exactly 3 connections |
| `test_blank_until_deadline_fails` | only blank frames: exit 1 and `looks blank: 1 colours` |
| `test_no_server_fails_with_2` | a closed port: exit 2 |
| `test_password_protected_server_fails_with_2` | security type 2 (VNC authentication): exit 2, the type is named |

## Fixtures and helpers
- `FakeServer(frames, version=b"RFB 003.003\n", security=1)`: accepts connections in a daemon thread and serves `frames[n]` to the n-th connection (the last one repeated); counts connections. Speaks just enough RFB for the probe: greeting, security, ServerInit, then reads the probe's three client messages and answers with one FramebufferUpdate of two Raw rectangles.
- `server` fixture: a factory that closes every server it made.
- `colourful()` / `blank()`: 16×8 BGRX frames with 128 colours / one colour.

## Gotchas
- The probe module is imported from `scripts/` via `sys.path` (scripts are not a package), as in `test_check_build_flags.py`.
- Timing: the slowest case waits about 1.5 s (the blank-until-deadline test).

## History
- Created 2026-10-14 with the probe ([dev log](../../../04-development-log.md#docker-image)).
