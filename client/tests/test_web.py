import json
import socket
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from nda_client import AgentClient
from nda_client import web as web_mod
from nda_client.cli import main
from nda_client.web import make_server


@pytest.fixture
def web():
    """Starts the status page for a given agent client; yields its base URL."""
    started = []

    def start(client: AgentClient) -> str:
        httpd, source = make_server(client, port=0, refresh_s=1.0)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        started.append((httpd, source))
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for httpd, source in started:
        httpd.shutdown()
        httpd.server_close()
        source.close()


def get(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers["Content-Type"], r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], e.read()


def test_page_is_served_with_refresh_interval(web):
    base = web(AgentClient("127.0.0.1", 1))
    code, ctype, body = get(base + "/")
    assert code == 200 and ctype.startswith("text/html")
    assert b"const REFRESH_MS = 1000;" in body
    assert b"__REFRESH_MS__" not in body


def test_unknown_path_is_404(web):
    base = web(AgentClient("127.0.0.1", 1))
    assert get(base + "/nope")[0] == 404


def test_unreachable_agent_reports_502_not_a_crash(web):
    base = web(AgentClient("127.0.0.1", 1, timeout=0.5))  # nothing listens on port 1
    code, ctype, body = get(base + "/api/status")
    assert code == 502 and ctype == "application/json"
    data = json.loads(body)
    assert data["ok"] is False and data["agent"] == "127.0.0.1:1" and data["error"]


@pytest.mark.integration
def test_api_status_proxies_get_status(server, web):
    base = web(AgentClient(server.host, server.tcp_port))
    code, _, body = get(base + "/api/status")
    data = json.loads(body)
    assert code == 200 and data["ok"] is True
    assert data["status"]["hostname"] == "nda-pi"
    assert data["status"]["cpu_temperature_c"] == 48.2
    assert data["rtt_ms"] > 0


@pytest.mark.integration
def test_concurrent_browsers_share_one_connection_safely(server, web):
    base = web(AgentClient(server.host, server.tcp_port))
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: json.loads(get(base + "/api/status")[2]), range(40)))
    assert all(r["ok"] and r["status"]["hostname"] == "nda-pi" for r in results)
    with AgentClient(server.host, server.tcp_port) as c:
        assert c.request("get_metrics")["clients_total"] == 2  # page's one connection + this one


@pytest.mark.integration
def test_page_recovers_after_agent_restart(server, web):
    base = web(AgentClient(server.host, server.tcp_port, timeout=1))
    assert json.loads(get(base + "/api/status")[2])["ok"] is True
    server.stop()
    assert get(base + "/api/status")[0] == 502
    server.start()
    assert json.loads(get(base + "/api/status")[2])["ok"] is True


def _occupy() -> tuple[socket.socket, int]:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s, s.getsockname()[1]


def test_default_port_falls_back_to_a_free_port(monkeypatch, capsys):
    held, busy = _occupy()
    with held:
        monkeypatch.setattr(web_mod, "DEFAULT_WEB_PORT", busy)
        httpd, source = web_mod.bind_with_fallback(AgentClient("127.0.0.1", 1), "127.0.0.1", None, 1.0)
        try:
            assert httpd.server_address[1] not in (0, busy)
            assert "using a free port" in capsys.readouterr().out
        finally:
            httpd.server_close()
            source.close()


def test_explicit_busy_port_is_a_clear_error_not_a_traceback(capsys):
    held, busy = _occupy()
    with held:
        assert main(["--host", "127.0.0.1", "--port", "1", "web", "--web-port", str(busy)]) == 1
    err = capsys.readouterr().err
    assert f"cannot use 127.0.0.1:{busy}" in err and "--web-port" in err
