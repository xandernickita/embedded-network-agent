"""Latency summaries. Percentiles use linear interpolation (numpy's default), so results
match what a reader gets from the raw CSV in a spreadsheet or numpy."""

from __future__ import annotations

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return math.nan
    if not 0 <= p <= 100:
        raise ValueError("p must be in 0..100")
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize_ms(values: Sequence[float]) -> dict[str, float]:
    if not values:
        nan = math.nan
        return {"p50_ms": nan, "p95_ms": nan, "p99_ms": nan, "mean_ms": nan, "max_ms": nan}
    return {
        "p50_ms": round(percentile(values, 50), 4),
        "p95_ms": round(percentile(values, 95), 4),
        "p99_ms": round(percentile(values, 99), 4),
        "mean_ms": round(sum(values) / len(values), 4),
        "max_ms": round(max(values), 4),
    }
