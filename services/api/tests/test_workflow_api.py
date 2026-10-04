"""The reason workflow (ADR-0025): an HMI mismatch asks the shift's operator why, a Manager guides, the operator acknowledges."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import psycopg
import pytest
from centerline_common import workflow as workflow_mod

from .conftest import FAST_AUTH
from .test_monitoring_api import event, versions

DESK = replace(FAST_AUTH, operator_workstations=(("Line desk", "10.0.0.5"),))
TWO_DESKS = replace(FAST_AUTH, operator_workstations=(("Line desk", "10.0.0.5"), ("Backup desk", "10.0.0.6")))
REQUESTS = "/api/v1/workflow/requests"


def operator(make_client):
    return make_client(roles=["OPERATOR"], address="10.0.0.5", auth=DESK)


def me(c) -> str:
    return c.get("/api/v1/auth/session").json()["user"]["username"]


def now(conn):
    return conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]


def mismatch(database, at_offset: timedelta = timedelta()) -> tuple:
    """An open HMI mismatch with its request, as monitor-core writes them (in the shift at now + at_offset)."""
    with database.connect() as conn:
        eid = event(conn, versions(conn), "HMI_MISMATCH", "P02", "V1", "OPEN", hmi=222)
        workflow_mod.open_request(conn, eid, now(conn) + at_offset)
        conn.commit()
        rid = conn.execute("SELECT id FROM workflow_request WHERE event_id = %s", (eid,)).fetchone()["id"]
    return eid, str(rid)


def test_the_operator_explains_and_answers_a_manager_guides_and_the_operator_acknowledges(make_client, database, owner):
    manager = make_client(roles=["MANAGER"])  # the first start imports the register
    eid, rid = mismatch(database)
    op = operator(make_client)
    listing = op.get(REQUESTS).json()
    (req,) = listing["requests"]
    assert (req["id"], req["status"], req["next"]) == (rid, "waiting_reason", "reason")
    assert (req["event"]["zoneName"], req["event"]["hmi"], req["event"]["target"]) == ("Vertical 1", "222", "180")
    assert listing["questions"] == ["What was changed, and why?", "Is the product affected?"] and listing["counts"]["reason"] == 1

    assert op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["a", "b"]}).json()["type"] == "/problems/wrong-step"
    assert op.post(f"{REQUESTS}/{rid}/reason", json={"text": "   "}).status_code == 422
    reason = "Pinalitan ang setpoint para sa bagong film roll"  # Filipino, kept as typed (WF-01)
    assert op.post(f"{REQUESTS}/{rid}/reason", json={"text": reason}).json()["next"] == "answers"
    assert op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Raised by 2 °C", ""]}).status_code == 422
    assert op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Raised by 2 °C for the new film", "No"]}).json()["next"] == "guidance"
    assert op.post(f"{REQUESTS}/{rid}/acknowledge").status_code == 409  # guidance comes first
    assert manager.post(f"{REQUESTS}/{rid}/reason", json={"text": "x"}).status_code == 403  # the operator's to write
    assert op.post(f"{REQUESTS}/{rid}/guidance", json={"text": "x"}).status_code == 403  # a Manager's
    guided = manager.post(f"{REQUESTS}/{rid}/guidance", json={"text": "Back to 220 °C unless QA approved the change"}).json()
    assert guided["next"] == "acknowledgment"
    done = op.post(f"{REQUESTS}/{rid}/acknowledge").json()
    assert done["status"] == "done" and done["next"] is None and done["closedAt"]
    o, m = me(op), me(manager)
    assert [(e["kind"], e["by"], e["question"]) for e in done["entries"]] == [
        ("reason", o, None), ("answer", o, "What was changed, and why?"), ("answer", o, "Is the product affected?"),
        ("guidance", m, None), ("acknowledgment", o, None)]
    assert done["entries"][0]["body"] == reason
    assert [r["status"] for r in manager.get(f"/api/v1/events/{eid}").json()["requests"]] == ["done"]  # in its evidence
    assert op.post(f"{REQUESTS}/{rid}/reason", json={"text": "again"}).json()["type"] == "/problems/request-closed"
    with owner.connect() as c, pytest.raises(psycopg.errors.RestrictViolation):
        c.execute("UPDATE workflow_entry SET body = 'rewritten'")  # what people wrote is kept, even against the owner


def test_the_questions_are_the_administrators_and_with_none_the_reason_goes_straight_to_guidance(make_client, database):
    admin = make_client(roles=["ADMINISTRATOR"])
    assert make_client(roles=["MANAGER"]).put("/api/v1/config/workflow", json={"questions": [], "reason": "x y z"}).status_code == 403
    assert admin.put("/api/v1/config/workflow", json={"questions": ["Why?"], "reason": ""}).status_code == 422
    r = admin.put("/api/v1/config/workflow", json={"questions": [" ", ""], "reason": "The reason alone, for now"}).json()
    assert r["questions"] == [] and [h["reason"] for h in r["history"]] == ["The reason alone, for now", "The starting questions (ADR-0025)"]
    assert any(e["summary"] == "Follow-up questions: none" for e in admin.get("/api/v1/config/register").json()["audit"])
    _, rid = mismatch(database)
    op = operator(make_client)
    assert op.post(f"{REQUESTS}/{rid}/reason", json={"text": "Film change"}).json()["next"] == "guidance"


def test_an_operator_signing_in_gets_a_request_for_each_mismatch_still_open(make_client, database):
    make_client(roles=["MANAGER"])  # the first start imports the register
    with database.connect() as conn:
        v = versions(conn)
        still_open = event(conn, v, "HMI_MISMATCH", "P02", "V1", "OPEN", hmi=222)  # raised before this shift: no request here
        event(conn, v, "HMI_MISMATCH", "P02", "V2", "RESOLVED", open_=False, hmi=217)
        event(conn, v, "ACTUAL", "P03", "FRONT", "WARNING", "WARNING", actual=186)
        conn.commit()
    op = operator(make_client)  # signing in opens the shift's requests
    (req,) = op.get(REQUESTS).json()["requests"]
    assert (req["event"]["id"], req["status"]) == (str(still_open), "waiting_reason")
    operator(make_client)  # another operator at the desk, same shift (it replaces the first one's session)
    with database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM workflow_request").fetchone()["n"] == 1  # still one per event


def test_a_request_of_another_shift_or_a_closed_one_takes_no_answers_and_the_session_ends_with_the_shift(make_client, database):
    manager = make_client(roles=["MANAGER"])  # the first start imports the register
    _, earlier = mismatch(database, at_offset=-timedelta(hours=9))  # raised in an earlier shift
    op = operator(make_client)
    assert op.post(f"{REQUESTS}/{earlier}/reason", json={"text": "x"}).json()["type"] == "/problems/other-shift"
    with database.connect() as conn:
        rid = conn.execute("SELECT r.id FROM workflow_request r JOIN shift_instance s ON s.id = r.shift_instance_id "
                           "WHERE s.starts_at <= now() AND s.ends_at > now()").fetchone()["id"]  # the one sign-in opened
        workflow_mod.close_requests(conn, conn.execute("SELECT event_id FROM workflow_request WHERE id = %s", (rid,)).fetchone()["event_id"],
                                    "RESOLVED", now(conn))
        conn.commit()
    closed = op.post(f"{REQUESTS}/{rid}/reason", json={"text": "x"}).json()
    assert closed["type"] == "/problems/request-closed" and "back on target" in closed["detail"]

    session = op.get("/api/v1/auth/session").json()
    assert session["session"]["endsWithShift"] and session["shift"]["code"] in "ABC" and session["session"]["shiftWarningS"] == 300
    with database.connect() as conn:  # as if this operator had signed in during the last shift
        conn.execute("UPDATE app_session SET created_at = created_at - interval '9 hours' WHERE kind = 'operator'")
        conn.commit()
    r = op.get(REQUESTS)
    assert r.status_code == 401 and r.json()["type"] == "/problems/shift-over"
    assert manager.get("/api/v1/auth/session").json()["session"]["endsWithShift"] is False
    with database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE action = 'auth.shift_over'").fetchone()["n"] == 1


def test_a_session_left_over_from_the_last_shift_ends_with_it_and_blocks_nobody(make_client, database):
    first = make_client(roles=["OPERATOR"], address="10.0.0.5", auth=TWO_DESKS)
    with database.connect() as conn:  # its browser closed just before the shift ended: a recent heartbeat, never looked up again
        conn.execute("UPDATE app_session SET created_at = created_at - interval '9 hours' WHERE kind = 'operator'")
        conn.commit()
    second = make_client(roles=["OPERATOR"], address="10.0.0.6", auth=TWO_DESKS)  # at the backup desk, with no takeover
    assert second.get(REQUESTS).status_code == 200
    assert first.get(REQUESTS).json()["type"] == "/problems/session-ended"
    with database.connect() as conn:
        actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'auth.%' ORDER BY seq")]
    assert "auth.shift_over" in actions and "auth.takeover" not in actions
