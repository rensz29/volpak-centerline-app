"""monitor-core against PostgreSQL: one transaction per step, append-only evidence, restarts, acks, outages."""

from __future__ import annotations

import socket
from dataclasses import replace

import psycopg
import pytest

from centerline_common.db import uuid7
from centerline_monitor.engine import Engine
from centerline_monitor.store import Store
from monitor_helpers import Line, advance, at


class Recording(Store):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.steps: list = []

    def apply(self, fx, now):
        self.steps.append((list(fx), now))
        super().apply(fx, now)


def running(database, tmp_path, t: float = 0, store_cls=Recording) -> tuple[Engine, Store, Line]:
    store = store_cls(database, tmp_path, "test")
    store.start(at(t - 1))
    engine = Engine(store.config(), store, at(t - 1))
    engine.restore(store.open_events(), at(t - 1))
    engine.set_connected(True, at(t - 1))
    line = Line()
    line.publish(engine, at(t))
    return engine, store, line


def give_ack(database, event_id, period: int = 1) -> None:
    """What POST /api/v1/events/{id}/acknowledge writes."""
    with database.connect() as c:
        c.execute("""INSERT INTO event_acknowledgment (id, event_id, by_user, note, critical_period)
                     VALUES (%s, %s, 'manager', 'on it', %s)""", (uuid7(), event_id, period))
        c.commit()


def rows(database, sql, *args):
    with database.connect() as c:
        return c.execute(sql, args).fetchall()


def test_a_mismatch_is_written_once_with_its_evidence(seeded, owner, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 31)
    line.set("P02.V1", setpoint=220)
    advance(engine, line, 31, 32)

    (event,) = rows(seeded, "SELECT * FROM event")
    active = rows(seeded, "SELECT active_config_version() AS c, active_mapping_version() AS m")[0]
    assert (event["kind"], event["opened_at"], float(event["raw_hmi"]), float(event["raw_target"])) == ("HMI_MISMATCH", at(31), 222, 220)
    assert (event["config_version_id"], event["mapping_version_id"]) == (active["c"], active["m"])  # pinned (OPC-07)
    assert [r["state"] for r in rows(seeded, "SELECT state FROM event_transition ORDER BY seq")] == ["OPEN", "RESOLVED"]
    (state,) = rows(seeded, "SELECT * FROM event_state")
    assert not state["open"] and state["closed_at"] == at(32)
    assert [r["kind"] for r in rows(seeded, "SELECT kind FROM notification ORDER BY created_at")] == ["initial", "recovery"]
    assert {r["status"] for r in rows(seeded, "SELECT status FROM scheduled_action WHERE key = 'P02.V1:hmi'")} == {"done"}
    assert all(r["ended_at"] for r in rows(seeded, "SELECT ended_at FROM pause_period WHERE scope = 'line'"))

    for fx, now in store.steps:  # every write is safe to repeat
        Store.apply(store, fx, now)
    assert len(rows(seeded, "SELECT 1 FROM event_transition")) == 2 and len(rows(seeded, "SELECT 1 FROM notification")) == 2

    with seeded.connect() as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("UPDATE event SET raw_hmi = 221")  # monitor-core's role may only add evidence (ADR-0020)
    with owner.connect() as c, pytest.raises(psycopg.errors.RestrictViolation):
        c.execute("UPDATE event SET raw_hmi = 221")  # and the trigger stops even the owner


def test_a_restart_carries_on_an_open_critical_without_repeating_what_was_sent(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    line.set("P06.N1", actual=98 + 19)
    advance(engine, line, 0, 31 * 60, every=5)  # Critical at t=11, repeats at 15 and 30 min
    assert [r["kind"] for r in rows(seeded, "SELECT kind FROM notification ORDER BY created_at")] == \
        ["initial", "critical_repeat", "critical_repeat"]

    engine2, _, _ = running(seeded, tmp_path, t=31 * 60 + 5)  # monitor-core restarted
    advance(engine2, line, 31 * 60 + 5, 50 * 60, every=5)
    kinds = [r["kind"] for r in rows(seeded, "SELECT kind FROM notification ORDER BY created_at")]
    assert kinds == ["initial", "critical_repeat", "critical_repeat", "critical_repeat"]  # the third, not the first again
    assert len(rows(seeded, "SELECT 1 FROM event")) == 1
    assert {r["status"] for r in rows(seeded, "SELECT status FROM scheduled_action WHERE key = 'P06.N1:critical'")} >= {"abandoned"}


def test_an_acknowledgment_from_the_api_stops_the_repeats(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    line.set("P06.N2", actual=98 - 19)
    advance(engine, line, 0, 16 * 60, every=5)
    (event,) = rows(seeded, "SELECT id FROM event")
    give_ack(seeded, event["id"])
    for ack in store.new_acks():
        engine.acknowledge(ack, at(16 * 60))
    advance(engine, line, 16 * 60, 80 * 60, every=5)
    assert [r["kind"] for r in rows(seeded, "SELECT kind FROM notification ORDER BY created_at")] == ["initial", "critical_repeat"]
    assert rows(seeded, "SELECT acknowledged_at FROM event_state")[0]["acknowledged_at"] == at(16 * 60)
    (t,) = rows(seeded, "SELECT inputs FROM event_transition WHERE state = 'ACKNOWLEDGED'")
    assert t["inputs"] == {"acknowledged_by": "manager", "note": "on it"}


def test_an_acknowledgment_given_while_monitor_core_was_down_counts_after_the_restart(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    line.set("P06.N2", actual=98 - 19)
    advance(engine, line, 0, 5 * 60, every=5)  # Critical from t=10
    (event,) = rows(seeded, "SELECT id FROM event")
    give_ack(seeded, event["id"])  # monitor-core is down now

    engine2, store2, _ = running(seeded, tmp_path, t=5 * 60 + 5)
    for ack in store2.new_acks():
        engine2.acknowledge(ack, at(5 * 60 + 5))
    advance(engine2, line, 5 * 60 + 5, 80 * 60, every=5)
    assert [r["kind"] for r in rows(seeded, "SELECT kind FROM notification ORDER BY created_at")] == ["initial"]
    assert len(rows(seeded, "SELECT 1 FROM event_transition WHERE state = 'ACKNOWLEDGED'")) == 1

    engine3, store3, _ = running(seeded, tmp_path, t=80 * 60 + 5)  # and again: nothing applied twice
    for ack in store3.new_acks():
        engine3.acknowledge(ack, at(80 * 60 + 5))
    assert len(rows(seeded, "SELECT 1 FROM event_transition WHERE state = 'ACKNOWLEDGED'")) == 1


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cut_off(store) -> None:
    """The database goes away: nothing answers on its port."""
    store.database = replace(store.database, port=closed_port(), connect_timeout_s=1)
    store.conn.close()


def test_steps_made_while_the_database_is_away_go_to_the_disk_journal_and_are_written_in_order(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    real = store.database
    cut_off(store)
    line.set("P02.V3", setpoint=217)
    advance(engine, line, 0, 31)  # the event opens while nothing can be written
    journal = store.journal.path
    assert store.journal.steps >= 1 and not rows(seeded, "SELECT 1 FROM event")
    assert (journal.stat().st_mode & 0o777, journal.parent.stat().st_mode & 0o777) == (0o600, 0o700)  # protected
    store.database = real
    line.set("P02.V3", setpoint=215)
    advance(engine, line, 31, 38)
    assert store.drain(at(38))  # as the service loop does every 2 s, once the 5 s wait is over
    assert not store.journal.pending and journal.stat().st_size == 0
    assert [r["state"] for r in rows(seeded, "SELECT state FROM event_transition ORDER BY seq")] == ["OPEN", "RESOLVED"]


def test_a_restart_during_an_outage_writes_the_journal_before_anything_else(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    cut_off(store)
    line.set("P02.V3", setpoint=217)
    advance(engine, line, 0, 40)  # opened at 31, only in the journal
    assert not rows(seeded, "SELECT 1 FROM event")

    # monitor-core stops; the database comes back; the next run finds the same journal
    engine2, store2, _ = running(seeded, tmp_path, t=45)
    assert not store2.journal.pending
    assert len(rows(seeded, "SELECT 1 FROM event")) == 1
    # Written from the journal, then restored: the new run's on-target setpoint resolves the same event
    assert [r["state"] for r in rows(seeded, "SELECT state FROM event_transition ORDER BY seq")] == ["OPEN", "RESOLVED"]
    assert "pending" not in {r["status"] for r in rows(seeded, "SELECT status FROM scheduled_action")}  # timers from zero


def test_a_replay_cut_short_is_safe_to_run_again(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    real = store.database
    cut_off(store)
    line.set("P02.V3", setpoint=217)
    advance(engine, line, 0, 40)
    saved = store.journal.path.read_bytes()
    store.database = real
    assert store.drain(at(60), force=True)
    store.journal.path.write_bytes(saved + b'{"at": "2026-')  # as if a crash left the journal and a torn last line
    replayed = type(store.journal)(store.journal.path)
    assert replayed.steps == len(saved.splitlines())  # the torn line isn't a step
    store.journal = replayed
    assert store.drain(at(61), force=True)
    assert len(rows(seeded, "SELECT 1 FROM event")) == 1 and len(rows(seeded, "SELECT 1 FROM notification")) == 1


def test_switches_and_windows_come_from_the_database_and_a_switched_off_event_closes_there(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    line.set("P06.N1", actual=98 + 19)
    advance(engine, line, 0, 30, every=5)  # a Critical is open
    with seeded.connect() as c:
        for enabled, reason in ((False, "Sensor replaced"), (True, None), (False, "Still broken")):
            c.execute("INSERT INTO monitoring_switch (id, channel, enabled, by_user, reason) VALUES (%s, 'P06.N1', %s, 'manager', %s)",
                      (uuid7(), enabled, reason))
        c.execute("""INSERT INTO maintenance_window (id, scope, channels, reason, planned_start, planned_end, created_by)
                     VALUES (%s, 'zones', ARRAY['P02.V1'], 'Heater work', %s, %s, 'admin')""", (uuid7(), at(20), at(3600)))
        c.commit()
    switched_off, windows = store.control()
    assert switched_off["P06.N1"]["reason"] == "Still broken"  # the latest switch of each zone counts
    assert [(w["scope"], w["channels"]) for w in windows] == [("zones", ["P02.V1"])]
    engine.set_control(switched_off, windows, at(30))
    assert rows(seeded, "SELECT state, open FROM event_state") == [{"state": "CLOSED_MONITORING_DISABLED", "open": False}]
    assert [r["kind"] for r in rows(seeded, "SELECT kind FROM notification")] == ["initial"]  # no recovery notice
