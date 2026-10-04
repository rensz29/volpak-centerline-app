"""The reason workflow in monitor-core (ADR-0025): a request with each HMI mismatch, closed with it, at shift end, escalated."""

from __future__ import annotations

import psycopg
import pytest

from centerline_monitor.store import Store
from monitor_helpers import advance, at
from test_monitor_store import rows, running


def test_an_hmi_mismatch_asks_that_shifts_operator_for_a_reason_and_its_request_closes_with_it(seeded, owner, tmp_path):
    engine, store, line = running(seeded, tmp_path)  # 14:00 Manila: shift B starts
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 31)
    (event,) = rows(seeded, "SELECT id FROM event")
    (req,) = rows(seeded, """SELECT r.event_id, r.status, r.created_at, s.code, s.starts_at, s.ends_at
                               FROM workflow_request r JOIN shift_instance s ON s.id = r.shift_instance_id""")
    assert (req["event_id"], req["status"], req["created_at"], req["code"]) == (event["id"], "waiting_reason", at(31), "B")
    assert (req["starts_at"], req["ends_at"]) == (at(0), at(8 * 3600))  # 14:00–22:00 Manila
    for fx, now in store.steps:  # the journal may replay a step: still one request
        Store.apply(store, fx, now)
    assert len(rows(seeded, "SELECT 1 FROM workflow_request")) == 1

    line.set("P02.V1", setpoint=220)  # back on target: the event and its request close
    advance(engine, line, 31, 32)
    (req,) = rows(seeded, "SELECT status, closed_at FROM workflow_request")
    assert (req["status"], req["closed_at"]) == ("resolved", at(32))
    with owner.connect() as c, pytest.raises(psycopg.errors.RestrictViolation):
        c.execute("UPDATE workflow_request SET status = 'waiting_reason', closed_at = NULL")  # closed stays closed


def test_actual_events_ask_the_operator_for_no_reason(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    line.set("P03.REAR", actual=186)
    advance(engine, line, 0, 31)
    assert rows(seeded, "SELECT 1 FROM event WHERE kind = 'ACTUAL'") and not rows(seeded, "SELECT 1 FROM workflow_request")


def test_an_overdue_reason_alerts_management_once_and_an_unfinished_one_closes_when_the_shift_ends(seeded, tmp_path):
    engine, store, line = running(seeded, tmp_path)
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 31)
    names = engine.zone_names()
    store.workflow_tick(at(31 + 14 * 60), names)
    assert not rows(seeded, "SELECT 1 FROM notification WHERE kind = 'workflow_escalation'")  # 14 min: not yet
    store.workflow_tick(at(31 + 15 * 60), names)
    store.workflow_tick(at(31 + 16 * 60), names)
    (note,) = rows(seeded, "SELECT payload FROM notification WHERE kind = 'workflow_escalation'")  # once (WF-03)
    assert (note["payload"]["zoneName"], note["payload"]["shift"], note["payload"]["hmi"]) == ("Vertical 1", "B", "222")
    assert note["payload"]["shiftLabel"] == "Shift B, 1 Oct (14:00–22:00)"
    assert rows(seeded, "SELECT escalated_at FROM workflow_request")[0]["escalated_at"] == at(31 + 15 * 60)

    store.workflow_tick(at(8 * 3600), names)  # 22:00 Manila: shift B is over
    (req,) = rows(seeded, "SELECT status, closed_at FROM workflow_request")
    assert (req["status"], req["closed_at"]) == ("not_answered", at(8 * 3600))
