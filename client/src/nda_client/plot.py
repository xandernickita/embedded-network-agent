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


# Colours from a validated palette (light surface, colour-blind-safe for 3 categories):
# a link keeps its colour on every chart; payload size, an ordered quantity, is one hue
# from light (small) to dark (large).
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
LINK_COLORS = {"ethernet": "#2a78d6", "wifi": "#eb6834", "tailscale": "#1baf7a"}
FALLBACK_COLORS = ["#6250d6", "#008300", "#e34948"]  # further links, fixed order
PAYLOAD_RAMP = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
LINK_ORDER = ["ethernet", "wifi", "tailscale"]


def _link_order(links: Iterable[str]) -> list[str]:
    links = set(links)
    return [k for k in LINK_ORDER if k in links] + sorted(links - set(LINK_ORDER))


def _link_color(link: str, ordered: list[str]) -> str:
    if link in LINK_COLORS:
        return LINK_COLORS[link]
    extras = [k for k in ordered if k not in LINK_COLORS]
    return FALLBACK_COLORS[extras.index(link) % len(FALLBACK_COLORS)]


def _runs_note(n_values: Iterable[int]) -> str:
    ns = sorted(set(n_values))
    if not ns or ns == [1]:
        return "single run"
    return f"median of {ns[0]} runs" if len(ns) == 1 else f"median of {ns[0]}-{ns[-1]} runs"


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK_2, labelsize=9)


def _place_end_labels(ax, labels: list[tuple[float, float, str, str]], min_gap_pt: float = 13.0) -> None:
    """Label each line at its last point, nudging labels apart vertically so none overlap."""
    if not labels:
        return
    fig = ax.figure
    fig.canvas.draw()  # final limits/scales, so data -> display is exact
    to_pt = 72.0 / fig.dpi
    placed = sorted(((ax.transData.transform((x, y))[1] * to_pt, x, y, t, c) for x, y, t, c in labels))
    ys: list[float] = []
    for y_pt, *_ in placed:
        ys.append(max(y_pt, ys[-1] + min_gap_pt) if ys else y_pt)
    for (y_pt, x, y, text, color), target in zip(placed, ys, strict=True):
        ax.annotate(text, (x, y), xytext=(8, target - y_pt), textcoords="offset points", va="center",
                    fontsize=8.5, color=INK_2, annotation_clip=False,
                    bbox={"boxstyle": "round,pad=0.15", "fc": SURFACE, "ec": color, "lw": 1})  # fmt: skip


def plot(csv_paths: Path | list[Path], outdir: Path | None = None) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    paths = [csv_paths] if isinstance(csv_paths, Path) else list(csv_paths)
    rows = load(paths)
    outdir = outdir or paths[0].parent
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK_2})

    # 1. Latency vs payload: one panel per transport, colour = link, solid = p50, dashed = p99.
    lat = latency_series(rows)
    transports = [t for t in ("TCP", "UDP") if any(k.startswith(t + " / ") for k in lat)]
    links = _link_order(k.split(" / ")[1] for k in lat)
    fig, axes = plt.subplots(1, len(transports), figsize=(10, 4.6), sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    ns: list[int] = []
    panel_labels = []
    for ax, transport in zip(axes[0], transports, strict=True):
        _style(ax)
        end_labels: list[tuple[float, float, str, str]] = []
        panel_labels.append((ax, end_labels))
        for link in links:
            series = lat.get(f"{transport} / {link}")
            if not series:
                continue
            color = _link_color(link, links)
            xs = sorted(series)
            p50 = [series[x]["p50"] for x in xs]
            p99 = [series[x]["p99"] for x in xs]
            ns += [a[3] for a in p50]
            med = [a[0] for a in p50]
            err = [[a[0] - a[1] for a in p50], [a[2] - a[0] for a in p50]]
            ax.errorbar(xs, med, yerr=err, color=color, lw=2, marker="o", ms=6, capsize=3, elinewidth=1,
                        mec=SURFACE, mew=1.5, zorder=3)  # fmt: skip
            ax.plot(xs, [a[0] for a in p99], color=color, lw=1.5, ls="--", marker="o", ms=4, alpha=0.8, zorder=2)
            end_labels.append((xs[-1], med[-1], link, color))
        ax.set_xscale("log", base=2)
        # Tick the shared sizes only; per-link MTU maxima (1252 Tailscale, 1472 LAN) sit too
        # close to label separately, so they share one tick labelled as the MTU limit.
        sizes = sorted({x for k, v in lat.items() if k.startswith(transport) for x in v})
        common = [x for x in sizes if x <= 1024 or x == 4096]
        ax.set_xticks(common + ([max(sizes)] if max(sizes) not in common else []))
        largest = max(sizes)
        if largest not in common:
            note = "max unfragmented\n(1252 tunnel, 1472 LAN)"
            ax.text(largest, -0.11, note, transform=ax.get_xaxis_transform(), ha="center", va="top",
                    fontsize=7, color=MUTED)  # fmt: skip

        def size_label(v, _pos, largest=largest, common=tuple(common)):
            return "" if v == largest and v not in common else f"{int(v)}"

        ax.xaxis.set_major_formatter(FuncFormatter(size_label))
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlim(right=ax.get_xlim()[1] * 1.6)  # room for end labels
        ax.set_title(f"{transport} echo", fontsize=11, color=INK, loc="left")
        ax.set_xlabel("Payload size (bytes)", fontsize=9.5)
    axes[0][0].set_yscale("log")
    axes[0][0].yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
    axes[0][0].yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    axes[0][0].yaxis.set_minor_formatter(NullFormatter())
    axes[0][0].set_ylabel("Round-trip latency (ms, log scale)", fontsize=9.5)
    handles = [Line2D([], [], color=_link_color(k, links), lw=2, marker="o", label=k) for k in links]
    handles += [Line2D([], [], color=INK_2, lw=2, label="p50 (bars: range across runs)"),
                Line2D([], [], color=INK_2, lw=1.5, ls="--", label="p99")]  # fmt: skip
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), frameon=False, fontsize=8.5,
               bbox_to_anchor=(0.5, 0.93))  # fmt: skip
    fig.suptitle(f"Latency vs payload size, 1 client ({_runs_note(ns)})", x=0.01, ha="left", fontsize=12.5)
    fig.tight_layout(rect=(0, 0.03, 1, 0.88))
    for ax, end_labels in panel_labels:
        _place_end_labels(ax, end_labels)
    p = outdir / "latency_vs_payload.png"
    fig.savefig(p, dpi=150, facecolor=SURFACE)
    written.append(p)

    # 2. TCP throughput vs clients: one panel per link (shared y), line per payload (ordered ramp).
    thr = throughput_series(rows)
    links = _link_order(k.split(" / ")[1] for k in thr)
    payloads = sorted({int(k.split()[0]) for k in thr})
    ramp = PAYLOAD_RAMP if len(payloads) <= len(PAYLOAD_RAMP) else None
    fig, axes = plt.subplots(1, max(len(links), 1), figsize=(10, 4.4), sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    ns = []
    for ax, link in zip(axes[0], links, strict=True):
        _style(ax)
        for i, payload in enumerate(payloads):
            series = thr.get(f"{payload} B / {link}")
            if not series:
                continue
            color = ramp[len(ramp) - len(payloads) + i] if ramp else None
            xs = sorted(series)
            med = [series[x][0] for x in xs]
            err = [[series[x][0] - series[x][1] for x in xs], [series[x][2] - series[x][0] for x in xs]]
            ns += [series[x][3] for x in xs]
            ax.errorbar(xs, med, yerr=err, color=color, lw=2, marker="o", ms=6, capsize=3, elinewidth=1,
                        mec=SURFACE, mew=1.5, label=f"{payload} B")  # fmt: skip
        ax.set_xticks(sorted({x for v in thr.values() for x in v}))
        ax.set_title(link, fontsize=11, color=INK, loc="left")
        ax.set_xlabel("Concurrent clients", fontsize=9.5)
    axes[0][0].set_ylabel("Requests per second (median)", fontsize=9.5)
    axes[0][0].set_ylim(bottom=0)
    h, lbl = axes[0][0].get_legend_handles_labels()
    fig.legend(h, lbl, title="Payload", loc="upper center", ncol=len(lbl), frameon=False, fontsize=8.5,
               title_fontsize=8.5, bbox_to_anchor=(0.5, 0.93))  # fmt: skip
    fig.suptitle(f"TCP throughput vs concurrent clients ({_runs_note(ns)}; bars: range across runs)",
                 x=0.01, ha="left", fontsize=12.5)  # fmt: skip
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    p = outdir / "throughput_vs_clients.png"
    fig.savefig(p, dpi=150, facecolor=SURFACE)
    written.append(p)
    plt.close("all")
    return written
