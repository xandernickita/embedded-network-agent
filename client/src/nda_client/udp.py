"""UDP benchmark: delivery, ordering and RTT against the server's echo endpoint
(docs/PROTOCOL.md section 2)."""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field

MAGIC = b"NDA1"
HEADER = struct.Struct(">4sIQ")  # magic, seq, t_send_ns
MIN_SIZE = HEADER.size  # 16
MAX_SIZE = 1472  # never fragments on a 1500-byte MTU
TAILSCALE_MAX_SIZE = 1252  # Tailscale's interface MTU is 1280: 1280 - 20 IPv4 - 8 UDP


def build_datagram(seq: int, t_send_ns: int, size: int) -> bytes:
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ValueError(f"datagram size must be {MIN_SIZE}..{MAX_SIZE}")
    return HEADER.pack(MAGIC, seq, t_send_ns) + b"\x00" * (size - MIN_SIZE)


def parse_datagram(data: bytes) -> tuple[int, int] | None:
    if len(data) < MIN_SIZE:
        return None
    magic, seq, t_send = HEADER.unpack_from(data)
    return (seq, t_send) if magic == MAGIC else None


@dataclass
class UdpResult:
    sent: int = 0  # datagrams the OS accepted; local send failures are counted separately
    send_errors: int = 0  # e.g. EMSGSIZE when a datagram exceeds the interface MTU
    received: int = 0  # unique sequence numbers
    duplicates: int = 0
    reordered: int = 0
    invalid: int = 0
    rtts_ms: list[float] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def lost(self) -> int:
        return self.sent - self.received

    @property
    def loss_pct(self) -> float:
        return 100.0 * self.lost / self.sent if self.sent else 0.0


def analyze(sent: int, arrivals: list[tuple[int, int, int]]) -> UdpResult:
    """arrivals: (seq, t_send_ns, t_recv_ns) in arrival order. Pure, so it is unit-tested."""
    r = UdpResult(sent=sent)
    seen: set[int] = set()
    highest = -1
    for seq, t_send, t_recv in arrivals:
        if seq in seen:
            r.duplicates += 1
            continue
        seen.add(seq)
        if seq < highest:
            r.reordered += 1
        highest = max(highest, seq)
        r.rtts_ms.append((t_recv - t_send) / 1e6)
    r.received = len(seen)
    return r


def _send(sock: socket.socket, data: bytes) -> None:
    sock.send(data)  # separate function so tests can inject send failures


def run(
    host: str, port: int, count: int = 1000, size: int = 64, interval_s: float = 0.001, drain_s: float = 1.0
) -> UdpResult:
    """Send `count` datagrams, `interval_s` apart, then wait `drain_s` for stragglers.

    perf_counter_ns is used rather than monotonic_ns because on Windows monotonic has
    ~15 ms resolution, which would swamp a LAN round trip.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.connect((socket.gethostbyname(host), port))  # filters replies to this peer only
    sock.settimeout(0.05)

    arrivals: list[tuple[int, int, int]] = []
    invalid = 0
    done_sending = threading.Event()
    deadline = [float("inf")]

    def receiver() -> None:
        nonlocal invalid
        while time.monotonic() < deadline[0]:
            try:
                data = sock.recv(2048)
            except TimeoutError:
                continue
            except OSError:  # ICMP port unreachable surfaces as ConnectionRefused/Reset
                if done_sending.is_set():
                    continue
                time.sleep(0.001)
                continue
            t_recv = time.perf_counter_ns()
            parsed = parse_datagram(data)
            if parsed is None:
                invalid += 1
            else:
                arrivals.append((parsed[0], parsed[1], t_recv))

    rx = threading.Thread(target=receiver, daemon=True)
    rx.start()
    t0 = time.perf_counter()
    next_send = t0
    send_errors = 0
    for seq in range(count):
        # A local send failure is not network loss: keep it out of the loss figure.
        try:
            _send(sock, build_datagram(seq, time.perf_counter_ns(), size))
        except OSError:
            send_errors += 1
        next_send += interval_s
        delay = next_send - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    done_sending.set()
    deadline[0] = time.monotonic() + drain_s
    rx.join()
    sock.close()

    result = analyze(count - send_errors, arrivals)
    result.send_errors = send_errors
    result.invalid = invalid
    result.duration_s = time.perf_counter() - t0
    return result
