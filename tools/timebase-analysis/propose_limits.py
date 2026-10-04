"""Propose Actual Warning/Critical offsets from normal running (Phase 0, ADR-0002, A-02).

    python propose_limits.py config.json [--settle-min 15] [--long-stop-min 10] [--warmup-min 30]
                                         [--low-pct 0.25] [--high-pct 99.75]

For every monitored zone this measures actual − setpoint during *routine
running*: the machine running (Machine_Run = 1), except the first
--warmup-min minutes after a stop of at least --long-stop-min minutes, and
except --settle-min minutes after each setpoint change. Short stops (jams)
don't count as warm-ups: the zones stay hot. From that it proposes offsets
around the setpoint:

* Warning: just outside routine variation, i.e. the --low-pct and --high-pct
  percentiles of (actual − setpoint), rounded outward to the parameter's step;
* Critical: twice the Warning offset.

Writes data/limits-proposed.csv (the limits.csv format of analyse_delays.py,
one row per parameter) and data/limits-report.md. These are a statistical
starting point for process engineering to confirm, not approved alarm limits.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from analyse_delays import clip, join, load_series, running_periods, to_segments
from fetch import RAW, load_config
from timebase import parse_ts

OUT = Path(__file__).parent / "data"
STEP = {"°C": 1.0, "bar": 0.05}  # rounding step per unit; others use 1


def step_for(unit: str | None) -> float:
    return STEP.get(unit or "", 1.0)


def round_out(value: float, step: float) -> float:
    """Round up to the step, and never below one step."""
    return max(step, math.ceil(value / step - 1e-9) * step)


def intersect(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if e > s:
            out.append((s, e))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return out


def settled(change_times: list[float], lo: float, hi: float, settle: float) -> list[tuple[float, float]]:
    """[lo, hi) without the `settle` seconds after each change (the carry-in counts as a change)."""
    out, start = [], lo
    for t in sorted(change_times):
        if t >= hi:
            break
        if t > start:
            out.append((start, t))
        start = max(start, t + settle)
    if start < hi:
        out.append((start, hi))
    return out


def quantiles(pairs: list[tuple[float, float]], qs: list[float]) -> list[float]:
    """Time-weighted quantiles of (value, weight) pairs."""
    pairs.sort()
    total = sum(w for _, w in pairs)
    out, acc, k = [], 0.0, 0
    for q in qs:
        target = q * total
        while k < len(pairs) - 1 and acc + pairs[k][1] < target:
            acc += pairs[k][1]
            k += 1
        out.append(pairs[k][0])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--settle-min", type=float, default=15.0)
    ap.add_argument("--long-stop-min", type=float, default=10.0)
    ap.add_argument("--warmup-min", type=float, default=30.0)
    ap.add_argument("--low-pct", type=float, default=0.25)
    ap.add_argument("--high-pct", type=float, default=99.75)
    args = ap.parse_args()
    low_q, high_q = args.low_pct / 100, args.high_pct / 100
    cfg, reg = load_config(args.config)
    good = int(cfg.get("good_quality_min", 192))
    manifest = json.loads((RAW / "manifest.json").read_text())
    lo = parse_ts(manifest["from"]).timestamp()
    hi = min(parse_ts(manifest["to"]).timestamp(), float(manifest.get("done_until") or 0) or float("inf"))
    settle = args.settle_min * 60
    run_tag = reg.context.get("machine_run")
    if not run_tag or run_tag not in manifest["tags"]:
        raise SystemExit("Machine_Run isn't in the download; run fetch.py with the register's context tags")
    run_iv = running_periods(to_segments(load_series(run_tag, good, numeric=True), lo, hi),
                             args.long_stop_min * 60, args.warmup_min * 60)

    per_zone = []
    for z in reg.zones:
        if z.setpoint not in manifest["tags"] or z.actual not in manifest["tags"]:
            continue
        sp_pts = load_series(z.setpoint, good, numeric=True)
        steady = intersect(settled([t for t, _ in sp_pts], lo, hi, settle), run_iv)
        joined = join(clip(to_segments(load_series(z.actual, good, numeric=True), lo, hi), lo, hi),
                      clip(to_segments(sp_pts, lo, hi), lo, hi))
        dev, k = [], 0
        for s, e in steady:  # both lists are sorted: walk them together
            while k < len(joined) and joined[k][1] <= s:
                k += 1
            m = k
            while m < len(joined) and joined[m][0] < e:
                a, b, x, h = joined[m]
                a2, b2 = max(a, s), min(b, e)
                if b2 > a2 and x is not None and h is not None:
                    dev.append((x - h, b2 - a2))
                m += 1
        hours = sum(w for _, w in dev) / 3600
        q = quantiles(dev, [low_q, 0.5, high_q]) if dev else [math.nan] * 3
        per_zone.append((z, hours, q))

    by_param: dict[str, list] = defaultdict(list)
    for row in per_zone:
        by_param[row[0].parameter_id].append(row)
    names = {p["id"]: p for p in reg.parameters}
    OUT.mkdir(exist_ok=True)
    rows_csv, L = [], [
        "# Proposed Actual limits (Phase 0), for process engineering to confirm", "",
        f"- Range: {manifest['from']} → {manifest['to']} (UTC, Timebase clock)",
        f"- Routine running: Machine_Run = 1, except {args.warmup_min:g} min of warm-up after stops of ≥ "
        f"{args.long_stop_min:g} min and {args.settle_min:g} min after each setpoint change",
        f"- Warning: {args.low_pct:g}th / {args.high_pct:g}th percentile of (actual − setpoint), rounded outward to the step "
        "(1 °C, 0.05 bar, 1 otherwise); Critical: 2 × Warning",
        "- Offsets are around the setpoint (A-02), one row per parameter: the widest zone sets it, so no zone "
        "raises Warnings in routine running. Written to data/limits-proposed.csv.", "",
        "| Parameter | Routine hours (all zones) | actual − setpoint: low · median · high | Warning (−/+) | Critical (−/+) |",
        "|---|---|---|---|---|"]
    for pid, rows in sorted(by_param.items()):
        p = names[pid]
        step = step_for(p.get("unit"))
        lows = [-r[2][0] for r in rows if not math.isnan(r[2][0])]
        highs = [r[2][2] for r in rows if not math.isnan(r[2][2])]
        if not lows:
            continue
        wl, wh = round_out(max(lows), step), round_out(max(highs), step)
        cl, ch = round_out(2 * wl, step), round_out(2 * wh, step)
        rows_csv.append(["*", pid, "*", f"{wl:g}", f"{wh:g}", f"{cl:g}", f"{ch:g}"])
        unit = p.get("unit") or ""
        L.append(f"| {pid} {p['name']} | {sum(r[1] for r in rows):,.0f} | "
                 f"{min(r[2][0] for r in rows):+.3g} · {sorted(r[2][1] for r in rows)[len(rows) // 2]:+.3g} · {max(highs):+.3g} {unit} | "
                 f"−{wl:g} / +{wh:g} {unit} | −{cl:g} / +{ch:g} {unit} |")
    L += ["", "## Per zone", "",
          f"| Zone | Routine hours | {args.low_pct:g}th pct | Median | {args.high_pct:g}th pct |", "|---|---|---|---|---|"]
    for z, hours, q in per_zone:
        L.append(f"| {z.channel} {z.zone_name} | {hours:,.0f} | {q[0]:+.3g} | {q[1]:+.3g} | {q[2]:+.3g} |")
    for pid in by_param:
        if names[pid].get("tag_review"):
            L += ["", f"**{pid} {names[pid]['name']}:** {names[pid]['tag_review']} The offsets' size still holds if "
                  "the tags are swapped; low and high swap sides."]
    with (OUT / "limits-proposed.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "parameter_id", "zone_id", "warn_low", "warn_high", "crit_low", "crit_high"])
        w.writerows(rows_csv)
    (OUT / "limits-report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'limits-proposed.csv'} and limits-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
