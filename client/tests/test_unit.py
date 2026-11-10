import csv
import math
import socket

import pytest

from nda_client import bench, framing, udp
from nda_client.stats import percentile, summarize_ms


def test_frame_header_is_big_endian_length():
    assert framing.encode(b"hello") == b"\x00\x00\x00\x05hello"


def test_frame_rejects_empty_and_oversize():
    with pytest.raises(ValueError):
        framing.encode(b"")
    with pytest.raises(ValueError):
        framing.encode(b"x" * (framing.MAX_FRAME + 1))


def test_recv_frame_reassembles_split_delivery():
    a, b = socket.socketpair()
    with a, b:
        frame = framing.encode(b'{"k":1}')
        for byte in frame:  # one byte per send: forces many short recv() calls
            a.send(bytes([byte]))
        assert framing.recv_frame(b) == b'{"k":1}'


def test_recv_frame_detects_bad_length():
    a, b = socket.socketpair()
    with a, b:
        a.send(b"\x00\x00\x00\x00")
        with pytest.raises(framing.FramingError):
            framing.recv_frame(b)


def test_percentile_matches_linear_interpolation():
    v = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(v, 50) == 5.5
    assert percentile(v, 0) == 1
    assert percentile(v, 100) == 10
    assert math.isclose(percentile(v, 95), 9.55)
    assert math.isnan(percentile([], 50))


def test_summary_keys():
    s = summarize_ms([1.0, 2.0, 3.0])
    assert s["p50_ms"] == 2.0 and s["max_ms"] == 3.0 and s["mean_ms"] == 2.0


def test_datagram_round_trip_and_limits():
    d = udp.build_datagram(7, 123456789, 64)
    assert len(d) == 64 and d[:4] == b"NDA1"
    assert udp.parse_datagram(d) == (7, 123456789)
    assert udp.parse_datagram(b"XXXX" + d[4:]) is None
    assert udp.parse_datagram(d[:15]) is None
    with pytest.raises(ValueError):
        udp.build_datagram(0, 0, 1473)


def test_udp_analysis_counts_loss_duplicates_and_reordering():
    # sent 0..5; 3 lost; 4 arrives before 2; 1 duplicated
    arrivals = [(0, 0, 1_000_000), (1, 0, 2_000_000), (1, 0, 2_100_000), (4, 0, 3_000_000),
                (2, 0, 4_000_000), (5, 0, 5_000_000)]  # fmt: skip
    r = udp.analyze(6, arrivals)
    assert r.received == 5
    assert r.lost == 1
    assert r.duplicates == 1
    assert r.reordered == 1
    assert r.rtts_ms == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert math.isclose(r.loss_pct, 100 / 6)


def test_csv_has_stable_columns_and_header_once(tmp_path):
    out = tmp_path / "r.csv"
    row = dict.fromkeys(bench.COLUMNS, 1)
    bench.append_csv(out, [row])
    bench.append_csv(out, [row, row])
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 3
    assert list(rows[0].keys()) == bench.COLUMNS


def test_udp_sizes_are_capped_at_the_link_mtu():
    assert bench.udp_sizes(udp.MAX_SIZE) == [64, 256, 1024, 1472]
    assert bench.udp_sizes(bench.udp_max_for("tailscale")) == [64, 256, 1024, 1252]
    assert bench.udp_max_for("ethernet") == 1472


def test_tailscale_address_detection():
    assert bench.is_tailscale_address("100.101.102.103")
    assert bench.is_tailscale_address("100.64.0.1")
    assert not bench.is_tailscale_address("100.128.0.1")  # just outside 100.64.0.0/10
    assert not bench.is_tailscale_address("192.168.1.177")
    assert not bench.is_tailscale_address("127.0.0.1")
    assert not bench.is_tailscale_address("no-such-host.invalid")


def test_local_send_failures_are_not_counted_as_network_loss(monkeypatch):
    """A datagram the OS refuses to send (e.g. EMSGSIZE) never reached the network."""
    calls = {"n": 0}
    real_send = udp._send

    def flaky(sock, data):
        calls["n"] += 1
        if calls["n"] % 4 == 0:
            raise OSError(90, "Message too long")
        real_send(sock, data)

    monkeypatch.setattr(udp, "_send", flaky)
    # Nothing answers on this port, so every datagram that *was* sent is lost.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as hole:
        hole.bind(("127.0.0.1", 0))
        port = hole.getsockname()[1]
        r = udp.run("127.0.0.1", port, count=40, size=64, interval_s=0, drain_s=0.1)
    assert r.send_errors == 10
    assert r.sent == 30
    assert r.lost == 30  # only datagrams that left the host count as lost
