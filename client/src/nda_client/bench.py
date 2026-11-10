"""Benchmarks from the project plan (sections 5 and 6). Every run produces flat dict rows
with the same columns, appended to one CSV, so charts and the report read from one file."""

from __future__ import annotations

import contextlib
import csv
import datetime as dt
import ipaddress
import platform
import socket
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import udp
from .client import AgentClient, AgentConnectionError, AgentError
from .stats import summarize_ms

COLUMNS = [
    "run_id", "timestamp", "test", "transport", "link", "payload_bytes", "clients", "requests",
    "ok", "errors", "lost", "send_errors", "duplicates", "reordered", "loss_pct",
    "p50_ms", "p95_ms", "p99_ms", "mean_ms", "max_ms",
    "msgs_per_s", "payload_bytes_per_s", "duration_s",
    "server_host", "server_kernel", "client_platform", "client_python",
]  # fmt: skip

# The plan's benchmark matrix (section 6).
MATRIX_PAYLOADS = [64, 256, 1024, 4096]
MATRIX_CLIENTS = [1, 2, 5]
# UDP stops at one MTU: 4 KiB would be IP-fragmented, which tests the kernel's
# reassembly rather than our protocol. 1472 is the largest unfragmented datagram.
MATRIX_UDP_SIZES = [64, 256, 1024, 1472]

# Largest unfragmented UDP payload per link type. Tailscale's tunnel interface has a
# 1280-byte MTU, so a 1472-byte datagram is IP-fragmented before it enters the tunnel (or
# rejected with EMSGSIZE when the Don't-Fragment bit is set): either way that row would
# measure the tunnel's MTU, not the protocol.
LINK_UDP_MAX = {"tailscale": udp.TAILSCALE_MAX_SIZE}

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")  # CGNAT range Tailscale assigns from


def udp_max_for(link: str) -> int:
    return LINK_UDP_MAX.get(link, udp.MAX_SIZE)


def udp_sizes(max_size: int) -> list[int]:
    """The matrix UDP sizes, capped at the link's largest unfragmented datagram."""
    return sorted({s for s in MATRIX_UDP_SIZES if s <= max_size} | {max_size})


def is_tailscale_address(host: str) -> bool:
    """True when `host` resolves to a Tailscale (100.64.0.0/10) address."""
    try:
        return ipaddress.ip_address(socket.gethostbyname(host)) in TAILSCALE_NET
    except (OSError, ValueError):
        return False


def environment(host: str, port: int, link: str, run_id: str) -> dict[str, Any]:
    env = {
        "run_id": run_id,
        "link": link,
        "client_platform": platform.platform(terse=True),
        "client_python": platform.python_version(),
        "server_host": None,
        "server_kernel": None,
    }
    try:
        with AgentClient(host, port) as c:
            s = c.request("get_status")
            env["server_host"], env["server_kernel"] = s.get("hostname"), s.get("kernel")
    except (AgentConnectionError, AgentError):
        pass
    return env


def _row(env: dict[str, Any], **fields: Any) -> dict[str, Any]:
    row = dict.fromkeys(COLUMNS)
    row.update(env)
    row["timestamp"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    row.update(fields)
    return row


def tcp_latency(host: str, port: int, env: dict[str, Any], requests: int = 1000) -> dict[str, Any]:
    """Sequential pings on one connection: pure round-trip latency."""
    rtts, errors = [], 0
    t0 = time.perf_counter()
    with AgentClient(host, port) as c:
        for _ in range(requests):
            try:
                rtts.append(c.ping())
            except AgentError:
                errors += 1
    dur = time.perf_counter() - t0
    return _row(env, test="latency", transport="tcp", payload_bytes=0, clients=1, requests=requests,
                ok=len(rtts), errors=errors, duration_s=round(dur, 3),
                msgs_per_s=round(len(rtts) / dur, 1), **summarize_ms(rtts))  # fmt: skip


def _echo_worker(host: str, port: int, payload: str, n: int, out: list, barrier: threading.Barrier) -> None:
    rtts, errors = [], 0
    try:
        with AgentClient(host, port, timeout=10) as c:
            barrier.wait()
            for _ in range(n):
                t = time.perf_counter_ns()
                try:
                    data = c.request("echo", {"payload": payload})
                    if data.get("payload") != payload:
                        errors += 1  # corruption: response doesn't match what we sent
                        continue
                    rtts.append((time.perf_counter_ns() - t) / 1e6)
                except AgentError:
                    errors += 1
    except (AgentConnectionError, threading.BrokenBarrierError):
        errors += n - len(rtts)
    out.append((rtts, errors))


def tcp_echo(
    host: str, port: int, env: dict[str, Any], payload_bytes: int = 64, clients: int = 1, requests: int = 1000
) -> dict[str, Any]:
    """`clients` parallel connections, each sending `requests` echo requests.

    Throughput is application payload delivered per second in one direction; the frame
    adds a 4-byte header plus ~60 bytes of JSON envelope on top of that.
    """
    payload = "x" * payload_bytes
    out: list = []
    barrier = threading.Barrier(clients + 1)
    workers = [
        threading.Thread(target=_echo_worker, args=(host, port, payload, requests, out, barrier))
        for _ in range(clients)
    ]
    for w in workers:
        w.start()
    with contextlib.suppress(threading.BrokenBarrierError):
        barrier.wait(timeout=10)
    t0 = time.perf_counter()
    for w in workers:
        w.join()
    dur = time.perf_counter() - t0
    rtts = [r for rs, _ in out for r in rs]
    errors = sum(e for _, e in out)
    return _row(env, test="echo", transport="tcp", payload_bytes=payload_bytes, clients=clients,
                requests=requests * clients, ok=len(rtts), errors=errors, duration_s=round(dur, 3),
                msgs_per_s=round(len(rtts) / dur, 1),
                payload_bytes_per_s=round(len(rtts) * payload_bytes / dur, 1), **summarize_ms(rtts))  # fmt: skip


def udp_echo(
    host: str, port: int, env: dict[str, Any], size: int = 64, count: int = 1000, interval_s: float = 0.001
) -> dict[str, Any]:
    r = udp.run(host, port, count=count, size=size, interval_s=interval_s)
    return _row(env, test="echo", transport="udp", payload_bytes=size, clients=1, requests=r.sent + r.send_errors,
                ok=r.received, errors=r.invalid, lost=r.lost, send_errors=r.send_errors,
                duplicates=r.duplicates, reordered=r.reordered,
                loss_pct=round(r.loss_pct, 3), duration_s=round(r.duration_s, 3),
                msgs_per_s=round(r.received / r.duration_s, 1),
                payload_bytes_per_s=round(r.received * size / r.duration_s, 1), **summarize_ms(r.rtts_ms))  # fmt: skip


def matrix(
    host: str, tcp_port: int, udp_port: int, env: dict[str, Any], requests: int = 1000, udp_max: int = udp.MAX_SIZE
) -> Iterable[dict]:
    """The full plan matrix: payload x clients for TCP, sizes for UDP, plus a latency baseline."""
    yield tcp_latency(host, tcp_port, env, requests)
    for size in MATRIX_PAYLOADS:
        for clients in MATRIX_CLIENTS:
            yield tcp_echo(host, tcp_port, env, size, clients, requests)
    for size in udp_sizes(udp_max):
        yield udp_echo(host, udp_port, env, size, requests)


def append_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    n = 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        for row in rows:
            w.writerow(row)
            f.flush()  # a crash mid-matrix keeps the rows already measured
            n += 1
    return n
