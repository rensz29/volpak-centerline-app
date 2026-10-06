"""Expected results for AT-ANA-01…10, calculated independently of the api (ADR-0029).

    python independent.py      # after dataset.py: rewrites expected.json and the spreadsheet files

Written from the URS (ANA-06…19) and SDD §9.1–9.2, not from the api's code. It uses Python's standard library only:
exact fractions for times (they're on a 1/8 s grid) and 50-digit decimals for values and statistics, about 35 digits
more than the api's numpy and 64-bit floats. Where the documents are silent, the choice is written next to the code.

The rules, as the documents give them:
- A value holds from its sample until the next one (Timebase stores on change); the first one in force is the
  value at the range's start. A sample with bad quality (below 192), null, not a number, NaN, infinite, or outside
  its parameter's Analytics-valid range makes the value unknown until the next sample, and is counted by reason.
  A sample counts when it's in force for some part of the range.
- A machine area that sends nothing for more than 120 s is a data gap from 120 s after its last message until the
  next one; so is the time before its first message. Its values are unknown then.
- Buckets start at floor(t ÷ width) × width (UTC seconds). A bucket counts when at least half of it is known: AVG
  is the time-weighted average of the known part, MIN and MAX the smallest and largest value in force on it.
- A pair needs both buckets valid, and the bucket in the chosen shift (from its start's Manila time).
- Pearson r, least squares y = a + b·x, R², and for each variable n, min, max, mean and the sample standard
  deviation (n − 1). Fewer than 3 pairs, or a constant variable: not computable.
- More than 10,000 pairs: no result; recommend the smallest larger bucket that fits.
- Groups by shift or production date (the Manila date the shift started), the 10 most recent shown; fewer than
  3 pairs is insufficient data, 3–29 a low sample size.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from fractions import Fraction
from pathlib import Path

from dataset import arrivals

HERE = Path(__file__).resolve().parent
getcontext().prec = 50
GOOD_QUALITY, GAP_S, MIN_COVERAGE, PAIR_LIMIT, VISIBLE_GROUPS = 192, 120, Fraction(1, 2), 10_000, 10
BUCKETS = {"PT10S": 10, "PT30S": 30, "PT1M": 60, "PT5M": 300, "PT15M": 900, "PT1H": 3600}
MANILA = timezone(timedelta(hours=8))

# The queries the suite runs; "pairs" keeps every pair in the expected results
DENSE_COMBOS = [(b, a) for b in BUCKETS for a in ("AVG", "MIN", "MAX")]
QUERIES = {
    **{f"dense-{b}-{a}": {"window": "dense", "bucket": b, "aggregation": a, "shift": "ALL", "groupBy": "NONE",
                          "pairs": (b, a) == ("PT1M", "AVG")} for b, a in DENSE_COMBOS},
    "dense-PT1M-AVG-shift-A": {"window": "dense", "bucket": "PT1M", "aggregation": "AVG", "shift": "A", "groupBy": "NONE"},
    "dense-PT1M-AVG-by-shift": {"window": "dense", "bucket": "PT1M", "aggregation": "AVG", "shift": "ALL", "groupBy": "SHIFT",
                                "groupStats": True},
    "days-PT15M-AVG-by-date": {"window": "days", "bucket": "PT15M", "aggregation": "AVG", "shift": "ALL",
                               "groupBy": "PRODUCTION_DATE", "groupStats": True},
    "days-PT10S-AVG": {"window": "days", "bucket": "PT10S", "aggregation": "AVG", "shift": "ALL", "groupBy": "NONE"},
}


def F(t) -> Fraction:
    return Fraction(t)  # a time: exact, since every time is on the 1/8 s grid


def D(v) -> Decimal:
    """A value (a float's exact binary value: the number the api reads), or a time span, as a decimal."""
    return Decimal(v.numerator) / Decimal(v.denominator) if isinstance(v, Fraction) else Decimal(v)


def ranges() -> dict[str, tuple[Decimal, Decimal]]:
    with (HERE / "ranges.csv").open(encoding="utf-8") as f:
        return {r["parameter_id"]: (D(float(r["valid_min"])), D(float(r["valid_max"]))) for r in csv.DictReader(f)}


# -- step series --------------------------------------------------------------------------------------------------

def classify(value, quality: int, valid: tuple[Decimal, Decimal]) -> tuple[Decimal | None, str | None]:
    if quality < GOOD_QUALITY:
        return None, "badQuality"
    if value is None or value == "":
        return None, "null"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "nonNumeric"
    if math.isnan(value):
        return None, "nan"
    if math.isinf(value):
        return None, "infinite"
    v = D(value)
    if not valid[0] <= v <= valid[1]:
        return None, "outOfRange"
    return v, None


def series(samples: list, lo: Fraction, hi: Fraction, valid) -> tuple[list[tuple[Fraction, Fraction, Decimal | None]], dict]:
    """[(start, end, value or None)] covering [lo, hi), and the exclusion counts."""
    counts = dict.fromkeys(("samples", "badQuality", "null", "nonNumeric", "nan", "infinite", "outOfRange"), 0)
    pts = sorted(samples, key=lambda s: s[0])
    out = []
    first_t = F(pts[0][0]) if pts else hi
    if first_t > lo:
        out.append((lo, min(first_t, hi), None))  # nothing in force yet
    for i, (t, value, q) in enumerate(pts):
        a = max(F(t), lo)
        b = min(F(pts[i + 1][0]) if i + 1 < len(pts) else hi, hi)
        if b <= a:
            continue  # never in force inside the range: it doesn't count
        counts["samples"] += 1
        v, why = classify(value, q, valid)
        if why:
            counts[why] += 1
        out.append((a, b, v))
    return out, counts


def gaps(times: list[float], lo: Fraction, hi: Fraction) -> list[tuple[Fraction, Fraction]]:
    t = sorted(F(x) for x in times)
    before = [x for x in t if x < lo][-1:]
    inside = [x for x in t if lo <= x < hi]
    pts = before + inside
    if not pts:
        return [(lo, hi)]
    spans = []
    if pts[0] > lo:
        spans.append((lo, pts[0]))
    for a, b in zip(pts, pts[1:] + [hi]):
        if b - a > GAP_S:
            s, e = max(a + GAP_S, lo), min(b, hi)
            if e > s:
                spans.append((s, e))
    return spans


def mask(segs, spans) -> tuple[list, Fraction]:
    """Unknown inside every span; also the known time the spans removed."""
    out, removed = [], Fraction(0)
    for a, b, v in segs:
        cuts = sorted({a, b} | {x for s, e in spans for x in (s, e) if a < x < b})
        for p, q in zip(cuts, cuts[1:]):
            inside = any(s <= p and q <= e for s, e in spans)
            if inside and v is not None:
                removed += q - p
            out.append((p, q, None if inside else v))
    return out, removed


# -- buckets, pairs and statistics -----------------------------------------------------------------------------------

def bucket_values(segs, lo: Fraction, hi: Fraction, width: int, how: str) -> list[tuple[Fraction, Decimal | None]]:
    """One sweep: the segments are in order and cover [lo, hi) without holes."""
    out, i = [], 0
    start = Fraction(math.floor(lo / width) * width)
    while start < hi:
        end = start + width
        while i < len(segs) and segs[i][1] <= start:
            i += 1
        known, area, seen, j = Fraction(0), Decimal(0), [], i
        while j < len(segs) and segs[j][0] < end:
            a, b, v = segs[j]
            overlap = min(b, end) - max(a, start)
            if v is not None and overlap > 0:
                known += overlap
                area += v * D(overlap)
                seen.append(v)
            j += 1
        if known / width >= MIN_COVERAGE:
            value = area / D(known) if how == "AVG" else min(seen) if how == "MIN" else max(seen)
        else:
            value = None
        out.append((start, value))
        start = end
    return out


def manila(t: Fraction) -> datetime:
    return datetime.fromtimestamp(float(t), MANILA)


def shift_of(t: Fraction) -> str:
    h = manila(t).hour
    return "A" if 6 <= h < 14 else "B" if 14 <= h < 22 else "C"


def production_date(t: Fraction) -> str:
    m = manila(t)
    return (m.date() - timedelta(days=1 if m.hour < 6 else 0)).isoformat()


def sqrt(q: Decimal) -> Decimal:
    return q.sqrt()


def strength(r: Decimal) -> str:
    a = abs(r)
    for limit, label in ((Decimal("0.20"), "very weak/none"), (Decimal("0.40"), "weak"), (Decimal("0.70"), "moderate"),
                         (Decimal("0.90"), "strong")):
        if a < limit:
            return label
    return "very strong"


def describe(vals: list[Decimal]) -> dict:
    n = len(vals)
    if n == 0:
        return {"n": 0, "min": None, "max": None, "mean": None, "sd": None}
    mean = sum(vals, Decimal(0)) / n
    ss = sum(((v - mean) ** 2 for v in vals), Decimal(0))
    return {"n": n, "min": float(min(vals)), "max": float(max(vals)), "mean": float(mean),
            "sd": float(sqrt(ss / (n - 1))) if n > 1 else None}


def correlate(xs: list[Decimal], ys: list[Decimal]) -> dict:
    n = len(xs)
    if n < 3:
        return {"n": n, "computable": False}
    mx, my = sum(xs, Decimal(0)) / n, sum(ys, Decimal(0)) / n
    sxx = sum(((x - mx) ** 2 for x in xs), Decimal(0))
    syy = sum(((y - my) ** 2 for y in ys), Decimal(0))
    sxy = sum(((x - mx) * (y - my) for x, y in zip(xs, ys)), Decimal(0))
    if sxx == 0 or syy == 0:
        return {"n": n, "computable": False}
    r = sxy / sqrt(sxx * syy)
    slope = sxy / sxx
    return {"n": n, "computable": True, "r": float(r), "rSquared": float(sxy * sxy / (sxx * syy)), "slope": float(slope),
            "intercept": float(my - slope * mx), "strength": strength(r),
            "direction": "positive" if r > 0 else "negative" if r < 0 else "none"}


def run(data: dict, q: dict, valid: dict) -> dict:
    lo, hi = (F(t) for t in data["windows"][q["window"]])
    sides, excluded = {}, {}
    for side in ("x", "y"):
        v = data[side]
        segs, counts = series(v["samples"], lo, hi, valid[v["parameter"]])
        segs, removed = mask(segs, gaps(arrivals(data["heartbeats"][v["area"]]), lo, hi))
        counts["gapSeconds"] = round(float(removed), 1)
        sides[side], excluded[side] = segs, counts

    def pairs_for(width: int):
        bx = bucket_values(sides["x"], lo, hi, width, q["aggregation"])
        by = bucket_values(sides["y"], lo, hi, width, q["aggregation"])
        both = [(t, x, y) for (t, x), (_, y) in zip(bx, by) if x is not None and y is not None]
        return bx, by, both, [p for p in both if q["shift"] == "ALL" or shift_of(p[0]) == q["shift"]]

    width = BUCKETS[q["bucket"]]
    bx, by, both, paired = pairs_for(width)
    out = {"buckets": {"total": len(bx), "xValid": sum(x is not None for _, x in bx), "yValid": sum(y is not None for _, y in by),
                       "bothValid": len(both), "outsideShift": len(both) - len(paired), "paired": len(paired)},
           "exclusions": excluded, "sizeGuard": {"exceeded": False, "recommendedBucket": None}}
    if len(paired) > PAIR_LIMIT:
        bigger = [b for b, w in BUCKETS.items() if w > width]
        out["sizeGuard"] = {"exceeded": True, "recommendedBucket": next(
            (b for b in bigger if len(pairs_for(BUCKETS[b])[3]) <= PAIR_LIMIT), None)}
        return out
    xs, ys = [p[1] for p in paired], [p[2] for p in paired]
    out["statistics"] = {"correlation": correlate(xs, ys), "x": describe(xs), "y": describe(ys)}
    if q["groupBy"] != "NONE":
        keyed = [(shift_of(t) if q["groupBy"] == "SHIFT" else production_date(t), x, y) for t, x, y in paired]
        keys = sorted({k for k, _, _ in keyed})
        visible = keys[-VISIBLE_GROUPS:]
        items = []
        for k in visible:
            gx, gy = [x for kk, x, _ in keyed if kk == k], [y for kk, _, y in keyed if kk == k]
            n = len(gx)
            g = {"key": k, "n": n, "warning": "INSUFFICIENT_DATA" if n < 3 else "LOW_SAMPLE_SIZE" if n < 30 else None}
            if q.get("groupStats") and n >= 3:
                g["correlation"] = correlate(gx, gy)
            items.append(g)
        out["groups"] = {"by": q["groupBy"], "items": items, "hidden": len(keys) - len(visible)}
    if q.get("pairs"):
        out["pairs"] = {"t": [int(t * 1000) for t, _, _ in paired], "x": [float(x) for _, x, _ in paired],
                        "y": [float(y) for _, _, y in paired]}
    return out


def main() -> None:
    data = json.loads((HERE / "dataset.json").read_text(encoding="utf-8"))
    valid = ranges()
    expected = {"queries": QUERIES, "results": {name: run(data, q, valid) for name, q in QUERIES.items()},
                "variables": {"x": data["x"]["channel"], "y": data["y"]["channel"]},
                "windows": {k: [datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z") for t in v]
                            for k, v in data["windows"].items()}}
    (HERE / "expected.json").write_text(json.dumps(expected, indent=1) + "\n", encoding="utf-8")
    # For a spreadsheet check: CORREL, SLOPE, INTERCEPT, RSQ, AVERAGE, STDEV.S on these columns give the results
    pairs = expected["results"]["dense-PT1M-AVG"]["pairs"]
    with (HERE / "expected-pairs-dense-PT1M-AVG.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bucket_start_manila", data["x"]["channel"], data["y"]["channel"]])
        for t, x, y in zip(pairs["t"], pairs["x"], pairs["y"]):
            w.writerow([manila(Fraction(t, 1000)).strftime("%Y-%m-%d %H:%M:%S"), repr(x), repr(y)])
    print("expected.json and expected-pairs-dense-PT1M-AVG.csv written")


if __name__ == "__main__":
    main()
