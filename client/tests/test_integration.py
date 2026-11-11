"""Loopback versions of the plan's acceptance tests (section 5). The same tests point at
the Pi by running the CLI benchmarks; these keep the server honest on every PR."""

import json
import socket
import struct
import threading
import time

import pytest

from nda_client import AgentClient, AgentConnectionError, AgentError, udp
from nda_client.bench import environment, tcp_echo

pytestmark = pytest.mark.integration


def raw_connect(server) -> socket.socket:
    s = socket.create_connection((server.host, server.tcp_port), timeout=3)
    return s


def read_frame(s: socket.socket) -> dict:
    hdr = b""
    while len(hdr) < 4:
        chunk = s.recv(4 - len(hdr))
        assert chunk, "server closed before replying"
        hdr += chunk
    (n,) = struct.unpack(">I", hdr)
    body = b""
    while len(body) < n:
        body += s.recv(n - len(body))
    return json.loads(body)


def test_status_returns_fixture_telemetry(server):
    with AgentClient(server.host, server.tcp_port) as c:
        s = c.request("get_status")
    assert s["hostname"] == "nda-pi"
    assert s["cpu_temperature_c"] == 48.2


def test_tcp_reliability_sequential_requests(server):
    """Plan: 10,000 sequential requests, 100 % valid. 2,000 here to keep CI fast."""
    with AgentClient(server.host, server.tcp_port) as c:
        for i in range(2000):
            assert c.request("echo", {"payload": str(i)})["payload"] == str(i)


def test_malformed_input_is_rejected_and_server_survives(server):
    with AgentClient(server.host, server.tcp_port) as c:
        assert c.send_raw(b"{not json")["error"]["code"] == "MALFORMED_JSON"
        assert c.send_raw(b"\xff\xfe")["error"]["code"] == "MALFORMED_JSON"
        assert c.send_raw(b'{"version":1,"request_id":1,"command":"reboot"}')["error"]["code"] == "UNKNOWN_COMMAND"
        with pytest.raises(AgentError) as e:
            c.request("run_diagnostic", {"test": "cat /etc/shadow"})
        assert e.value.code == "INVALID_ARGS"
        assert c.request("ping")  # same connection still works
    assert server.alive()


def test_oversize_frame_gets_error_then_close(server):
    with raw_connect(server) as s:
        s.sendall(struct.pack(">I", 70000))
        resp = read_frame(s)
        assert resp["error"]["code"] == "FRAME_TOO_LARGE"
        assert resp["request_id"] is None
        assert s.recv(1) == b""  # closed by server
    with AgentClient(server.host, server.tcp_port) as c:
        assert c.request("ping")


def test_partial_frame_then_disconnect_does_not_hurt_server(server):
    with raw_connect(server) as s:
        s.sendall(struct.pack(">I", 100) + b'{"version":1')
    time.sleep(0.2)
    with AgentClient(server.host, server.tcp_port) as c:
        assert c.request("ping")
    assert server.alive()


def test_pipelined_requests_answered_in_order(server):
    with raw_connect(server) as s:
        msgs = b"".join(
            struct.pack(">I", len(m)) + m
            for m in (json.dumps({"version": 1, "request_id": i, "command": "ping"}).encode() for i in range(50))
        )
        s.sendall(msgs)
        assert [read_frame(s)["request_id"] for _ in range(50)] == list(range(50))


def test_five_concurrent_clients_without_corruption(server):
    """Plan: 5 clients simultaneously, all served without protocol corruption."""
    env = environment(server.host, server.tcp_port, "loopback", "test")
    row = tcp_echo(server.host, server.tcp_port, env, payload_bytes=1024, clients=5, requests=200)
    assert row["ok"] == 1000
    assert row["errors"] == 0


def test_max_clients_rejects_with_server_busy(server):
    held = [raw_connect(server) for _ in range(8)]
    try:
        time.sleep(0.2)
        with raw_connect(server) as extra:
            assert read_frame(extra)["error"]["code"] == "SERVER_BUSY"
    finally:
        for s in held:
            s.close()


def test_idle_clients_are_closed(server):
    with raw_connect(server) as s:
        s.settimeout(6)
        assert s.recv(1) == b""  # idle-timeout is 3 s in the fixture


def test_udp_echo_counts_on_loopback(server):
    r = udp.run(server.host, server.udp_port, count=500, size=256, interval_s=0.0005, drain_s=0.5)
    assert r.sent == 500
    assert r.received >= 495  # loopback: essentially lossless, tolerate a busy CI box
    assert r.duplicates == 0
    with AgentClient(server.host, server.tcp_port) as c:
        m = c.request("get_metrics")
    assert m["udp_datagrams_rx"] >= r.received


def test_invalid_udp_datagrams_are_dropped_and_counted(server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0.3)
        s.sendto(b"hello", (server.host, server.udp_port))
        with pytest.raises(TimeoutError):
            s.recvfrom(2048)
    with AgentClient(server.host, server.tcp_port) as c:
        assert c.request("get_metrics")["udp_datagrams_invalid"] == 1


def test_recovery_after_server_restart(server):
    """Plan: restart the server mid-session; the client detects it and recovers."""
    c = AgentClient(server.host, server.tcp_port, timeout=2).connect()
    assert c.request("ping")
    server.stop()
    with pytest.raises(AgentConnectionError):
        c.request("ping")

    restarted = threading.Event()

    def restart():
        time.sleep(0.5)
        server.start()
        restarted.set()

    threading.Thread(target=restart).start()
    assert c.request_with_retry("get_status", retries=5, backoff=0.2)["hostname"] == "nda-pi"
    assert restarted.is_set()
    c.close()


def test_sigterm_shuts_down_cleanly(server):
    assert server.stop() == 0
    assert any(ev.get("event") == "stopped" for ev in server.logs)


def test_udp_rate_excludes_the_drain_wait(server):
    """msgs_per_s must not include the idle wait for late replies after the last send."""
    r = udp.run(server.host, server.udp_port, count=200, size=64, interval_s=0, drain_s=1.5)
    assert r.received >= 195
    assert r.duration_s < 1.0  # 200 loopback datagrams take milliseconds, not drain_s
