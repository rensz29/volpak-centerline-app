"""AT-05: one reason workflow per shift, two clarification maximum and 15-minute escalation.

URS v1.1 §8 (WF-01…03) and SES-05, as built in ADR-0025. monitor-core judges each mismatch on the simulated line;
the operator and the Manager answer through the api. With no Active OCAP, as here, every request goes to a Manager's
guidance, which the operator acknowledges: WF-01's "OCAP-or-guidance" on its guidance branch. Its OCAP branch, the
sections offered and chosen (ADR-0031), is AT-08's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from centerline_common import shifts
from .conftest import AT_THE_LINE, configure, wait_for

REQUESTS = "/api/v1/workflow/requests"
FILIPINO = "Pinalitan ang setpoint para sa bagong film roll"


def operator(make_client):
    """The shift's operator at the line desk; signing in opens the shift's requests (WF-02)."""
    return make_client(roles=["OPERATOR"], address="10.0.0.5", auth=AT_THE_LINE)


def requests_of(database, event_id) -> list[dict]:
    return wait_for(database, """SELECT r.status, s.starts_at FROM workflow_request r JOIN shift_instance s
                                   ON s.id = r.shift_instance_id WHERE r.event_id = %s ORDER BY s.starts_at""",
                    lambda rows: True, (event_id,))


def open_mismatch(owner, plant, channel: str = "P02.V1", setpoint: float = 222, start=None):
    """The line configured, monitor-core judging it, and a setpoint left off target past the 30 s mismatch delay."""
    configure(owner)
    p = plant(start)
    p.line.set(channel, setpoint=setpoint)
    p.run(31)
    (event,) = [e for e in owner.get("/api/v1/events?open=true").json()["events"] if e["channel"] == channel]
    assert event["kind"] == "HMI_MISMATCH"
    return p, event


@pytest.mark.urs("WF-01")
def test_each_mismatch_gets_one_reason_its_questions_a_managers_guidance_and_the_operators_acknowledgment(make_client, plant):
    owner = make_client()  # the owner: Manager and Administrator
    p, event = open_mismatch(owner, plant)
    op = operator(make_client)
    (req,) = op.get(REQUESTS).json()["requests"]
    assert (req["event"]["id"], req["status"], req["next"]) == (event["id"], "waiting_reason", "reason")
    rid = req["id"]

    assert op.post(f"{REQUESTS}/{rid}/reason", json={"text": FILIPINO}).json()["next"] == "answers"
    assert op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Raised by 2 °C for the new film", "No"]}).json()["next"] == "guidance"
    assert owner.post(f"{REQUESTS}/{rid}/guidance", json={"text": "Back to 220 °C unless QA approved it"}).json()["next"] == "acknowledgment"
    done = op.post(f"{REQUESTS}/{rid}/acknowledge").json()
    assert done["status"] == "done" and done["next"] is None
    assert [e["kind"] for e in done["entries"]] == ["reason", "answer", "answer", "guidance", "acknowledgment"]
    assert done["entries"][0]["body"] == FILIPINO  # kept as typed

    # an Actual event asks nobody for a reason
    p.line.set("P03.REAR", actual=200)  # 20 °C over its setpoint
    p.run(31 + 45)
    actual = [e for e in owner.get("/api/v1/events?open=true").json()["events"] if e["kind"] == "ACTUAL"]
    assert actual and [r["event"]["id"] for r in op.get(REQUESTS).json()["requests"]] == [event["id"]]


@pytest.mark.urs("WF-01")
def test_at_most_two_follow_up_questions_and_with_none_the_reason_goes_straight_to_guidance(make_client, plant):
    owner = make_client()
    assert owner.put("/api/v1/config/workflow", json={"questions": ["One?", "Two?", "Three?"], "reason": "Too many"}).status_code == 422
    assert owner.put("/api/v1/config/workflow", json={"questions": [], "reason": "The reason alone"}).status_code == 200
    open_mismatch(owner, plant)
    op = operator(make_client)
    (req,) = op.get(REQUESTS).json()["requests"]
    assert op.post(f"{REQUESTS}/{req['id']}/reason", json={"text": "New film roll"}).json()["next"] == "guidance"
    assert op.post(f"{REQUESTS}/{req['id']}/answers", json={"answers": ["a", "b", "c"]}).status_code == 422


@pytest.mark.urs("WF-02")
def test_a_finished_request_isnt_asked_again_in_its_shift_and_the_next_shift_gets_its_own_at_sign_in(make_client, plant, database):
    owner = make_client()
    this_shift = shifts.shift_at(datetime.now(timezone.utc))
    last_shift = this_shift.starts_at - shifts.LENGTH + timedelta(minutes=10)
    p, event = open_mismatch(owner, plant, start=last_shift)  # raised in the last shift, still off target
    assert len(requests_of(database, event["id"])) == 1  # that shift's request
    p.store.workflow_tick(this_shift.starts_at + timedelta(seconds=1), p.names)  # its shift ended unanswered

    op = operator(make_client)  # this shift's operator signs in: this shift's request, at once
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["event"]["id"] == event["id"] and req["status"] == "waiting_reason"
    assert [r["status"] for r in requests_of(database, event["id"])] == ["not_answered", "waiting_reason"]
    rid = req["id"]
    op.post(f"{REQUESTS}/{rid}/reason", json={"text": "Film roll"})
    op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Changed", "No"]})
    owner.post(f"{REQUESTS}/{rid}/guidance", json={"text": "Agreed with QA"})
    assert op.post(f"{REQUESTS}/{rid}/acknowledge").json()["status"] == "done"

    operator(make_client)  # signing in again in the same shift, the mismatch still open: no new request
    assert [r["status"] for r in requests_of(database, event["id"])] == ["not_answered", "done"]


@pytest.mark.urs("WF-03")
def test_a_request_still_open_after_15_minutes_alerts_management_once(make_client, plant, database):
    owner = make_client()
    p, event = open_mismatch(owner, plant)
    operator(make_client)
    p.run(31 + 14 * 60, every=5)
    escalations = "SELECT payload FROM notification WHERE kind = 'workflow_escalation'"
    assert wait_for(database, escalations, lambda rows: True, timeout=0) == []  # not before 15 min
    p.run(31 + 15 * 60 + 10, every=5)
    p.run(31 + 20 * 60, every=5)
    (escalation,) = wait_for(database, escalations, lambda rows: True, timeout=0)  # once
    payload = escalation["payload"]
    assert (payload["kind"], payload["zoneName"], payload["status"]) == ("Reason overdue", "Vertical 1", "waiting_reason")


@pytest.mark.urs("SES-05")
def test_a_request_closes_when_its_mismatch_resolves_or_is_superseded_so_the_unsent_text_is_dropped(make_client, plant):
    """The operator's unsent text lives only in that browser (localStorage) and is dropped when the request closes:
    the web app does it on these statuses, and on sign-out, handover and takeover (ADR-0025)."""
    owner = make_client()
    p, first = open_mismatch(owner, plant)
    op = operator(make_client)
    (req,) = op.get(REQUESTS).json()["requests"]
    p.line.set("P02.V1", setpoint=224)  # another off-target value: a new event replaces this one
    p.run(31 + 31)
    listing = op.get(REQUESTS).json()["requests"]
    superseded = next(r for r in listing if r["id"] == req["id"])
    current = next(r for r in listing if r["id"] != req["id"])
    assert superseded["status"] == "superseded" and current["status"] == "waiting_reason"
    assert op.post(f"{REQUESTS}/{req['id']}/reason", json={"text": "late"}).json()["type"] == "/problems/request-closed"

    p.line.set("P02.V1", setpoint=220)  # back on target
    p.run(31 + 31 + 2)
    assert next(r for r in op.get(REQUESTS).json()["requests"] if r["id"] == current["id"])["status"] == "resolved"
