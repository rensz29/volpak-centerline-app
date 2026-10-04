"""Measure off-target dwell times from Timebase history and propose delays (O-08).

    python analyse_delays.py config.json [--targets targets.csv] [--limits limits.csv]

Reads data/raw/ (written by fetch.py) and the parameter register, and writes
data/delay-report.md. Each zone ("channel", e.g. P02.V3) is analysed on its
own with the SDD rules, then rolled up per parameter and for the line:

* HMI mismatch (HMI-01, HMI-03): setpoint and target are compared with the
  parameter's HMI rule (URS default: truncate to whole numbers). The delay
  restarts whenever a *new* off-target value appears, so the quantity that
  matters is the dwell at one off-target value. For each candidate delay the
  report shows how many events a day it would raise and how many brief changes
  it would absorb.
* Actual severity (ACT-01, A-02): only with --limits, because limits are
  offsets around the setpoint that live in configuration, not in Timebase.
  Without limits the report still gives the |actual − setpoint| spread.
* Runs: while the SKU tag isn't published (ADR-0007), every shift
  (06:00 / 14:00 / 22:00 Manila) is a run and its target is inferred as the
  value held longest. Once the SKU tag exists, runs follow the SKU and the
  changeover analysis for ADR-0001 appears.

targets.csv: sku,parameter_id,zone_id,target   sku and zone_id may be '*'
limits.csv:  sku,parameter_id,zone_id,warn_low,warn_high,crit_low,crit_high
             offsets from the setpoint, all positive; sku and zone_id may be '*'

Series are sample-and-hold. A sample below good_quality_min, a non-numeric
value, or a span the server couldn't return (gaps.csv) is unknown. A dwell that
ends in unknown data or at the end of a run is *censored*, because the real
system would have paused or closed it.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fetch import MANILA, RAW, load_config, safe_name
from timebase import parse_ts

OUT = Path(__file__).parent / "data"
CANDIDATES_S = [5, 10, 15, 30, 60, 120, 300, 600]
RECOVERY_DELAY_S = 15  # the only delay the URS fixes
LIVE_SETPOINT_PER_DAY = 100  # more setpoint changes than this looks like a live value, not an HMI setting


@dataclass
class Seg:
    a: float  # start, epoch seconds
    b: float  # end
    v: object  # None = unknown


@dataclass
class Dwell:
    start: float
    length: float
    ended_by: str  # 'target' | 'other' | 'censored'
    changeover: bool = False  # setpoint not yet dialled to the new SKU's target


# -- loading -----------------------------------------------------------------


def load_series(tag: str, good_min: int, numeric: bool) -> list[tuple[float, object]]:
    path = RAW / f"{safe_name(tag)}.csv"
    if not path.exists():
        raise SystemExit(f"missing {path}; run fetch.py first")
    pts = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            v: object = row["v"]
            if int(row["q"]) < good_min or v == "":
                v = None
            elif numeric:
                try:
                    v = float(v)
                    if not math.isfinite(v):
                        v = None
                except ValueError:
                    v = None
            else:
                v = v.strip()
            pts.append((parse_ts(row["t"]).timestamp(), v))
    pts.sort(key=lambda p: p[0])
    return pts


def to_segments(pts, lo: float, hi: float) -> list[Seg]:
    """Sample-and-hold segments clipped to [lo, hi); before the first sample is unknown."""
    segs: list[Seg] = []
    if not pts or pts[0][0] > lo:
        segs.append(Seg(lo, min(hi, pts[0][0]) if pts else hi, None))
    for i, (t, v) in enumerate(pts):
        a = max(t, lo)
        b = min(pts[i + 1][0] if i + 1 < len(pts) else hi, hi)
        if b > a:
            segs.append(Seg(a, b, v))
    return merge(segs)


def merge(segs: list[Seg]) -> list[Seg]:
    out: list[Seg] = []
    for s in segs:
        if out and out[-1].v == s.v and out[-1].b == s.a:
            out[-1].b = s.b
        else:
            out.append(Seg(s.a, s.b, s.v))
    return out


def clip(segs: list[Seg], lo: float, hi: float) -> list[Seg]:
    starts = [s.a for s in segs]
    i = max(0, bisect_right(starts, lo) - 1)
    out = []
    while i < len(segs) and segs[i].a < hi:
        s = segs[i]
        a, b = max(s.a, lo), min(s.b, hi)
        if b > a:
            out.append(Seg(a, b, s.v))
        i += 1
    return out


def _lookup(table: dict, sku: str, pid: str, zid: str):
    for key in ((sku, pid, zid), (sku, pid, "*"), ("*", pid, zid), ("*", pid, "*")):
        if key in table:
            return table[key]
    return None


def load_targets(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        return {(r["sku"].strip(), r["parameter_id"].strip(), (r.get("zone_id") or "*").strip()): float(r["target"])
                for r in csv.DictReader(f)}


def load_limits(path: str | None) -> dict:
    if not path:
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vals = tuple(abs(float(r[k])) for k in ("warn_low", "warn_high", "crit_low", "crit_high"))
            if vals[2] < vals[0] or vals[3] < vals[1]:
                raise SystemExit(f"limits for {r['parameter_id']}: Critical offset must be ≥ Warning offset")
            out[(r["sku"].strip(), r["parameter_id"].strip(), (r.get("zone_id") or "*").strip())] = vals
    return out


def load_gaps() -> dict[str, float]:
    path = RAW / "gaps.csv"
    out: dict[str, float] = defaultdict(float)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["tag"]] += parse_ts(r["to"]).timestamp() - parse_ts(r["from"]).timestamp()
    return out


# -- runs --------------------------------------------------------------------


def shift_runs(lo: float, hi: float) -> list[Seg]:
    """Shift instances (06:00, 14:00, 22:00 Manila); the 22:00 shift belongs to its start date (A-07)."""
    day = datetime.fromtimestamp(lo, MANILA).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    out = []
    while day.timestamp() < hi:
        for hour, letter in ((6, "A"), (14, "B"), (22, "C")):
            a = day.replace(hour=hour)
            s, e = max(a.timestamp(), lo), min((a + timedelta(hours=8)).timestamp(), hi)
            if e > s:
                out.append(Seg(s, e, f"{a:%Y-%m-%d} shift {letter}"))
        day += timedelta(days=1)
    return out


# -- rules (same semantics as monitor_core/rules) ------------------------------


def classify(x: float, sp: float, off: tuple[float, float, float, float]) -> str:
    """Boundaries belong to the milder state (ACT-01); limits are offsets around the setpoint (A-02)."""
    if sp - off[0] <= x <= sp + off[1]:
        return "N"
    if sp - off[2] <= x <= sp + off[3]:
        return "W"
    return "C"


def inferred_target(sp: list[Seg], key) -> int | None:
    held: Counter = Counter()
    for s in sp:
        if s.v is not None:
            held[key(s.v)] += s.b - s.a
    return held.most_common(1)[0][0] if held else None


def hmi_dwells(sp: list[Seg], target: int, key, after_change: bool) -> list[Dwell]:
    """Dwells at one off-target value; a new off-target value restarts the delay (HMI-03)."""
    states = merge([Seg(s.a, s.b, None if s.v is None else key(s.v)) for s in sp])
    dwells, settling = [], after_change
    for i, s in enumerate(states):
        if s.v == target:
            settling = False
        if s.v is None or s.v == target:
            continue
        nxt = states[i + 1] if i + 1 < len(states) else None
        ended = "censored" if nxt is None or nxt.v is None else ("target" if nxt.v == target else "other")
        dwells.append(Dwell(s.a, s.b - s.a, ended, changeover=settling))
    return dwells


def join(actual: list[Seg], sp: list[Seg]) -> list[tuple[float, float, object, object]]:
    out, i, j = [], 0, 0
    while i < len(actual) and j < len(sp):
        x, h = actual[i], sp[j]
        a, b = max(x.a, h.a), min(x.b, h.b)
        if b > a:
            out.append((a, b, x.v, h.v))
        if x.b <= h.b:
            i += 1
        else:
            j += 1
    return out


def severity_dwells(joined, off) -> tuple[list[Dwell], list[Dwell]]:
    """Excursions at ≥Warning and at Critical; interruptions shorter than the recovery delay don't end one."""
    states = []
    for a, b, x, h in joined:
        st = None if x is None or h is None else classify(x, h, off)
        if states and states[-1][2] == st and states[-1][1] == a:
            states[-1][1] = b
        else:
            states.append([a, b, st])

    def blocks(member: set[str]) -> list[Dwell]:
        out, start, end = [], None, None
        for k, (a, b, st) in enumerate(states):
            if st in member:
                start = a if start is None else start
                end = b
            elif start is not None and (st is None or b - a >= RECOVERY_DELAY_S or k == len(states) - 1):
                out.append(Dwell(start, end - start, "censored" if st is None else "other"))
                start = None
        if start is not None:
            out.append(Dwell(start, end - start, "censored"))
        return out

    return blocks({"W", "C"}), blocks({"C"})


# -- machine state -------------------------------------------------------------


def running_periods(run_segs: list[Seg], long_stop_s: float, warmup_s: float) -> list[tuple[float, float]]:
    """Stretches with Machine_Run = 1, minus the first `warmup_s` after a stop of at least `long_stop_s`.

    The machine stops and starts about 100 times a day; short stops (jams) don't
    cool the zones, so running resumes at once after them. After a long stop the
    zones have to heat up again first.
    """
    out, stopped_for = [], 0.0
    for s in run_segs:
        if s.v is None:
            stopped_for = 0.0
        elif float(s.v) == 1.0:
            start = s.a + (warmup_s if stopped_for >= long_stop_s else 0.0)
            if s.b > start:
                out.append((start, s.b))
            stopped_for = 0.0
        else:
            stopped_for += s.b - s.a
    return out


def keep_only(segs: list[Seg], keep: list[tuple[float, float]]) -> list[Seg]:
    """The same step series, unknown outside `keep` (sorted, disjoint intervals)."""
    out, k = [], 0
    for s in segs:
        a = s.a
        while a < s.b:
            while k < len(keep) and keep[k][1] <= a:
                k += 1
            if k == len(keep) or keep[k][0] >= s.b:
                out.append(Seg(a, s.b, None))
                break
            ka, kb = keep[k]
            if ka > a:
                out.append(Seg(a, ka, None))
                a = ka
            b = min(s.b, kb)
            out.append(Seg(a, b, s.v))
            a = b
    return merge(out)


# -- reporting helpers ---------------------------------------------------------


def weighted_pct(pairs: list[tuple[float, float]], q: float) -> float:
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total:
            return v
    return float("nan")


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def fmt_s(x: float) -> str:
    if math.isnan(x):
        return "–"
    if x < 120:
        return f"{x:.0f} s"
    if x < 7200:
        return f"{x / 60:.1f} min"
    return f"{x / 3600:.1f} h"


KNEE_GAIN = 0.10  # a longer delay must remove at least 10 % more events to be worth it


def suggest(dwells: list[Dwell]) -> str:
    """The knee of the events-per-delay curve (ADR-0002 selection rule).

    Walk the candidate delays and stop at the first one where the next longer
    delay would remove less than KNEE_GAIN of the remaining events. Shorter
    dwells are then the quick transients the delay should absorb; what's left
    are deliberate setpoint changes, which monitoring is meant to catch.
    """
    drift = [w.length for w in dwells if not w.changeover]
    if len(drift) < 20:
        return f"– (only {len(drift)} off-target dwells; need ≥ 20)"
    events = [sum(x >= d for x in drift) for d in CANDIDATES_S]
    for i in range(len(CANDIDATES_S) - 1):
        if events[i] == 0 or (events[i] - events[i + 1]) / events[i] < KNEE_GAIN:
            return f"**{CANDIDATES_S[i]} s** (longer delays remove < {KNEE_GAIN:.0%} more of {len(drift)} dwells)"
    return f"**≥ {CANDIDATES_S[-1]} s** (events keep falling with longer delays)"


def candidate_table(dwells: list[Dwell], days: float, with_changeover: bool) -> list[str]:
    head = "| Mismatch delay | Events / day | Brief changes / day |" + (" Extra events / day at changeover |" if with_changeover else "")
    rows = [head, "|---" * (4 if with_changeover else 3) + "|"]
    drift = [w for w in dwells if not w.changeover]
    change = [w for w in dwells if w.changeover]
    for d in CANDIDATES_S:
        raised = sum(w.length >= d for w in drift)
        row = f"| {d} s | {raised / days:.1f} | {(len(drift) - raised) / days:.1f} |"
        if with_changeover:
            row += f" {sum(w.length >= d for w in change) / days:.1f} |"
        rows.append(row)
    return rows


def short(tag: str, ns: str) -> str:
    return tag.split(ns + ".")[-1]


# -- main ----------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--targets")
    ap.add_argument("--limits")
    ap.add_argument("--running-only", action="store_true",
                    help="judge Actual severity only while the machine runs, skipping warm-ups after long stops")
    ap.add_argument("--long-stop-min", type=float, default=10.0)
    ap.add_argument("--warmup-min", type=float, default=30.0)
    args = ap.parse_args()

    cfg, reg = load_config(args.config)
    good = int(cfg.get("good_quality_min", 192))
    manifest = json.loads((RAW / "manifest.json").read_text())
    lo = parse_ts(manifest["from"]).timestamp()
    hi = min(parse_ts(manifest["to"]).timestamp(), float(manifest.get("done_until") or 0) or float("inf"))
    targets, limits = load_targets(args.targets), load_limits(args.limits)
    gaps = load_gaps()
    fetched = set(manifest["tags"])

    sku_mode = reg.sku_tag is not None and reg.sku_tag in fetched
    runs = ([r for r in to_segments(load_series(reg.sku_tag, good, numeric=False), lo, hi) if r.v is not None]
            if sku_mode else shift_runs(lo, hi))
    days = max(sum(r.b - r.a for r in runs) / 86400, 1e-9)
    run_tag = reg.context.get("machine_run")
    run_segs = to_segments(load_series(run_tag, good, numeric=True), lo, hi) if run_tag in fetched else []
    active = (running_periods(run_segs, args.long_stop_min * 60, args.warmup_min * 60)
              if args.running_only and run_segs else None)

    # pid -> list of (zone, hmi dwells, ≥Warning excursions, Critical excursions, |actual−sp| spread, setpoint changes)
    per_param: dict[str, list] = defaultdict(list)
    skipped: list[str] = []
    settle: list[float] = []
    changeover_off: Counter = Counter()

    for z in reg.zones:
        if z.setpoint not in fetched or z.actual not in fetched:
            skipped.append(f"{z.channel} ({z.zone_name}): tag not downloaded")
            continue
        key = z.hmi_match.key
        sp_pts = load_series(z.setpoint, good, numeric=True)
        sp_all = to_segments(sp_pts, lo, hi)
        act_all = to_segments(load_series(z.actual, good, numeric=True), lo, hi)
        if active is not None:  # --running-only: stopped time and warm-ups don't count for Actual rules
            act_all = keep_only(act_all, active)
        sp_changes = sum(1 for t, _ in sp_pts if lo <= t < hi)
        dwells, sev_w, sev_c, dev = [], [], [], []
        for k, run in enumerate(runs):
            sp = clip(sp_all, run.a, run.b)
            sku = str(run.v) if sku_mode else "*"
            raw_target = _lookup(targets, sku, z.parameter_id, z.zone_id)
            target = key(raw_target) if raw_target is not None else inferred_target(sp, key)
            if target is None:
                continue
            dwells += hmi_dwells(sp, target, key, after_change=sku_mode and k > 0)
            if sku_mode and k > 0:
                first = next((s.v for s in sp if s.v is not None), None)
                if first is not None and key(first) != target:
                    changeover_off[run.a] += 1
                ok = next((s.a for s in sp if s.v is not None and key(s.v) == target), None)
                if ok is not None:
                    settle.append(ok - run.a)
            joined = join(clip(act_all, run.a, run.b), sp)
            dev += [(abs(x - h), b - a) for a, b, x, h in joined if x is not None and h is not None]
            off = _lookup(limits, sku, z.parameter_id, z.zone_id)
            if off:
                w, c = severity_dwells(joined, off)
                sev_w += w
                sev_c += c
        per_param[z.parameter_id].append((z, dwells, sev_w, sev_c, dev, sp_changes))

    # A setpoint that changes constantly is a data or rule problem, not operator behaviour:
    # keep it out of the line-wide suggestion so it can't drag the default delay down.
    live = {r[0].channel for rows in per_param.values() for r in rows if r[5] / days > LIVE_SETPOINT_PER_DAY}
    all_dwells = [w for rows in per_param.values() for r in rows if r[0].channel not in live for w in r[1]]
    names = {p["id"]: p for p in reg.parameters}
    L = [f"# Delay analysis (O-08), generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
         f"- Range: {manifest['from']} → {manifest['to']} (UTC, Timebase clock); "
         f"analysed up to {datetime.fromtimestamp(hi, timezone.utc):%Y-%m-%d %H:%M} UTC",
         f"- Register version {reg.version}: {sum(len(r) for r in per_param.values())} zones in {len(per_param)} active parameters",
         ("- Runs follow the SKU tag" if sku_mode else
          "- **No SKU tag yet (ADR-0007):** each shift is a run and its target is inferred as the setpoint "
          "held longest in that shift. Changeover analysis needs the SKU tag."),
         f"- Targets: {'targets.csv' if targets else 'inferred per run'} · "
         f"Actual limits: {'limits.csv' if limits else 'not given, so severity analysis is skipped'}",
         "- Events / day count every dwell long enough to trigger, including censored ones; "
         "percentiles use only dwells that ended on their own.",
         "- Excursions interrupted for less than the 15 s recovery delay count as one excursion.", ""]

    L += ["## Line summary", "",
          f"Suggested global default mismatch delay: {suggest(all_dwells)}", ""]
    if live:
        L += [f"Left out of the line totals because their setpoint changes more than {LIVE_SETPOINT_PER_DAY} times "
              f"a day (a live value, not an operator setting): {', '.join(sorted(live))}. "
              "Their own tables are below.", ""]
    L += [
          *candidate_table(all_dwells, days, sku_mode), "",
          "CAP-01 budget: 1,000 events and 10,000 lightweight changes per day for the whole line.", "",
          "| Parameter | Zones | HMI rule | Off-target dwells / day | Setpoint changes / day | Suggested delay | Flags |",
          "|---|---|---|---|---|---|---|"]
    for pid, rows in sorted(per_param.items()):
        dw = [w for r in rows for w in r[1]]
        flags = []
        if any(r[5] / days > LIVE_SETPOINT_PER_DAY for r in rows):
            flags.append(f"setpoint changes > {LIVE_SETPOINT_PER_DAY}/day: behaves like a live value, check the HMI rule")
        if names[pid].get("hmi_match_review"):
            flags.append("HMI rule under review (O-17)")
        L.append(f"| {pid} {names[pid]['name']} | {len(rows)} | {rows[0][0].hmi_match.describe()} | "
                 f"{sum(not w.changeover for w in dw) / days:.1f} | {sum(r[5] for r in rows) / days:.1f} | "
                 f"{suggest(dw)} | {'; '.join(flags) or '–'} |")
    L.append("")

    if limits:
        # Split by machine state at the start of each excursion: stops and warm-ups can
        # dominate Critical counts, and whether to alarm then is a design question (O-20).
        run_starts = [s.a for s in run_segs]

        def running_at(t: float) -> bool:
            i = bisect_right(run_starts, t) - 1
            return i >= 0 and run_segs[i].v is not None and float(run_segs[i].v) == 1.0

        rows_sev = [r for rows in per_param.values() for r in rows if r[0].channel not in live]
        all_w = [w for r in rows_sev for w in r[2]]
        all_c = [c for r in rows_sev for c in r[3]]
        scope = (f"only while running, skipping {args.warmup_min:g} min of warm-up after stops of ≥ {args.long_stop_min:g} min"
                 if active is not None else "at all times, stopped or running (as the URS is written)")
        L += ["### Actual severity (with the given limits)", "",
              f"Actual rules judged {scope}.", "",
              f"Suggested Warning delay: {suggest(all_w)} · suggested Critical delay: {suggest(all_c)}", "",
              "| Delay | Warning events / day | Critical events / day | Critical, machine running at start | "
              "Critical, machine stopped at start |", "|---|---|---|---|---|"]
        for d in CANDIDATES_S:
            crit = [c for c in all_c if c.length >= d]
            run_n = sum(running_at(c.start) for c in crit)
            L.append(f"| {d} s | {sum(w.length >= d for w in all_w) / days:.1f} | {len(crit) / days:.1f} | "
                     f"{run_n / days:.1f} | {(len(crit) - run_n) / days:.1f} |")
        L.append("")

    if sku_mode:
        n = max(len(runs) - 1, 0)
        L += ["### SKU changeovers (ADR-0001)", "",
              f"- Changeovers: {n} ({n / days:.2f} per day)",
              f"- Changeovers with ≥ 1 zone off the new SKU's target at the change: {len(changeover_off)}"
              f" (median {statistics.median(changeover_off.values()) if changeover_off else 0:g} zones each)",
              f"- Time until each zone first matched the new target: "
              f"p50 {fmt_s(pct(settle, .5))} · p90 {fmt_s(pct(settle, .9))}", ""]

    if gaps or skipped or manifest.get("missing_tags"):
        L += ["### Data quality", ""]
        for t, secs in sorted(gaps.items(), key=lambda kv: -kv[1]):
            L.append(f"- Unreadable in Timebase: `{short(t, reg.namespace)}` for {fmt_s(secs)} (spans in data/raw/gaps.csv)")
        L += [f"- Skipped {s}" for s in skipped]
        L += [f"- Not in Timebase: `{short(t, reg.namespace)}`" for t in manifest.get("missing_tags", [])]
        L.append("")

    for pid, rows in sorted(per_param.items()):
        p = names[pid]
        dw = [w for r in rows for w in r[1]]
        L += [f"## {pid} {p['name']}" + (f" ({p['unit']})" if p.get("unit") else ""), "",
              f"HMI rule: {rows[0][0].hmi_match.describe()}."
              + (f" **Review:** {p['hmi_match_review']}" if p.get("hmi_match_review") else ""), "",
              "| Zone | Setpoint changes / day | Dwells / day | Returned · moved · censored | p50 | p90 | "
              "Suggested delay | \\|actual − setpoint\\| p50 · p99 |",
              "|---|---|---|---|---|---|---|---|"]
        for z, d, _, _, dev, spc in rows:
            done = [w.length for w in d if w.ended_by != "censored"]
            spread = f"{weighted_pct(dev, .5):.3g} · {weighted_pct(dev, .99):.3g}" if dev else "–"
            L.append(f"| {z.zone_id} {z.zone_name} | {spc / days:.1f} | {len(d) / days:.1f} | "
                     f"{sum(w.ended_by == 'target' for w in d)} · {sum(w.ended_by == 'other' for w in d)} · "
                     f"{sum(w.ended_by == 'censored' for w in d)} | {fmt_s(pct(done, .5))} | {fmt_s(pct(done, .9))} | "
                     f"{suggest(d)} | {spread} |")
        L += ["", f"All {p['name']} zones together:", "", *candidate_table(dw, days, sku_mode), ""]
        if limits:
            sw = [w for r in rows for w in r[2]]
            sc = [c for r in rows for c in r[3]]
            L += ["| Delay | Warning events / day | Critical events / day |", "|---|---|---|"]
            L += [f"| {d} s | {sum(w.length >= d for w in sw) / days:.1f} | {sum(c.length >= d for c in sc) / days:.1f} |"
                  for d in CANDIDATES_S]
            L.append("")

    OUT.mkdir(exist_ok=True)
    path = OUT / "delay-report.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
