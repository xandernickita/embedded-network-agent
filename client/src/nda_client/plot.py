"""The two charts the plan asks for: latency vs payload size, throughput vs clients.

Each configuration may have been run several times (one `run_id` per `nda bench matrix`).
Single runs over Wi-Fi vary a lot, so the charts plot the **median across runs** and show
the min-max range across runs as error bars. Several CSVs (e.g. ethernet, wifi, tailscale)
can be drawn on the same chart to compare links.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path


def _f(v: str | None) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def load(paths: Iterable[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for p in paths:
        with p.open(newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def aggregate(values: list[float]) -> tuple[float, float, float, int]:
    """(median, min, max, n) across repeated runs of one configuration."""
    return statistics.median(values), min(values), max(values), len(values)


def latency_series(rows: list[dict[str, str]]) -> dict[str, dict[float, dict[str, tuple]]]:
    """{ "TCP / ethernet": { payload: {"p50": agg, "p99": agg} } } for single-client echo rows."""
    raw: dict[str, dict[float, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        if r.get("test") != "echo" or r.get("clients") != "1":
            continue
        x, p50, p99 = _f(r.get("payload_bytes")), _f(r.get("p50_ms")), _f(r.get("p99_ms"))
        if None in (x, p50, p99):
            continue
        cell = raw[f"{r['transport'].upper()} / {r['link']}"][x]
        cell["p50"].append(p50)
        cell["p99"].append(p99)
    return {s: {x: {k: aggregate(v) for k, v in m.items()} for x, m in xs.items()} for s, xs in raw.items()}


def throughput_series(rows: list[dict[str, str]]) -> dict[str, dict[float, tuple]]:
    """{ "64 B / ethernet": { clients: agg(msgs_per_s) } } for TCP echo rows."""
    raw: dict[str, dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get("test") != "echo" or r.get("transport") != "tcp":
            continue
        x, y = _f(r.get("clients")), _f(r.get("msgs_per_s"))
        if None in (x, y):
            continue
        raw[f"{r['payload_bytes']} B / {r['link']}"][x].append(y)
    return {s: {x: aggregate(v) for x, v in xs.items()} for s, xs in raw.items()}


def _errbars(aggs: list[tuple]) -> tuple[list[float], list[list[float]]]:
    med = [a[0] for a in aggs]
    return med, [[a[0] - a[1] for a in aggs], [a[2] - a[0] for a in aggs]]


def _runs_note(n_values: Iterable[int]) -> str:
    ns = sorted(set(n_values))
    if ns == [1]:
        return "single run"
    return f"median of {ns[0]} runs" if len(ns) == 1 else f"median of {ns[0]}-{ns[-1]} runs"


def plot(csv_paths: Path | list[Path], outdir: Path | None = None) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = [csv_paths] if isinstance(csv_paths, Path) else list(csv_paths)
    rows = load(paths)
    outdir = outdir or paths[0].parent
    outdir.mkdir(parents=True, exist_ok=True)
    written = []

    # 1. Latency vs payload (1 client): median p50 solid, median p99 dashed, bars = range across runs.
    lat = latency_series(rows)
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ns = []
    for label in sorted(lat):
        xs = sorted(lat[label])
        p50, e50 = _errbars([lat[label][x]["p50"] for x in xs])
        p99, e99 = _errbars([lat[label][x]["p99"] for x in xs])
        ns += [lat[label][x]["p50"][3] for x in xs]
        bar = ax.errorbar(xs, p50, yerr=e50, marker="o", capsize=3, label=f"{label} p50")
        color = bar[0].get_color()
        ax.errorbar(xs, p99, yerr=e99, linestyle="--", marker=".", capsize=2, color=color, alpha=0.55,
                    label=f"{label} p99")  # fmt: skip
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Payload size (bytes)")
    ax.set_ylabel("Round-trip latency (ms)")
    ax.set_title(f"Latency vs payload size (1 client, {_runs_note(ns)}; bars = range across runs)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    p = outdir / "latency_vs_payload.png"
    fig.savefig(p, dpi=150)
    written.append(p)

    # 2. TCP throughput vs concurrent clients, one line per payload (and link).
    thr = throughput_series(rows)
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ns = []
    for label in sorted(thr, key=lambda s: (s.split(" / ")[1], int(s.split()[0]))):
        xs = sorted(thr[label])
        med, err = _errbars([thr[label][x] for x in xs])
        ns += [thr[label][x][3] for x in xs]
        ax.errorbar(xs, med, yerr=err, marker="o", capsize=3, label=label)
    ax.set_xlabel("Concurrent clients")
    ax.set_ylabel("Throughput (requests/s)")
    ax.set_title(f"TCP throughput vs concurrent clients ({_runs_note(ns)})")
    ax.set_xticks(sorted({x for s in thr.values() for x in s}))
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    p = outdir / "throughput_vs_clients.png"
    fig.savefig(p, dpi=150)
    written.append(p)
    plt.close("all")
    return written
