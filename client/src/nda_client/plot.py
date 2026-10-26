"""The two charts the plan asks for: latency vs payload size, throughput vs clients."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def plot(csv_path: Path, outdir: Path | None = None) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = list(csv.DictReader(csv_path.open()))
    outdir = outdir or csv_path.parent
    outdir.mkdir(parents=True, exist_ok=True)
    written = []

    # 1. p50 latency (with p99 whisker) vs payload, one line per transport/link, single client.
    series: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for r in rows:
        if r["test"] == "echo" and r["clients"] == "1" and _f(r["p50_ms"]) is not None:
            series[f"{r['transport'].upper()} / {r['link']}"].append(
                (_f(r["payload_bytes"]), _f(r["p50_ms"]), _f(r["p99_ms"]))
            )
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for label, pts in sorted(series.items()):
        pts.sort()
        xs, p50, p99 = zip(*pts, strict=True)
        line = ax.plot(xs, p50, marker="o", label=f"{label} p50")[0]
        ax.plot(xs, p99, linestyle="--", color=line.get_color(), alpha=0.6, label=f"{label} p99")
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Payload size (bytes)")
    ax.set_ylabel("Round-trip latency (ms)")
    ax.set_title("Latency vs payload size (1 client)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = outdir / "latency_vs_payload.png"
    fig.savefig(p, dpi=150)
    written.append(p)

    # 2. TCP messages/s vs concurrent clients, one line per payload size.
    by_payload: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        if r["test"] == "echo" and r["transport"] == "tcp" and _f(r["msgs_per_s"]) is not None:
            by_payload[f"{r['payload_bytes']} B / {r['link']}"].append((_f(r["clients"]), _f(r["msgs_per_s"])))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for label, pts in sorted(by_payload.items(), key=lambda kv: int(kv[0].split()[0])):
        pts.sort()
        xs, ys = zip(*pts, strict=True)
        ax.plot(xs, ys, marker="o", label=label)
    ax.set_xlabel("Concurrent clients")
    ax.set_ylabel("Throughput (requests/s)")
    ax.set_title("TCP throughput vs concurrent clients")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = outdir / "throughput_vs_clients.png"
    fig.savefig(p, dpi=150)
    written.append(p)
    plt.close("all")
    return written
