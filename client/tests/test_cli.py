import csv

import pytest

from nda_client.cli import main

pytestmark = pytest.mark.integration


def args(server, *rest):
    return ["--host", server.host, "--port", str(server.tcp_port), "--udp-port", str(server.udp_port), *rest]


def test_status_prints_telemetry(server, capsys):
    assert main(args(server, "status")) == 0
    out = capsys.readouterr().out
    assert "nda-pi" in out and "48.2 C" in out and "31.4%" in out


def test_json_and_diag(server, capsys):
    assert main(args(server, "--json", "diag", "default_route")) == 0
    assert '"gateway": "192.168.1.1"' in capsys.readouterr().out


def test_ping_summary(server, capsys):
    assert main(args(server, "ping", "-n", "3")) == 0
    assert "3 pings" in capsys.readouterr().out


def test_unreachable_server_exits_2(capsys):
    assert main(["--host", "127.0.0.1", "--port", "1", "--retries", "0", "status"]) == 2
    assert "connection error" in capsys.readouterr().err


def test_bench_writes_csv(server, tmp_path):
    out = tmp_path / "r.csv"
    assert main(args(server, "bench", "echo", "--clients", "2", "--requests", "50", "--link", "loopback",
                     "--out", str(out))) == 0  # fmt: skip
    assert main(args(server, "bench", "udp", "--requests", "50", "--link", "loopback", "--out", str(out))) == 0
    rows = list(csv.DictReader(out.open()))
    assert [r["transport"] for r in rows] == ["tcp", "udp"]
    assert rows[0]["ok"] == "100" and rows[0]["server_host"] == "nda-pi" and rows[0]["link"] == "loopback"


def test_plot_writes_two_charts(server, tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "r.csv"
    for clients in ("1", "2"):
        main(args(server, "bench", "echo", "--clients", clients, "--requests", "20", "--out", str(out)))
    assert main(["plot", str(out)]) == 0
    assert (tmp_path / "latency_vs_payload.png").exists()
    assert (tmp_path / "throughput_vs_clients.png").exists()
