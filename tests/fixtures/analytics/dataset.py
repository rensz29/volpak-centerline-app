"""The reference dataset AT-ANA-01…10 run on (ADR-0029): what Timebase returns for two tags and their areas.

    python dataset.py        # rewrites dataset.json; then run independent.py to rewrite the expected results

Deterministic (seeded). X is Front bottom's actual temperature (°C, area SPC), Y the nozzle pressure (bar, area
Dosing_Parameters): different units and areas. Every time is on a 1/8 s grid, so it's exact in binary floating point
and the api and the independent calculation read the same instants.

- **Twelve production dates**, 10 Sep 06:00 to 22 Sep 06:00 Manila, values changing every 5 to 10 minutes. X follows
  Y with noise, so they correlate. On 15 Sep SPC goes silent after 06:30, and on 17 Sep Dosing_Parameters publishes
  for two and a half hours only: groups of different sizes (ANA-17).
- **A dense two hours**, 21 Sep 13:00–15:00 Manila, across the 14:00 shift change: samples every 2–4 s, with one of
  each excluded kind (ANA-09): bad quality, null, non-numeric, NaN, infinite, and out of the ranges in ranges.csv.
  SPC is silent for 5 minutes, which is a data gap.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANILA = timezone(timedelta(hours=8))
NS = "Unilever_Ph_Nutrition.Dressings_Halal.Filling.Volpak.Filler"
X_TAG = f"{NS}.SPC.Actual_Temp_Front_Bottom_1"
Y_TAG = f"{NS}.Dosing_Parameters.Pressure_Actual"
START = datetime(2026, 9, 10, 6, 0, tzinfo=MANILA)
END = datetime(2026, 9, 22, 6, 0, tzinfo=MANILA)
DENSE = (datetime(2026, 9, 21, 13, 0, tzinfo=MANILA), datetime(2026, 9, 21, 15, 0, tzinfo=MANILA))


def ts(t: datetime) -> float:
    return t.timestamp()


def grid(t: float) -> float:
    """To the 1/8 s grid: exact in a float."""
    return round(t * 8) / 8


def build() -> dict:
    rng = random.Random(2026)
    lo, hi = ts(START), ts(END)
    d0, d1 = ts(DENSE[0]), ts(DENSE[1])
    x, y = [], []

    def pressure() -> float:
        return round(1.30 + rng.gauss(0, 0.03), 3)

    def temperature(p: float) -> float:
        return round(180 + (p - 1.30) * 40 + rng.gauss(0, 0.6), 1)

    # carry-ins: the values in force when the range starts
    p = pressure()
    y.append([grid(lo - 3600 * 5 + 0.25), p, 192])
    x.append([grid(lo - 3600 * 2 + 0.5), temperature(p), 192])

    # the sparse days: a change every 5–10 min, outside the dense window
    t = lo + 60
    while t < hi:
        if not (d0 - 600 <= t < d1 + 600):
            p = pressure()
            y.append([grid(t), p, 192])
            x.append([grid(t + rng.uniform(5, 90)), temperature(p), 192])
        t += rng.uniform(300, 600)

    # the dense window: every 2–4 s
    t = d0
    while t < d1:
        p = pressure()
        y.append([grid(t), p, 192])
        t += rng.uniform(1, 3)
        x.append([grid(t), temperature(p), 192])
        t += rng.uniform(1, 2)

    def put(series: list, at: datetime, value, recover: float, q: int = 192) -> None:
        """A sample at `at` that can't be used, then a good one 45 s later: unknown in between (ANA-09)."""
        a = grid(ts(at))
        series[:] = [s for s in series if not (a - 1 <= s[0] <= a + 46)]
        series += [[a, value, q], [grid(a + 45), recover, 192]]

    def dense(h: int, m: int) -> datetime:
        return datetime(2026, 9, 21, h, m, tzinfo=MANILA)

    put(x, dense(13, 20), 180.4, temperature(pressure()), q=0)  # bad quality
    put(x, dense(13, 40), None, temperature(pressure()))  # null
    put(x, dense(13, 50), "ERR", temperature(pressure()))  # non-numeric
    put(y, dense(14, 10), float("nan"), pressure())
    put(y, dense(14, 20), float("inf"), pressure())
    put(y, dense(14, 30), 9.9, pressure())  # above P09's valid 0–5 bar in ranges.csv
    put(x, dense(14, 40), 400.0, temperature(pressure()))  # above P03's valid 0–300 °C
    for series in (x, y):
        series.sort(key=lambda r: r[0])

    # each area's message arrivals (its _timestamp samples): spans of a fixed spacing, minus silences
    sep15, sep17 = datetime(2026, 9, 15, 6, 30, tzinfo=MANILA), datetime(2026, 9, 17, 6, 0, tzinfo=MANILA)
    heartbeats = {
        "SPC": {"spans": [[grid(lo - 3600), grid(d0), 30], [grid(d0), grid(d1), 5], [grid(d1), grid(hi + 3600), 30]],
                "silent": [[ts(sep15), ts(sep15) + 86400 - 1800],  # 15 Sep from 06:30 to the next morning
                           [ts(dense(14, 45)), ts(dense(14, 50))]]},  # five minutes in the dense window
        "Dosing_Parameters": {"spans": [[grid(lo - 3600), grid(d0), 30], [grid(d0), grid(d1), 2], [grid(d1), grid(hi + 3600), 30]],
                              "silent": [[ts(sep17) + 9000, ts(sep17) + 86400]]},  # 17 Sep after 08:30
    }
    return {"x": {"tag": X_TAG, "area": "SPC", "channel": "P03.FRONT.actual", "parameter": "P03", "unit": "°C", "samples": x},
            "y": {"tag": Y_TAG, "area": "Dosing_Parameters", "channel": "P09.MAIN.actual", "parameter": "P09", "unit": "bar",
                  "samples": y},
            "heartbeats": heartbeats,
            "windows": {"days": [ts(START), ts(END)], "dense": [ts(DENSE[0]), ts(DENSE[1])]}}


def arrivals(spec: dict) -> list[float]:
    """An area's message times from its spans and silences (the stub Timebase and the calculation share this)."""
    out = []
    for a, b, every in spec["spans"]:
        t = a
        while t < b:
            if not any(s <= t < e for s, e in spec["silent"]):
                out.append(t)
            t += every
    return out


if __name__ == "__main__":
    (HERE / "dataset.json").write_text(json.dumps(build(), indent=None, separators=(",", ":")) + "\n", encoding="utf-8")
    print("dataset.json written")
