# `scripts/vnc_probe.py`

> Connects to a VNC server like a viewer, reads one full screen and checks it is not blank: the automated check for the Docker image's default GUI mode.

## Where it sits
- **Layer:** tooling (stdlib only; Pillow only for the optional `--png`)
- **Used by:** `.github/workflows/docker.yml` (step *GUI over VNC*); by hand when trying the container; `tests/core/test_vnc_probe.py`.
- **Uses:** nothing in the project.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `python scripts/vnc_probe.py [--host H] [--port P] [--wait S] [--min-colours N] [--png FILE]` | CLI | Exit **0** = a frame with ≥ N colours (default 50), **1** = still blank when `--wait` (default 60 s) ran out, **2** = no server, a protocol error, or a server that wants a password. Prints one `OK …` / `FAIL …` line. |
| `main(argv)` | function → int | The CLI. |
| `connect(host, port, wait_s)` | function → `(socket, version)` | Connects and reads the 12-byte RFB greeting, retrying until `wait_s`. |
| `read_frame(sock, version)` | function → `(w, h, BGRX bytes)` | Handshake without authentication and one full Raw-encoded frame. |
| `recv_exact(sock, n)` | function | Reads exactly `n` bytes or raises `ConnectionError`. |

## How it works
1. **Connect with retries.** The container may still be starting. A port published by Docker accepts TCP connections even before the app inside listens, then closes them, so "connected" means "received the RFB greeting", not just "TCP accepted".
2. **Handshake.** Qt's VNC server speaks the old **RFB 3.3** protocol: the server announces the security type itself (1 = none) and sends no security result. Newer servers (3.7/3.8) send a list of types and a result; both are handled. A server that requires a password is reported, not attempted.
3. **One frame.** `SetPixelFormat` asks for 32-bit little-endian true colour, `SetEncodings` for Raw only (no decoder needed), then one non-incremental `FramebufferUpdateRequest` for the whole screen. Rectangles are stitched into one buffer.
4. **Blank or not.** Distinct colours are counted. An empty Qt VNC screen is one colour; the editor window has hundreds to thousands (1067 at 1280×800 in the first local run). Until the window is drawn the frame can be blank, so a blank frame is retried (fresh connection, 1 s apart) until the deadline.

## Invariants & gotchas
- The probe never sends input events: it only looks.
- Only the Raw encoding is supported (enough for any server, since Raw is mandatory in RFB).
- Running Qt's VNC plugin locally for a manual check: `QT_QPA_PLATFORM=vnc:size=1280x800:port=5999 python -m gif_editor in.gif`, then `python scripts/vnc_probe.py --port 5999 --png out/vnc.png`.

## Tests
- `tests/core/test_vnc_probe.py`: a fake RFB server in a thread (3.3 and 3.8 handshakes, frames sent as two rectangles): colourful frame → 0, stitching exact, blank frames retried until a real one, blank until the deadline → 1, no server → 2, password-protected → 2.
- End to end: the workflow step against the real container.

## History
- Created 2026-10-14 with the Docker image ([dev log](../../04-development-log.md#docker-image)).
