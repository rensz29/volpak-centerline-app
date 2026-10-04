"""Turn Timebase samples into step series (ADR-0008).

Timebase stores a value only when it changes, and the first sample of a read
is the value in force at the start. A value therefore holds until the next
sample: a steady temperature with no sample for 12 minutes is still known.
Every sample that fails a check (ANA-09) makes the series unknown until the
next sample, and each failure is counted by reason.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from centerline_common.historian import UNREADABLE_Q, Sample


@dataclass
class Exclusions:
    samples: int = 0  # samples that affect the range, including the carry-in
    bad_quality: int = 0
    null: int = 0
    non_numeric: int = 0
    nan: int = 0
    infinite: int = 0
    out_of_range: int = 0
    unreadable_s: float = 0.0  # time Timebase couldn't return
    gap_s: float = 0.0  # time the machine area sent nothing (heartbeat)

    def as_dict(self) -> dict:
        return {"samples": self.samples, "badQuality": self.bad_quality, "null": self.null,
                "nonNumeric": self.non_numeric, "nan": self.nan, "infinite": self.infinite,
                "outOfRange": self.out_of_range, "unreadableSeconds": round(self.unreadable_s, 1),
                "gapSeconds": round(self.gap_s, 1)}


@dataclass
class StepSeries:
    """Value vals[i] holds on [starts[i], ends[i]); NaN means unknown. Covers [lo, hi) without holes."""

    starts: np.ndarray
    ends: np.ndarray
    vals: np.ndarray


def _classify(s: Sample, good_min: int, valid: tuple[float, float] | None, ex: Exclusions) -> float:
    """The sample's value, or NaN after counting why it can't be used."""
    if s.q < good_min:
        ex.bad_quality += 1
        return math.nan
    v = s.v
    if v is None or v == "":
        ex.null += 1
        return math.nan
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        ex.non_numeric += 1
        return math.nan
    v = float(v)
    if math.isnan(v):
        ex.nan += 1
        return math.nan
    if math.isinf(v):
        ex.infinite += 1
        return math.nan
    if valid and not (valid[0] <= v <= valid[1]):
        ex.out_of_range += 1
        return math.nan
    return v


def build_series(samples: list[Sample], lo: float, hi: float, *, good_min: int = 192,
                 valid: tuple[float, float] | None = None) -> tuple[StepSeries, Exclusions]:
    ex = Exclusions()
    pts = sorted(samples, key=lambda s: s.t)
    times = [s.t.timestamp() for s in pts]
    # Only the last sample before `lo` (the carry-in) and the samples inside the range matter.
    first = max(0, sum(1 for t in times if t < lo) - 1)
    starts, ends, vals = [], [], []
    if not pts or times[first] > lo:
        starts.append(lo)
        ends.append(min(hi, times[first]) if pts else hi)
        vals.append(math.nan)
    for i in range(first, len(pts)):
        a = max(times[i], lo)
        b = min(times[i + 1] if i + 1 < len(pts) else hi, hi)
        if a >= hi:
            break
        if pts[i].q == UNREADABLE_Q:
            v = math.nan
            ex.unreadable_s += max(0.0, b - a)
        else:
            ex.samples += 1
            v = _classify(pts[i], good_min, valid, ex)
        if b > a:
            starts.append(a)
            ends.append(b)
            vals.append(v)
    return StepSeries(np.array(starts, float), np.array(ends, float), np.array(vals, float)), ex


def heartbeat_gaps(arrivals, lo: float, hi: float, gap_s: float) -> list[tuple[float, float]]:
    """Spans in [lo, hi) where a machine area sent nothing for longer than gap_s.

    `arrivals` are epoch seconds of the area's `_timestamp` samples: every
    message from an area carries it, so its Timebase samples are the message
    arrivals. After gap_s of silence the area's values stop counting until the
    next message.
    """
    t = np.sort(np.asarray(arrivals, dtype=float))
    if t.size == 0:
        return [(lo, hi)]
    t = np.concatenate([t[t < lo][-1:], t[(t >= lo) & (t < hi)]])
    edges = np.concatenate([t, [hi]])
    out = []
    if edges[0] > lo:  # nothing before the range: unknown until the first message
        out.append((lo, float(edges[0])))
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a > gap_s:
            s, e = max(a + gap_s, lo), min(b, hi)
            if e > s:
                out.append((float(s), float(e)))
    return out


def mask(series: StepSeries, spans: list[tuple[float, float]], ex: Exclusions | None = None) -> StepSeries:
    """The same series with every span in `spans` set to unknown."""
    if not spans:
        return series
    iv = np.array(sorted(spans), float)
    lo, hi = series.starts[0], series.ends[-1]
    edges = np.union1d(np.concatenate([series.starts, [hi]]), iv.ravel())
    edges = edges[(edges >= lo) & (edges <= hi)]
    a, b = edges[:-1], edges[1:]
    vals = series.vals[np.searchsorted(series.starts, a, side="right") - 1].copy()
    k = np.searchsorted(iv[:, 0], a, side="right") - 1
    inside = (k >= 0) & (a < iv[np.clip(k, 0, None), 1])
    if ex is not None:
        ex.gap_s += float(np.sum((b - a)[inside & ~np.isnan(vals)]))
    vals[inside] = np.nan
    return StepSeries(a, b, vals)
