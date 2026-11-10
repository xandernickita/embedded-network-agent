"""`nda` command-line client.

    nda status                     system telemetry
    nda ping -n 20                 round-trip latency
    nda netinfo | metrics          interfaces / server counters
    nda diag default_route         run an allowlisted diagnostic
    nda bench latency|echo|udp|matrix --out benchmarks/results/run.csv
    nda plot benchmarks/results/run.csv
    nda web                        live status page at http://localhost:8080/

Host comes from --host or the NDA_HOST environment variable (default 127.0.0.1).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from . import bench
from .client import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT, AgentClient, AgentConnectionError, AgentError, default_host
from .stats import summarize_ms


def _fmt_uptime(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


def _na(v: Any, unit: str = "") -> str:
    return "n/a" if v is None else f"{v}{unit}"


def cmd_status(c: AgentClient, a: argparse.Namespace) -> Any:
    s = c.request_with_retry("get_status", retries=a.retries)
    if a.json:
        return s
    load = s.get("load_avg") or [None] * 3
    print(f"Connected to:    {s.get('hostname')} ({c.host}:{c.port})")
    print("Protocol:        TCP")
    print(f"Kernel:          {_na(s.get('kernel'))}")
    print(f"Uptime:          {_fmt_uptime(s.get('uptime_seconds'))}")
    print(f"CPU temperature: {_na(s.get('cpu_temperature_c'), ' C')}")
    print(f"Load average:    {' '.join(_na(x) for x in load)}")
    print(f"Memory usage:    {_na(s.get('memory_percent'), '%')}")
    print("Status:          OK")
    return None


def cmd_ping(c: AgentClient, a: argparse.Namespace) -> Any:
    rtts = [c.ping() for _ in range(a.count)]
    summary = summarize_ms(rtts)
    if a.json:
        return {"count": a.count, **summary}
    for i, r in enumerate(rtts):
        print(f"seq={i} rtt={r:.3f} ms")
    print(f"--- {a.count} pings: p50 {summary['p50_ms']} ms, p95 {summary['p95_ms']} ms, max {summary['max_ms']} ms")
    return None


def cmd_simple(command: str):
    def run(c: AgentClient, a: argparse.Namespace) -> Any:
        return c.request_with_retry(command, retries=a.retries)

    return run


def cmd_diag(c: AgentClient, a: argparse.Namespace) -> Any:
    return c.request("run_diagnostic", {"test": a.test})


def cmd_bench(a: argparse.Namespace) -> int:
    run_id = a.run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    env = bench.environment(a.host, a.port, a.link, run_id)
    if env["server_host"] is None:
        print(f"error: no agent answering on {a.host}:{a.port}", file=sys.stderr)
        return 1

    if a.kind == "latency":
        rows = [bench.tcp_latency(a.host, a.port, env, a.requests)]
    elif a.kind == "echo":
        rows = [bench.tcp_echo(a.host, a.port, env, a.payload, a.clients, a.requests)]
    elif a.kind == "udp":
        rows = [bench.udp_echo(a.host, a.udp_port, env, a.payload, a.requests, a.interval)]
    else:
        rows = bench.matrix(a.host, a.port, a.udp_port, env, a.requests)

    def show(rows):
        for r in rows:
            print(
                f"{r['transport']:<4} {r['test']:<8} payload={r['payload_bytes']!s:>5} clients={r['clients']} "
                f"ok={r['ok']}/{r['requests']} lost={r['lost'] if r['lost'] is not None else '-'} "
                f"p50={r['p50_ms']} p99={r['p99_ms']} ms  {r['msgs_per_s']} msg/s",
                flush=True,
            )
            yield r

    n = bench.append_csv(Path(a.out), show(rows))
    print(f"{n} row(s) appended to {a.out} (run_id {run_id})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nda", description="Embedded Network Diagnostics Agent client")
    p.add_argument("--host", default=default_host(), help="agent address (env NDA_HOST, default 127.0.0.1)")
    p.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help="TCP command port")
    p.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT)
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.add_argument("--retries", type=int, default=2, help="reconnect attempts after a connection failure")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="system telemetry").set_defaults(fn=cmd_status)
    sp = sub.add_parser("ping", help="round-trip latency")
    sp.add_argument("-n", "--count", type=int, default=5)
    sp.set_defaults(fn=cmd_ping)
    sub.add_parser("netinfo", help="network interfaces").set_defaults(fn=cmd_simple("get_netinfo"))
    sub.add_parser("metrics", help="server counters").set_defaults(fn=cmd_simple("get_metrics"))
    sd = sub.add_parser("diag", help="run an allowlisted diagnostic")
    sd.add_argument("test", choices=["default_route", "link_stats", "gateway_tcp"])
    sd.set_defaults(fn=cmd_diag)

    sb = sub.add_parser("bench", help="run benchmarks and append results to a CSV")
    sb.add_argument("kind", choices=["latency", "echo", "udp", "matrix"])
    sb.add_argument("--link", default="unknown", help="wifi | ethernet | loopback (recorded in the CSV)")
    sb.add_argument("--payload", type=int, default=64, help="payload bytes (echo, udp)")
    sb.add_argument("--clients", type=int, default=1, help="parallel TCP connections (echo)")
    sb.add_argument("--requests", type=int, default=1000, help="requests per client / datagrams")
    sb.add_argument("--interval", type=float, default=0.001, help="seconds between UDP datagrams")
    sb.add_argument("--run-id", default=None)
    sb.add_argument("--out", default="benchmarks/results/results.csv")

    spl = sub.add_parser("plot", help="draw the two report charts from a results CSV (needs [plot] extra)")
    spl.add_argument("csv")
    spl.add_argument("--outdir", default=None)

    sw = sub.add_parser("web", help="serve a live status page on this laptop (agent stays unchanged)")
    sw.add_argument("--listen", default="127.0.0.1", help="address for the page (default: this laptop only)")
    sw.add_argument("--web-port", type=int, default=None, help="default 8080, or any free port if 8080 is unavailable")
    sw.add_argument("--refresh", type=float, default=2.0, help="seconds between updates")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "bench":
            return cmd_bench(a)
        if a.cmd == "plot":
            from .plot import plot

            for path in plot(Path(a.csv), Path(a.outdir) if a.outdir else None):
                print(path)
            return 0
        if a.cmd == "web":
            from .web import WebBindError, serve

            # Connects lazily, so the page starts (and shows "unreachable") even if the Pi is off.
            try:
                serve(AgentClient(a.host, a.port, a.timeout), a.listen, a.web_port, max(a.refresh, 0.5))
            except WebBindError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            return 0
        with AgentClient(a.host, a.port, a.timeout) as c:
            out = a.fn(c, a)
        if out is not None:
            print(json.dumps(out, indent=2))
        return 0
    except AgentError as e:
        print(f"server error {e.code}: {e.message}", file=sys.stderr)
        return 3
    except AgentConnectionError as e:
        print(f"connection error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
