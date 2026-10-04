"""Fixed-bucket aggregation of step series (ANA-06, ANA-07, ADR-0008).

Buckets start at floor(UTC seconds ÷ width) × width. A bucket's value comes
from the values *in force* during it, not only the samples that happen to land
in it, because Timebase stores on change:

* AVG: time-weighted average over the known part of the bucket;
* MIN / MAX: smallest / largest value in force during the known part.

A bucket counts only when at least `min_coverage` of it is known; otherwise it
is missing, never zero (ANA-08). Everything is vectorised: a 30-day range at
10 s is 259,200 buckets.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .series import StepSeries


@dataclass
class Buckets:
    start: np.ndarray  # bucket start, epoch seconds
    value: np.ndarray  # NaN = missing
    coverage: np.ndarray  # known share of the bucket, 0…1


def bucket_starts(lo: float, hi: float, width: int) -> np.ndarray:
    first = np.floor(lo / width) * width
    return np.arange(first, hi, width, dtype=float)


def aggregate(series: StepSeries, lo: float, hi: float, width: int, how: str,
              min_coverage: float = 0.5) -> Buckets:
    starts, ends, vals = series.starts, series.ends, series.vals
    b0 = bucket_starts(lo, hi, width)
    edges = np.concatenate([b0, [b0[-1] + width]]) if b0.size else np.array([lo, hi])
    known = ~np.isnan(vals)
    lengths = ends - starts
    ref = float(np.median(vals[known])) if known.any() else 0.0  # centring keeps the integrals small
    dv = np.where(known, vals - ref, 0.0)
    cum_f = np.concatenate([[0.0], np.cumsum(dv * lengths)])
    cum_k = np.concatenate([[0.0], np.cumsum(known * lengths)])

    idx = np.searchsorted(starts, edges, side="right") - 1
    ic = np.clip(idx, 0, len(starts) - 1)
    within = np.clip(edges - starts[ic], 0.0, lengths[ic])
    f = np.where(idx < 0, 0.0, cum_f[ic] + within * dv[ic])
    k = np.where(idx < 0, 0.0, cum_k[ic] + within * known[ic])
    known_s = np.diff(k)
    coverage = np.clip(known_s / width, 0.0, 1.0)
    ok = coverage >= min_coverage

    if how == "AVG":
        with np.errstate(invalid="ignore", divide="ignore"):
            value = ref + np.diff(f) / known_s
    elif how in ("MIN", "MAX"):
        # Segments overlapping bucket j run from the one holding its start to the last one starting before its end.
        i0 = np.clip(np.searchsorted(starts, edges[:-1], side="right") - 1, 0, len(starts) - 1)
        i1 = np.clip(np.searchsorted(starts, edges[1:], side="left") - 1, i0, len(starts) - 1)
        fill = np.inf if how == "MIN" else -np.inf
        arr = np.append(np.where(known, vals, fill), fill)
        pairs = np.empty(2 * len(i0), dtype=np.int64)
        pairs[0::2], pairs[1::2] = i0, i1 + 1
        ufunc = np.minimum if how == "MIN" else np.maximum
        value = ufunc.reduceat(arr, pairs)[0::2] if len(i0) else np.array([])
        value = np.where(np.isfinite(value), value, np.nan)
    else:
        raise ValueError(f"unknown aggregation {how!r}")
    return Buckets(b0, np.where(ok, value, np.nan), coverage)


# -- shift and production date (A-07, ANA-16) --------------------------------------

MANILA_OFFSET_S = 8 * 3600  # Asia/Manila is UTC+8 all year


def shift_of(bucket_start: np.ndarray) -> np.ndarray:
    """'A' 06:00–14:00, 'B' 14:00–22:00, 'C' 22:00–06:00 Manila. Buckets ≤ 1 h never straddle a boundary."""
    hour = ((bucket_start + MANILA_OFFSET_S) % 86400) // 3600
    return np.where((hour >= 6) & (hour < 14), "A", np.where((hour >= 14) & (hour < 22), "B", "C"))


def production_date(bucket_start: np.ndarray) -> np.ndarray:
    """Manila date on which the bucket's shift started: the 22:00 shift belongs to its start date."""
    local = bucket_start + MANILA_OFFSET_S
    hour = (local % 86400) // 3600
    day = ((local // 86400) - (hour < 6)).astype(np.int64)
    return np.datetime_as_string(day.astype("datetime64[D]"))
