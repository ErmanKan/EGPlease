"""Check that a VNC server shows a real, non-blank screen (stdlib only).

Used for the Docker image's GUI mode: the app runs on Qt's VNC platform plugin and this
script connects like a VNC viewer, reads one full frame and counts its colours. A blank
or not-yet-drawn screen has one or two colours; the editor window has hundreds.

Usage: python scripts/vnc_probe.py [--host 127.0.0.1] [--port 5900] [--wait 60]
                                   [--min-colours 50] [--png out.png]
Exit codes: 0 frame received and not blank, 1 blank frame, 2 no server / protocol error.
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import time


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"connection closed after {len(buf)} of {n} bytes")
        buf += chunk
    return buf


def connect(host: str, port: int, wait_s: float) -> tuple[socket.socket, bytes]:
    """Connect and read the server's version greeting, retrying until ``wait_s`` has passed
    (the container may still be starting)."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            sock = socket.create_connection((host, port), timeout=20)
            sock.settimeout(20)
            # A port published by Docker accepts the connection even before the app inside
            # listens, then closes it at once: read the greeting before calling it connected.
            try:
                return sock, recv_exact(sock, 12)
            except BaseException:
                sock.close()
                raise
        except (OSError, ConnectionError):
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def read_frame(sock: socket.socket, version: bytes) -> tuple[int, int, bytes]:
    """RFB handshake without authentication, then one full frame as BGRX bytes."""
    if not version.startswith(b"RFB 003."):
        raise ConnectionError(f"not a VNC server: {version!r}")
    if version.startswith(b"RFB 003.003"):  # Qt's server: the server picks the security type
        sock.sendall(b"RFB 003.003\n")
        (sec,) = struct.unpack(">I", recv_exact(sock, 4))
        if sec != 1:
            raise ConnectionError(f"server wants security type {sec}, not 'None'")
    else:
        sock.sendall(b"RFB 003.008\n")
        (n,) = struct.unpack("B", recv_exact(sock, 1))
        if 1 not in recv_exact(sock, n):
            raise ConnectionError("server offers no 'None' security type")
        sock.sendall(b"\x01")
        if struct.unpack(">I", recv_exact(sock, 4))[0] != 0:
            raise ConnectionError("security handshake failed")
    sock.sendall(b"\x01")  # ClientInit: shared session
    w, h = struct.unpack(">HH", recv_exact(sock, 4))
    recv_exact(sock, 16)  # server pixel format (replaced below)
    (name_len,) = struct.unpack(">I", recv_exact(sock, 4))
    recv_exact(sock, name_len)
    # SetPixelFormat: 32 bpp, depth 24, little endian, true colour, R<<16 G<<8 B.
    sock.sendall(
        struct.pack(">Bxxx", 0)
        + struct.pack(">BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
    )
    sock.sendall(struct.pack(">BxHi", 2, 1, 0))  # SetEncodings: Raw only
    sock.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, w, h))  # full, non-incremental update
    while True:
        msg = recv_exact(sock, 1)[0]
        if msg == 0:
            break
        if msg == 2:  # Bell: no payload
            continue
        raise ConnectionError(f"unexpected server message {msg}")
    recv_exact(sock, 1)
    (nrects,) = struct.unpack(">H", recv_exact(sock, 2))
    frame = bytearray(w * h * 4)
    for _ in range(nrects):
        x, y, rw, rh, enc = struct.unpack(">HHHHi", recv_exact(sock, 12))
        if enc != 0:
            raise ConnectionError(f"server used encoding {enc}, not Raw")
        data = recv_exact(sock, rw * rh * 4)
        for row in range(rh):
            start = ((y + row) * w + x) * 4
            frame[start : start + rw * 4] = data[row * rw * 4 : (row + 1) * rw * 4]
    return w, h, bytes(frame)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5900)
    ap.add_argument("--wait", type=float, default=60, help="seconds to keep retrying")
    ap.add_argument("--min-colours", type=int, default=50)
    ap.add_argument("--png", help="also save the frame (needs Pillow)")
    args = ap.parse_args(argv)
    deadline = time.monotonic() + args.wait
    while True:
        try:
            sock, version = connect(args.host, args.port, max(0.0, deadline - time.monotonic()))
            with sock:
                w, h, frame = read_frame(sock, version)
        except (OSError, ConnectionError, struct.error) as exc:
            print(f"FAIL no VNC frame from {args.host}:{args.port}: {exc}")
            return 2
        colours = {frame[i : i + 3] for i in range(0, len(frame), 4)}
        # The server may answer before the window is drawn: retry a blank frame.
        if len(colours) >= args.min_colours or time.monotonic() > deadline:
            break
        time.sleep(1)
    if args.png:
        from PIL import Image

        Image.frombytes("RGBX", (w, h), frame, "raw", "BGRX").convert("RGB").save(args.png)
    if len(colours) < args.min_colours:
        print(f"FAIL frame {w}x{h} looks blank: {len(colours)} colours")
        return 1
    print(f"OK frame {w}x{h}, {len(colours)} colours")
    return 0


if __name__ == "__main__":
    sys.exit(main())
