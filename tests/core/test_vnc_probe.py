"""Tests for scripts/vnc_probe.py against a fake VNC (RFB) server on localhost."""

from __future__ import annotations

import contextlib
import socket
import struct
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import vnc_probe  # noqa: E402

W, H = 16, 8


def colourful() -> bytes:
    """BGRX frame with W*H distinct colours."""
    return b"".join(bytes((i, 255 - i, (i * 7) % 256, 0)) for i in range(W * H))


def blank() -> bytes:
    return bytes((40, 40, 40, 0)) * (W * H)


class FakeServer:
    """Serves ``frames`` (one per connection, the last one repeated) over RFB 3.3 or 3.8."""

    def __init__(self, frames: list[bytes], version: bytes = b"RFB 003.003\n", security=1):
        self.frames = frames
        self.version = version
        self.security = security
        self.connections = 0
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                frame = self.frames[min(self.connections, len(self.frames) - 1)]
                self.connections += 1
                with contextlib.suppress(OSError, ConnectionError):
                    self._session(conn, frame)

    def _session(self, conn: socket.socket, frame: bytes) -> None:
        conn.sendall(self.version)
        vnc_probe.recv_exact(conn, 12)
        if self.version.startswith(b"RFB 003.003"):
            conn.sendall(struct.pack(">I", self.security))
            if self.security != 1:
                return
        else:
            conn.sendall(bytes((1, self.security)))
            vnc_probe.recv_exact(conn, 1)
            conn.sendall(struct.pack(">I", 0))
        vnc_probe.recv_exact(conn, 1)  # ClientInit
        name = b"fake"
        conn.sendall(struct.pack(">HH", W, H) + bytes(16) + struct.pack(">I", len(name)) + name)
        vnc_probe.recv_exact(conn, 20)  # SetPixelFormat
        vnc_probe.recv_exact(conn, 8)  # SetEncodings (one encoding)
        vnc_probe.recv_exact(conn, 10)  # FramebufferUpdateRequest
        # Two rects (top and bottom half) to exercise the stitching.
        half = H // 2
        conn.sendall(struct.pack(">BxH", 0, 2))
        for y in (0, half):
            conn.sendall(struct.pack(">HHHHi", 0, y, W, half, 0))
            conn.sendall(frame[y * W * 4 : (y + half) * W * 4])

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def server():
    servers: list[FakeServer] = []

    def make(*args, **kwargs) -> FakeServer:
        s = FakeServer(*args, **kwargs)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


@pytest.mark.parametrize("version", [b"RFB 003.003\n", b"RFB 003.008\n"])
def test_colourful_frame_passes(server, capsys, version):
    srv = server([colourful()], version=version)
    assert vnc_probe.main(["--port", str(srv.port), "--wait", "5"]) == 0
    assert f"OK frame {W}x{H}, {W * H} colours" in capsys.readouterr().out


def test_frame_is_stitched_from_rects():
    srv = FakeServer([colourful()])
    try:
        sock, version = vnc_probe.connect("127.0.0.1", srv.port, 5)
        with sock:
            w, h, frame = vnc_probe.read_frame(sock, version)
    finally:
        srv.close()
    assert (w, h) == (W, H)
    assert frame == colourful()


def test_blank_frame_is_retried_then_passes(server):
    srv = server([blank(), blank(), colourful()])
    assert vnc_probe.main(["--port", str(srv.port), "--wait", "10"]) == 0
    assert srv.connections == 3


def test_blank_until_deadline_fails(server, capsys):
    srv = server([blank()])
    assert vnc_probe.main(["--port", str(srv.port), "--wait", "1.5"]) == 1
    assert "looks blank: 1 colours" in capsys.readouterr().out


def test_no_server_fails_with_2(capsys):
    with socket.create_server(("127.0.0.1", 0)) as s:
        port = s.getsockname()[1]  # free port, closed again below
    assert vnc_probe.main(["--port", str(port), "--wait", "0"]) == 2
    assert "FAIL no VNC frame" in capsys.readouterr().out


def test_password_protected_server_fails_with_2(server, capsys):
    srv = server([colourful()], security=2)  # VNC authentication
    assert vnc_probe.main(["--port", str(srv.port), "--wait", "0"]) == 2
    assert "security type 2" in capsys.readouterr().out
