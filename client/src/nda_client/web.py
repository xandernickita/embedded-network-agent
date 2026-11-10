"""`nda web`: a local status page for the agent, served from the laptop.

The page is just another client of the TCP protocol: the browser polls /api/status on
this laptop-side server, which forwards `get_status` to the Pi. Nothing runs on the Pi,
so the measured server binary is unchanged (docs/decisions/003-laptop-side-status-page.md).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .client import AgentClient, AgentConnectionError, AgentError


class StatusSource:
    """One shared connection to the agent. AgentClient isn't thread-safe and the HTTP
    server is threaded, so requests take turns through a lock."""

    def __init__(self, client: AgentClient):
        self._client = client
        self._lock = threading.Lock()

    def fetch(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            t0 = time.perf_counter_ns()
            try:
                status = self._client.request_with_retry("get_status", retries=1, backoff=0.2)
            except AgentConnectionError as e:
                return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(e), **self._target()}
            except AgentError as e:
                return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": f"{e.code}: {e.message}", **self._target()}
            rtt_ms = (time.perf_counter_ns() - t0) / 1e6
        return HTTPStatus.OK, {"ok": True, "rtt_ms": round(rtt_ms, 3), "status": status, **self._target()}

    def _target(self) -> dict[str, Any]:
        return {"agent": f"{self._client.host}:{self._client.port}"}

    def close(self) -> None:
        with self._lock:
            self._client.close()


def make_handler(source: StatusSource, refresh_s: float) -> type[BaseHTTPRequestHandler]:
    page = PAGE.replace("__REFRESH_MS__", str(int(refresh_s * 1000))).encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "nda-web"

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", page)
            elif path == "/api/status":
                code, body = source.fetch()
                self._send(code, "application/json", json.dumps(body).encode())
            else:
                self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found")

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the terminal quiet
            pass

    return Handler


DEFAULT_WEB_PORT = 8080


class _StatusHTTPServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second program bind a port that's already in use, so
    # two pages could silently share 8080. Only reuse addresses where it means TIME_WAIT.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


class WebBindError(Exception):
    """The status page couldn't get a local port."""


def make_server(client: AgentClient, listen: str = "127.0.0.1", port: int = DEFAULT_WEB_PORT, refresh_s: float = 2.0):
    """Returns (httpd, source). Port 0 picks a free port (tests)."""
    source = StatusSource(client)
    httpd = _StatusHTTPServer((listen, port), make_handler(source, refresh_s))
    return httpd, source


def bind_with_fallback(client: AgentClient, listen: str, port: int | None, refresh_s: float):
    """Bind the requested port. With no explicit port, try 8080 and fall back to any free
    port: on Windows, 8080 is often inside a range reserved by Hyper-V/WSL/Docker
    (WinError 10013) or already taken by another program (WinError 10048)."""
    try:
        return make_server(client, listen, DEFAULT_WEB_PORT if port is None else port, refresh_s)
    except OSError as e:
        if port is not None:
            raise WebBindError(
                f"cannot use {listen}:{port} ({e.strerror or e}). "
                "Pick another --web-port, or omit it to let nda choose a free one."
            ) from e
        print(f"Port {DEFAULT_WEB_PORT} unavailable ({e.strerror or e}); using a free port instead.")
        try:
            return make_server(client, listen, 0, refresh_s)
        except OSError as e2:
            raise WebBindError(f"cannot listen on {listen} ({e2.strerror or e2})") from e2


def serve(client: AgentClient, listen: str, port: int | None, refresh_s: float) -> None:
    httpd, source = bind_with_fallback(client, listen, port, refresh_s)
    host, bound = httpd.server_address[:2]
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"Status page: http://{shown}:{bound}/  (agent {client.host}:{client.port}, Ctrl+C to stop)")
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        source.close()


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nda status</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --fg:#1b1f24; --muted:#5d6670; --line:#e3e6ea;
          --ok:#1a7f37; --bad:#c62828; --bar:#2f6fdd; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111418; --card:#1a1f25; --fg:#e8ebee; --muted:#98a2ad; --line:#2a3139;
            --ok:#3fb950; --bad:#f47067; --bar:#539bf5; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width:560px; margin:40px auto; padding:0 16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px 22px; }
  header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; }
  h1 { font-size:20px; margin:0; }
  .pill { font-size:13px; font-weight:600; padding:3px 10px; border-radius:999px; border:1px solid currentColor; }
  .pill.ok { color:var(--ok); } .pill.bad { color:var(--bad); }
  dl { display:grid; grid-template-columns:max-content 1fr; gap:10px 18px; margin:0; }
  dt { color:var(--muted); }
  dd { margin:0; font-variant-numeric:tabular-nums; }
  .meter { height:6px; background:var(--line); border-radius:3px; margin-top:5px; overflow:hidden; }
  .meter > span { display:block; height:100%; background:var(--bar); width:0; transition:width .4s; }
  footer { color:var(--muted); font-size:13px; margin-top:14px; }
  .err { color:var(--bad); margin:0 0 12px; display:none; }
  dl.stale dd { opacity:.45; }
  code { font-family: ui-monospace, Consolas, monospace; font-size:13px; }
</style>
</head>
<body>
<main>
  <div class="card">
    <header>
      <h1 id="host">nda status</h1>
      <span id="pill" class="pill">connecting</span>
    </header>
    <p id="err" class="err"></p>
    <dl id="vals">
      <dt>Agent</dt><dd><code id="agent">-</code></dd>
      <dt>Protocol</dt><dd>TCP (framed JSON, v1)</dd>
      <dt>Kernel</dt><dd id="kernel">-</dd>
      <dt>Uptime</dt><dd id="uptime">-</dd>
      <dt>CPU temperature</dt><dd id="temp">-</dd>
      <dt>Load average</dt><dd id="load">-</dd>
      <dt>Memory usage</dt><dd><span id="mem">-</span><div class="meter"><span id="membar"></span></div></dd>
      <dt>Round trip</dt><dd id="rtt">-</dd>
    </dl>
    <footer>Refreshes every <span id="every"></span> s &middot; last update <span id="when">never</span></footer>
  </div>
</main>
<script>
const REFRESH_MS = __REFRESH_MS__;
const $ = (id) => document.getElementById(id);
const na = (v, unit = "") => (v === null || v === undefined) ? "n/a" : v + unit;
function uptime(s) {
  if (s == null) return "n/a";
  s = Math.floor(s);
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return d ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
}
function setPill(ok) {
  $("vals").classList.toggle("stale", !ok);  // keep last values visible, but clearly not current
  $("pill").textContent = ok ? "OK" : "unreachable";
  $("pill").className = "pill " + (ok ? "ok" : "bad");
}
async function tick() {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    const body = await r.json();
    $("agent").textContent = body.agent;
    if (!body.ok) throw new Error(body.error);
    const s = body.status;
    $("host").textContent = s.hostname || "nda status";
    $("kernel").textContent = na(s.kernel);
    $("uptime").textContent = uptime(s.uptime_seconds);
    $("temp").textContent = na(s.cpu_temperature_c, " \\u00b0C");
    $("load").textContent = s.load_avg ? s.load_avg.map((x) => x.toFixed(2)).join("  ") : "n/a";
    $("mem").textContent = na(s.memory_percent, "%");
    $("membar").style.width = (s.memory_percent || 0) + "%";
    $("rtt").textContent = body.rtt_ms.toFixed(1) + " ms (laptop \\u2194 Pi, get_status)";
    $("err").style.display = "none";
    setPill(true);
    $("when").textContent = new Date().toLocaleTimeString();
  } catch (e) {
    $("err").textContent = String(e.message || e);
    $("err").style.display = "block";
    setPill(false);
  }
}
$("every").textContent = REFRESH_MS / 1000;
tick();
setInterval(tick, REFRESH_MS);
</script>
</body>
</html>
"""
