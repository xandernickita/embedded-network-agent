"""Length-prefixed framing, mirroring server/src/framing.cpp (docs/PROTOCOL.md section 1)."""

from __future__ import annotations

import socket
import struct

HEADER = struct.Struct(">I")
MAX_FRAME = 65536


class FramingError(Exception):
    """The peer sent a header we can't honour; the stream position is lost."""


def encode(payload: bytes) -> bytes:
    if not 1 <= len(payload) <= MAX_FRAME:
        raise ValueError(f"payload must be 1..{MAX_FRAME} bytes, got {len(payload)}")
    return HEADER.pack(len(payload)) + payload


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes. A TCP recv() may return fewer than asked, so loop."""
    chunks = []
    remaining = n
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("server closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(sock: socket.socket) -> bytes:
    (length,) = HEADER.unpack(recv_exact(sock, HEADER.size))
    if not 1 <= length <= MAX_FRAME:
        raise FramingError(f"bad frame length {length}")
    return recv_exact(sock, length)
