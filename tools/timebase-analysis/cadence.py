"""How often each machine area publishes, from its `_timestamp` in Timebase (ADR-0006 freshness).

    python cadence.py config.json [--days 28]

Every MQTT message from a machine area (SPC, Dosing_Parameters) carries
`_timestamp`, so its Timebase samples are the message arrivals. This counts
how often an area goes silent for longer than each candidate freshness
threshold, split by whether the machine was running, and lists the longest
silences. Monitoring pauses whenever an area is silent past its threshold, so
the threshold must sit above the largest regular gap.

Needs Machine_Run in data/raw (run fetch.py first). Writes data/cadence-report.md.
Read-only.
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analyse_delays import load_series, to_segments
from fetch import RAW, load_config
from timebase import Gap, TimebaseClient, parse_ts

OUT = Path(__file__).parent / "data"
THRESHOLDS_S = [10, 15, 20, 30, 60, 120, 300]
MANILA = timezone(timedelta(hours=8))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    args = ap.parse_args()
    cfg, reg = load_config(args.config)
    tb = TimebaseClient(cfg)
    manifest = json.loads((RAW / "manifest.json").read_text())
    lo = int(parse_ts(manifest["from"]).timestamp())
    hi = int(min(parse_ts(manifest["to"]).timestamp(), float(manifest.get("done_until") or hi_default(manifest))))
    days = (hi - lo) / 86400
    run_segs = to_segments(load_series(reg.context["machine_run"], 192, numeric=True), lo, hi)
    run_starts = [s.a for s in run_segs]

    def running_at(t: float) -> bool:
        i = bisect_right(run_starts, t) - 1
        return i >= 0 and run_segs[i].v is not None and float(run_segs[i].v) == 1.0

    L = [f"# Publish cadence per machine area (ADR-0006), {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
         f"- Range: {manifest['from']} → {manifest['to']} (UTC, Timebase clock), {days:.1f} days",
         "- A silence is the time between two consecutive messages from the area.",
         "- \"Pauses / day\" is how often monitoring would pause with that freshness threshold.", ""]
    for area in reg.groups():
        tag = reg.heartbeat_tag(area)
        gaps: list[Gap] = []
        times = sorted(tb.read_times(tag, lo, hi, 21600, 60, gaps))
        silences = [(a, b - a) for a, b in zip(times, times[1:])]
        running_time = sum(max(0.0, min(s.b, hi) - max(s.a, lo)) for s in run_segs
                           if s.v is not None and float(s.v) == 1.0) / 86400
        L += [f"## {area}", "",
              f"{len(times):,} messages ({len(times) / days / 86400:.2f} per second on average); "
              f"machine running {running_time / days:.0%} of the time. Unreadable spans in Timebase: {len(gaps)}.", "",
              "| Freshness threshold | Pauses / day while running | Pauses / day while stopped | Paused time while running |",
              "|---|---|---|---|"]
        for thr in THRESHOLDS_S:
            over = [(a, d) for a, d in silences if d > thr]
            run_over = [(a, d) for a, d in over if running_at(a)]
            paused_run_s = sum(d - thr for _, d in run_over)
            L.append(f"| {thr} s | {len(run_over) / days:.1f} | {(len(over) - len(run_over)) / days:.1f} | "
                     f"{paused_run_s / 3600 / days * 60:.1f} min/day |")
        longest = sorted(silences, key=lambda s: -s[1])[:5]
        L += ["", "Longest silences: " + "; ".join(
            f"{datetime.fromtimestamp(a, MANILA):%m-%d %H:%M} Manila, {d / 60:.1f} min "
            f"({'running' if running_at(a) else 'stopped'})" for a, d in longest), ""]
    OUT.mkdir(exist_ok=True)
    (OUT / "cadence-report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'cadence-report.md'}")
    return 0


def hi_default(manifest: dict) -> float:
    return parse_ts(manifest["to"]).timestamp()


if __name__ == "__main__":
    raise SystemExit(main())
