"""Monitoring control (ADR-0017): zones switched off (MON-01) and maintenance windows (MNT-01)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from centerline_common.db import uuid7

from .conftest import FAST_AUTH


def later(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def audit(c, action: str) -> list[dict]:
    return [e for e in c.get("/api/v1/config/register").json()["audit"] if e["action"] == action]


def test_a_manager_switches_zones_off_with_a_reason_and_on_again(make_client, owner):
    manager = make_client(roles=["MANAGER"])
    me = manager.get("/api/v1/auth/session").json()["user"]["username"]
    r = manager.post("/api/v1/monitoring/switch", json={"channels": ["P02.V3"], "on": False})
    assert r.status_code == 422 and r.json()["type"] == "/problems/reason-needed"
    r = manager.post("/api/v1/monitoring/switch", json={"channels": ["P02.V9"], "on": False, "reason": "x"})
    assert r.status_code == 422 and r.json()["type"] == "/problems/unknown-zone"

    body = {"channels": ["P02.V3", "P02.V4"], "on": False, "reason": "Thermocouples replaced"}
    r = manager.post("/api/v1/monitoring/switch", json=body)
    assert r.status_code == 200 and r.json()["changed"] == ["P02.V3", "P02.V4"]
    assert [(z["zoneName"], z["by"], z["reason"]) for z in r.json()["switchedOff"]] == [
        ("Vertical 3", me, "Thermocouples replaced"), ("Vertical 4", me, "Thermocouples replaced")]
    assert manager.post("/api/v1/monitoring/switch", json=body).json()["changed"] == []  # off already: nothing added

    r = manager.post("/api/v1/monitoring/switch", json={"channels": ["P02.V3"], "on": True})  # on again needs no reason
    assert r.json()["changed"] == ["P02.V3"] and [z["channel"] for z in r.json()["switchedOff"]] == ["P02.V4"]
    assert [z["channel"] for z in manager.get("/api/v1/monitoring/live").json()["control"]["switchedOff"]] == ["P02.V4"]
    (on, off) = audit(manager, "monitoring.switch")
    assert off["summary"] == "Monitoring switched off: Vertical 3 (P02.V3), Vertical 4 (P02.V4)" and off["user"] == me
    assert on["summary"] == "Monitoring switched on: Vertical 3 (P02.V3)"

    r = make_client(roles=["ADMINISTRATOR"]).post("/api/v1/monitoring/switch", json=body)
    assert r.status_code == 403  # a Manager's (O-13)
    with owner.connect() as conn, pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute("UPDATE monitoring_switch SET reason = 'changed'")  # the history is kept, even against the owner


def test_an_administrator_opens_extends_and_ends_maintenance_windows(make_client):
    admin = make_client(roles=["ADMINISTRATOR"])
    me = admin.get("/api/v1/auth/session").json()["user"]["username"]
    for body, field in (({"scope": "zones", "reason": "Heater work", "end": later(hours=1)}, "channels"),
                        ({"scope": "line", "reason": "x", "start": later(hours=-1), "end": later(hours=1)}, "start"),
                        ({"scope": "line", "reason": "x", "end": later(minutes=-5)}, "end"),
                        ({"scope": "zones", "channels": ["P02.V9"], "reason": "x", "end": later(hours=1)}, "channels")):
        r = admin.post("/api/v1/maintenance", json=body)
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == field, body
    assert admin.post("/api/v1/maintenance", json={"scope": "line", "reason": "x", "end": "2026-10-01T10:00:00"}).status_code == 422

    now_window = admin.post("/api/v1/maintenance", json={"scope": "zones", "channels": ["P04.FRONT"],
                                                         "reason": "Heater replaced", "end": later(minutes=45)}).json()
    assert (now_window["status"], now_window["zones"][0]["zoneName"], now_window["createdBy"]) == ("active", "Front top 1", me)
    scheduled = admin.post("/api/v1/maintenance", json={"scope": "line", "reason": "Network change",
                                                        "start": later(hours=2), "end": later(hours=3)}).json()
    assert scheduled["status"] == "scheduled"
    assert [w["id"] for w in admin.get("/api/v1/monitoring/control").json()["maintenance"]] == [now_window["id"], scheduled["id"]]

    r = admin.post(f"/api/v1/maintenance/{now_window['id']}/extend", json={"end": later(hours=2), "reason": "Parts late"})
    assert r.status_code == 200 and r.json()["plannedEnd"] > now_window["plannedEnd"]
    assert admin.post(f"/api/v1/maintenance/{scheduled['id']}/end", json={}).json()["status"] == "cancelled"
    ended = admin.post(f"/api/v1/maintenance/{now_window['id']}/end", json={"reason": "Done"}).json()
    assert (ended["status"], ended["endedBy"]) == ("ended", me)
    assert admin.post(f"/api/v1/maintenance/{now_window['id']}/end", json={}).status_code == 409
    assert admin.post(f"/api/v1/maintenance/{now_window['id']}/extend", json={"end": later(hours=5)}).status_code == 409
    assert admin.get("/api/v1/monitoring/control").json()["maintenance"] == []
    assert {w["status"] for w in admin.get("/api/v1/maintenance").json()["windows"]} == {"ended", "cancelled"}
    actions = [e["action"] for e in admin.get("/api/v1/config/register").json()["audit"] if e["action"].startswith("maintenance.")]
    assert actions == ["maintenance.end", "maintenance.cancel", "maintenance.extend", "maintenance.open", "maintenance.open"]

    manager = make_client(roles=["MANAGER"])
    assert manager.post("/api/v1/maintenance", json={"scope": "line", "reason": "x", "end": later(hours=1)}).status_code == 403
    operator = make_client(roles=["OPERATOR"], address="10.0.0.5",
                           auth=replace(FAST_AUTH, operator_workstations=(("Line desk", "10.0.0.5"),)))
    assert operator.get("/api/v1/maintenance").status_code == 200  # every role sees the windows


def test_a_window_past_its_planned_end_is_overdue_until_ended_and_its_history_is_guarded(make_client, database, owner):
    c = make_client()
    wid = uuid7()
    with database.connect() as conn:
        conn.execute("""INSERT INTO maintenance_window (id, scope, reason, planned_start, planned_end, created_by)
                        VALUES (%s, 'line', 'Network change', now() - interval '2 hours', now() - interval '10 min', 'admin')""", (wid,))
        conn.commit()
    (w,) = c.get("/api/v1/monitoring/live").json()["control"]["maintenance"]
    assert (w["id"], w["status"]) == (str(wid), "overdue")  # still in force: the work may not be done
    with owner.connect() as conn:  # the guard holds even for the owner
        for sql in ("UPDATE maintenance_window SET reason = 'other'", "DELETE FROM maintenance_window"):
            with pytest.raises(psycopg.errors.RestrictViolation):
                conn.execute(sql)
            conn.rollback()
    assert c.post(f"/api/v1/maintenance/{wid}/end", json={}).json()["status"] == "ended"
    with owner.connect() as conn, pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute("UPDATE maintenance_window SET ended_at = now()")  # ended once
