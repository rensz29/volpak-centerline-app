"""Storage (RES-02, O-12, ADR-0036): the guard's states, its alerts, and what protected degraded mode stops."""

from __future__ import annotations

from pathlib import Path

from centerline_common.isotime import iso
from monitor_helpers import advance, at, start
from centerline_monitor.effects import BriefChange
from centerline_monitor.storage import StorageGuard


class Disk:
    """A disk whose use the test sets."""

    def __init__(self, pct: float):
        self.pct = pct

    def __call__(self, _path: Path) -> float:
        return self.pct


def guard(pct: float) -> tuple[StorageGuard, Disk]:
    disk = Disk(pct)
    return StorageGuard([Path("/journal")], measure=disk), disk


def kinds(alerts) -> list[str]:
    return [a.payload["kind"] for a in alerts]


def test_80_percent_warns_once_and_the_warning_clears_below_78():
    g, disk = guard(81)
    assert kinds(g.check(at(0))) == ["Storage nearly full (RES-02)"] and g.state == "warning"
    assert g.check(at(60)) == []  # once per episode
    disk.pct = 79
    g.check(at(120))
    assert g.state == "warning"  # no flapping at the line
    disk.pct = 77
    assert g.check(at(180)) == [] and g.state == "normal"


def test_at_90_percent_the_cleanup_gets_ten_minutes_before_degraded_mode():
    g, disk = guard(92)
    assert kinds(g.check(at(0))) == ["Storage at the cleanup limit (RES-02)"] and g.state == "cleanup"
    g.check(at(9 * 60))
    assert g.state == "cleanup" and not g.degraded
    alerts = g.check(at(10 * 60))
    assert g.degraded and kinds(alerts) == ["Protected degraded mode: storage full (RES-02)"]
    assert alerts[0].payload["usedPct"] == 92 and alerts[0].kind == "system"


def test_a_cleanup_that_works_avoids_degraded_mode():
    g, disk = guard(91)
    g.check(at(0))
    disk.pct = 84
    g.check(at(5 * 60))
    assert g.state == "warning"
    g.check(at(30 * 60))
    assert not g.degraded


def test_degraded_mode_repeats_its_alert_hourly_and_ends_below_85_with_a_notice():
    g, disk = guard(95)
    g.check(at(0))
    first = g.check(at(600))
    keys = [first[0].dedup_key]
    for minute in range(11, 200):
        disk.pct = 88 if minute > 100 else 95  # under 90 but not under 85: still degraded
        keys += [a.dedup_key for a in g.check(at(minute * 60))]
    assert len(keys) == 4 and len(set(keys)) == 4  # entering, then +1 h, +2 h, +3 h
    assert g.degraded
    disk.pct = 84
    ended = g.check(at(200 * 60))
    assert kinds(ended) == ["Storage back under its limits (RES-02)"] and g.state == "warning"


def test_the_fullest_disk_counts_and_an_unreadable_one_is_reported():
    readings = {Path("/journal"): 70.0, Path("/backups"): 83.0}

    def measure(p: Path) -> float:
        if p == Path("/gone"):
            raise OSError("no such folder")
        return readings[p]

    g = StorageGuard([Path("/journal"), Path("/backups"), Path("/gone")], measure=measure)
    g.check(at(0))
    assert (g.state, g.path, g.used_pct) == ("warning", "/backups", 83.0)
    assert "/gone" in g.status()["error"]


def test_degraded_mode_stops_brief_change_records_and_nothing_else():
    engine, store, line = start()
    engine.storage_degraded = True
    line.set("P03.FRONT", setpoint=182)
    advance(engine, line, 0, 12)
    line.set("P03.FRONT", setpoint=180)
    advance(engine, line, 12, 60)
    assert not store.of(BriefChange) and engine.briefs_skipped == 1
    engine.storage_degraded = False
    line.set("P03.FRONT", setpoint=182)
    advance(engine, line, 60, 72)
    line.set("P03.FRONT", setpoint=180)
    advance(engine, line, 72, 120)
    assert len(store.of(BriefChange)) == 1


def test_the_status_says_what_the_page_needs():
    g, _ = guard(91)
    g.check(at(0))
    s = g.status()
    assert (s["state"], s["usedPct"], s["limits"]) == ("cleanup", 91.0, {"warn": 80.0, "cleanup": 90.0, "degradedUntilBelow": 85.0})
    assert s["since"] == iso(at(0))  # times end in Z (ADR-0028)  # the page counts the 10 min to degraded mode from it (StorageBanner)


def test_a_state_keeps_the_time_it_began():
    g, disk = guard(40)
    g.check(at(0))
    g.check(at(60))
    assert (g.state, g.since) == ("normal", None)  # never left normal
    disk.pct = 82
    g.check(at(120))
    g.check(at(180))
    assert (g.state, g.since) == ("warning", at(120))


def test_the_time_to_judge_is_the_worst_of_the_last_minute():
    from datetime import timedelta as td

    from centerline_monitor.service import Latency

    lat = Latency()
    lat.add(at(0), at(0) + td(milliseconds=40))
    lat.add(at(10), at(10) + td(milliseconds=2300))  # a slow one
    lat.add(at(50), at(50) + td(milliseconds=15))
    assert lat.status(at(51)) == {"maxMs": 2300, "messages": 3, "windowS": 60}
    assert lat.status(at(75)) == {"maxMs": 15, "messages": 1, "windowS": 60}  # the slow one is over a minute old
    assert lat.status(at(200))["maxMs"] is None
