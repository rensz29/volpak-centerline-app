"""The disk journal (RES-01, ADR-0018), without a database: what it keeps, and the pause past its limit."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from monitor_helpers import advance, at, start
from centerline_monitor import effects as E
from centerline_monitor.journal import Journal, decode, encode
from centerline_monitor.service import MonitorSettings, Service


def every_effect() -> list:
    z = E.ZoneRef("P02", "Vertical Temperature", "V1", "Vertical 1", "°C")
    v = E.Versions(uuid4(), uuid4(), uuid4())
    return [E.OpenEvent(uuid4(), "ACTUAL", z, "A", at(1), v, {"target": "220"}, Decimal("220"), Decimal("222.5"), Decimal("225.1"),
                        "CRITICAL", uuid4()),
            E.Transition(uuid4(), "CRITICAL", at(1), {"actual": "225.1", "hmi": "222.5"}, severity="CRITICAL"),
            E.BriefChange(uuid4(), z, "A", "cleared_before_trigger", at(1), at(2), v, Decimal("220"), Decimal("222"), {"seen": ["222"]}),
            E.Notify("k:initial", "initial", at(1), {"zone": "V1"}, uuid4()), E.StartTimer("P02.V1:hmi", "hmi_delay", at(31)),
            E.CancelTimer("P02.V1:actual"), E.TimerDone("P02.V1:hmi", at(31)), E.PauseStarted("line", at(3), ["SPC silent"]),
            E.PauseEnded("line", at(4))]


def test_every_effect_is_kept_exactly_and_in_order(tmp_path):
    journal = Journal(tmp_path / "journal" / "test.jsonl")
    fx = every_effect()
    assert [decode(encode(e)) for e in fx] == fx
    journal.append(fx[:4], at(1))
    journal.append(fx[4:], at(2))
    assert (journal.steps, journal.oldest, journal.age_s(at(61))) == (2, at(1), 60.0)
    assert list(journal.entries()) == [(fx[:4], at(1)), (fx[4:], at(2))]
    assert Journal(journal.path).steps == 2  # a new run finds them
    assert (journal.path.stat().st_mode & 0o777, journal.path.parent.stat().st_mode & 0o777) == (0o600, 0o700)
    journal.clear()
    assert not journal.pending and list(journal.entries()) == []


def test_a_last_line_torn_by_a_crash_is_skipped(tmp_path):
    journal = Journal(tmp_path / "j.jsonl")
    journal.append([E.CancelTimer("x")], at(1))
    with open(journal.path, "a", encoding="utf-8") as f:
        f.write('{"at": "2026-10-01T00:00:0')  # cut short: never on disk whole
    assert [fx for fx, _ in Journal(journal.path).entries()] == [[E.CancelTimer("x")]]


def test_past_the_journals_limit_judging_pauses_until_the_database_is_back(tmp_path):
    service = Service(replace(MonitorSettings(), config_dir=tmp_path, journal_dir=tmp_path / "journal", journal_limit_s=1800))
    service.store.journal.append([E.CancelTimer("x")], at(0))
    assert service._degraded(at(1800)) is None  # 30 min are kept, judging goes on
    reason = service._degraded(at(1801))
    assert reason.startswith("The database has been unreachable for 30 min, longer than the journal's 30 min")

    engine, store, line = start()
    advance(engine, line, 0, 10, every=5)
    engine.set_degraded(reason, at(10))
    status = engine.status()
    assert not status["judging"] and status["reasons"][0] == reason
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 10, 60, every=5)
    assert not store.of(E.OpenEvent)  # nothing new is judged, so the journal stops growing
    engine.set_degraded(None, at(60))
    advance(engine, line, 60, 100, every=5)
    assert store.of(E.OpenEvent)  # the database is back: judged again
