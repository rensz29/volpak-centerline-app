"""Phase 0 Timebase probe: the facts O-03, O-08 and ADR-0006 need.

    python probe.py config.json

Writes data/probe-report.md with:
* reachability, datasets, and whether every register tag exists (one unknown
  tag makes Timebase reject a whole multi-tag request);
* the latest value and quality of every tag;
* one hour of each tag: sample count, spacing, quality codes, setpoint churn;
* publish cadence per machine area from its `_timestamp` field, which is the
  rate the machine publishes to MQTT;
* clock offsets between this PC, the Timebase server and the machine's payload
  timestamps.
Read-only.
"""

from __future__ import annotations

import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fetch import load_config
from timebase import TimebaseClient, TimebaseError

OUT = Path(__file__).parent / "data"
SPACING_BINS = [(0, 1.5, "≤1.5 s"), (1.5, 5, "1.5–5 s"), (5, 10, "5–10 s"), (10, 15, "10–15 s"),
                (15, 30, "15–30 s"), (30, 60, "30–60 s"), (60, float("inf"), "> 60 s")]


def main(cfg_path: str) -> int:
    cfg, reg = load_config(cfg_path)
    tb = TimebaseClient(cfg)
    ns = reg.namespace

    def short(tag: str) -> str:
        return tag.split(ns + ".")[-1]

    L = [f"# Timebase probe, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC (this PC's clock)", "",
         f"- Base URL `{tb.base}` · dataset `{tb.dataset}` · register version {reg.version}", ""]

    t0 = time.time()
    try:
        ds = tb.datasets()
    except TimebaseError as e:
        L.append(f"- **`/api/datasets` failed: {e}** (check URL, auth, firewall)")
        return _write(L)
    local = (t0 + time.time()) / 2
    names = ", ".join(f"`{d.get('n')}`" for d in ds)
    L.append(f"- Datasets: {names}")
    if not any(d.get("n") == tb.dataset for d in ds):
        L.append(f"- **Configured dataset `{tb.dataset}` not found.**")
    server_offset = (tb.last_server_date - local) if tb.last_server_date else None
    if server_offset is not None:
        L.append(f"- Timebase server clock − this PC's clock: **{server_offset:+.0f} s** "
                 "(HTTP Date header, 1 s resolution; make sure this PC is NTP-synced before trusting it)")

    known = tb.tag_names(contains=ns)
    labelled = [(f"{z.channel} setpoint", z.setpoint) for z in reg.zones] + \
               [(f"{z.channel} actual", z.actual) for z in reg.zones] + \
               [(f"context: {k}", v) for k, v in reg.context.items()] + reg.candidate_tags()
    L += [f"- Tags under the namespace: {len(known)}", "", "## Register tags", "",
          "| Role | Tag | In Timebase | Latest value | Quality | Last change (Timebase clock) |",
          "|---|---|---|---|---|---|"]
    present = [t for _, t in labelled if t in known]
    latest, latest_err = {}, None
    try:
        latest = {t: (pts[-1] if pts else None) for t, pts in tb.read(list(dict.fromkeys(present))).items()}
    except TimebaseError as e:
        latest_err = str(e)
    for role, tag in labelled:
        p = latest.get(tag)
        L.append(f"| {role} | `{short(tag)}` | {'yes' if tag in known else '**NO**'} | "
                 f"{'' if p is None else p.v} | {'' if p is None else p.q} | {'' if p is None else f'{p.t:%Y-%m-%d %H:%M:%S}'} |")
    if latest_err:
        L += ["", f"**Latest-value request failed:** {latest_err}"]

    end = int(tb.last_server_date or time.time())
    start = end - 3600
    gaps = []
    hour = tb.read_window(list(dict.fromkeys(present)), start, end, gaps=gaps)
    L += ["", "## Last hour per tag", "",
          "| Role | Samples | Median spacing | Max gap | Quality codes | Note |", "|---|---|---|---|---|---|"]
    for role, tag in labelled:
        if tag not in hour:
            continue
        pts = [p for p in hour[tag] if p.t.timestamp() >= start]
        sp = [(b.t - a.t).total_seconds() for a, b in zip(pts, pts[1:])]
        note = ""
        if role.endswith("setpoint") and len(pts) > 10:
            note = f"setpoint changed {len(pts)}× in an hour: looks like a live value"
        L.append(f"| {role} | {len(pts)} | {f'{statistics.median(sp):.1f} s' if sp else '–'} | "
                 f"{f'{max(sp):.0f} s' if sp else '–'} | {dict(Counter(p.q for p in pts).most_common(4))} | {note} |")
    for g in gaps:
        L.append(f"| unreadable | `{short(g.tag)}` {datetime.fromtimestamp(g.start, timezone.utc):%H:%M}"
                 f"–{datetime.fromtimestamp(g.end, timezone.utc):%H:%M} | | | | {g.reason} |")

    L += ["", "## Publish cadence per machine area (from `_timestamp`)", "",
          "Each MQTT message from a machine area carries `_timestamp` (epoch ms), so its Timebase "
          "samples are the message arrivals. This sets the freshness threshold in ADR-0006.", "",
          "| Area | Messages / h | " + " | ".join(b[2] for b in SPACING_BINS) + " | Payload clock − Timebase clock |",
          "|---|---|" + "---|" * len(SPACING_BINS) + "---|"]
    for group in reg.groups():
        ts_tag = f"{ns}.{group}._timestamp"
        if ts_tag not in known:
            L.append(f"| {group} | no `_timestamp` tag |" + " |" * (len(SPACING_BINS) + 1))
            continue
        try:
            pts = [p for p in tb.read_window([ts_tag], start, end)[ts_tag] if p.t.timestamp() >= start]
        except TimebaseError as e:
            L.append(f"| {group} | error: {e} |" + " |" * (len(SPACING_BINS) + 1))
            continue
        sp = [(b.t - a.t).total_seconds() for a, b in zip(pts, pts[1:])]
        bins = [sum(lo < x <= hi for x in sp) for lo, hi, _ in SPACING_BINS]
        skew = [p.v / 1000 - p.t.timestamp() for p in pts if isinstance(p.v, (int, float))]
        skew_txt = f"{statistics.median(skew):+.1f} s" if skew else "–"
        L.append(f"| {group} | {len(pts)} | " + " | ".join(str(b) for b in bins) + f" | {skew_txt} |")

    L += ["", "## What to record", "",
          "- O-03: auth method, tag names that are missing, quality codes seen, unreadable spans.",
          "- ADR-0006: the largest regular gap per area sets the freshness threshold (the SDD's 10 s "
          "only works if every area publishes at least every few seconds).",
          "- Clock offsets larger than a second or two mean a server or the edge publisher isn't NTP-synced "
          "(O-18). Monitoring uses its own clock, but history and events will disagree by that much."]
    return _write(L)


def _write(lines: list[str]) -> int:
    OUT.mkdir(exist_ok=True)
    path = OUT / "probe-report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
