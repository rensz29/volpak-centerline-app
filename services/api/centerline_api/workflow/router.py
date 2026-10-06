"""The reason workflow (WF-01…03, ADR-0025): each HMI mismatch asks that shift's operator why.

A request moves through its steps in order:
1. the operator's reason, in English or Filipino, kept as typed;
2. answers to the follow-up questions in effect (none: this step is skipped);
3. a Manager's guidance, since OCAP matching comes with Phase 3 (GDE-01);
4. the operator's acknowledgment of that guidance.

monitor-core opens and closes requests (with the event, at the shift's end, after 15 min an alert);
the api records each step. An operator answers only their own shift's requests. Every role reads them.
"""

from __future__ import annotations

from uuid import UUID

from centerline_common import shifts
from centerline_common import workflow as workflow_mod
from centerline_common.db import uuid7
from fastapi import APIRouter, Depends, Request
from psycopg.types.json import Jsonb
from pydantic import Field

from ..auth.deps import ADMIN_ONLY, MANAGER_ONLY, OPERATOR_ONLY, PRIVILEGED, SIGNED_IN
from ..config import audit
from ..config.audit import iso
from ..config.models import _Camel
from ..config.versioning import reason_errors
from ..database import connect
from ..problems import Problem

router = APIRouter(prefix="/api/v1", tags=["workflow"])

TEXT_MAX = 2000
NEXT = {"waiting_reason": "reason", "waiting_answers": "answers", "waiting_guidance": "guidance",
        "waiting_acknowledgment": "acknowledgment"}
COLUMNS = """r.id, r.event_id, r.status, r.created_at, r.escalated_at, r.closed_at, s.code AS shift_code, s.starts_at,
             s.ends_at, s.production_date, e.kind, e.parameter_id, e.zone_id, e.opened_at, e.raw_hmi,
             e.raw_target, st.open AS event_open, st.state AS event_state"""
FROM = """FROM workflow_request r JOIN shift_instance s ON s.id = r.shift_instance_id
          JOIN event e ON e.id = r.event_id JOIN event_state st ON st.event_id = e.id"""


class TextIn(_Camel):
    text: str = Field(max_length=TEXT_MAX)


class AnswersIn(_Camel):
    answers: list[str] = Field(max_length=2)


class QuestionsIn(_Camel):
    questions: list[str] = Field(max_length=2)
    reason: str = ""


def questions(conn) -> list[str]:
    return conn.execute("SELECT questions FROM workflow_settings ORDER BY seq DESC LIMIT 1").fetchone()["questions"]


def _num(v) -> str | None:
    return None if v is None else format(v.normalize(), "f")


def _view(r: dict, entries: list[dict], names: dict) -> dict:
    ch = f"{r['parameter_id']}.{r['zone_id']}"
    zone = names.get(ch, {})
    shift = shifts.Shift(r["shift_code"], r["starts_at"], r["ends_at"], r["production_date"])
    return {"id": str(r["id"]), "status": r["status"], "next": NEXT.get(r["status"]), "createdAt": iso(r["created_at"]),
            "escalatedAt": iso(r["escalated_at"]), "closedAt": iso(r["closed_at"]),
            "shift": {"code": shift.code, "label": shifts.label(shift), "startsAt": iso(shift.starts_at), "endsAt": iso(shift.ends_at)},
            "event": {"id": str(r["event_id"]), "channel": ch, "parameterId": r["parameter_id"], "zoneId": r["zone_id"],
                      "parameterName": zone.get("parameterName"), "zoneName": zone.get("zoneName"), "unit": zone.get("unit"),
                      "openedAt": iso(r["opened_at"]), "hmi": _num(r["raw_hmi"]),
                      "target": _num(r["raw_target"]), "open": r["event_open"], "state": r["event_state"]},
            "entries": [{"kind": e["kind"], "at": iso(e["at"]), "by": e["by_user"], "question": e["question"], "body": e["body"]}
                        for e in entries]}


def _names(request: Request, conn) -> dict:
    register = request.app.state.register_store.load(conn)
    return {z.channel: {"parameterName": z.parameter_name, "zoneName": z.zone_name, "unit": z.unit} for z in register.zones}


def _entries(conn, ids: list) -> dict:
    out: dict = {}
    if ids:
        for e in conn.execute("SELECT * FROM workflow_entry WHERE request_id = ANY(%s) ORDER BY seq", (ids,)):
            out.setdefault(e["request_id"], []).append(e)
    return out


def requests_of_event(conn, event_id, names: dict) -> list[dict]:
    """Every request an event raised, one per shift, with what was written: for the event's evidence."""
    rows = conn.execute(f"SELECT {COLUMNS} {FROM} WHERE r.event_id = %s ORDER BY r.created_at", (event_id,)).fetchall()
    entries = _entries(conn, [r["id"] for r in rows])
    return [_view(r, entries.get(r["id"], []), names) for r in rows]


@router.get("/workflow/requests", dependencies=[SIGNED_IN],
            summary="An operator's requests this shift; for Managers and Administrators, every open one and the last day's")
def list_requests(request: Request, conn=Depends(connect)) -> dict:
    p = request.state.principal
    now = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
    current = shifts.shift_at(now)
    if p.kind == "operator":
        rows = conn.execute(f"SELECT {COLUMNS} {FROM} WHERE s.starts_at = %s ORDER BY r.created_at DESC",
                            (current.starts_at,)).fetchall()
    else:
        rows = conn.execute(f"""SELECT {COLUMNS} {FROM} WHERE r.closed_at IS NULL OR r.closed_at > %s - interval '24 hours'
                                 ORDER BY r.closed_at IS NOT NULL, r.created_at DESC LIMIT 200""", (now,)).fetchall()
    entries = _entries(conn, [r["id"] for r in rows])
    names = _names(request, conn)
    views = [_view(r, entries.get(r["id"], []), names) for r in rows]
    counts = {step: sum(1 for v in views if v["next"] == step) for step in NEXT.values()}
    return {"requests": views, "questions": questions(conn), "counts": counts,
            "shift": {"code": current.code, "label": shifts.label(current), "endsAt": iso(current.ends_at)}}


@router.get("/workflow/requests/{request_id}", dependencies=[SIGNED_IN], summary="One request, with everything written on it")
def get_request(request_id: UUID, request: Request, conn=Depends(connect)) -> dict:
    return _one(conn, request_id, _names(request, conn))


def _one(conn, request_id, names: dict) -> dict:
    r = conn.execute(f"SELECT {COLUMNS} {FROM} WHERE r.id = %s", (request_id,)).fetchone()
    if r is None:
        raise Problem(404, "not-found", "No such request", "Reload the page")
    return _view(r, _entries(conn, [r["id"]]).get(r["id"], []), names) | {"questions": questions(conn)}


def _locked(conn, request_id, step: str, operator: bool, now) -> dict:
    """The request, locked for this step; refused when it isn't waiting for it, or isn't this shift's."""
    r = conn.execute("""SELECT r.id, r.status, s.starts_at FROM workflow_request r JOIN shift_instance s ON s.id = r.shift_instance_id
                         WHERE r.id = %s FOR UPDATE OF r""", (request_id,)).fetchone()
    if r is None:
        raise Problem(404, "not-found", "No such request", "Reload the page")
    if r["status"] not in NEXT:
        raise Problem(409, "request-closed", "This request is closed",
                      {"done": "It's done.", "not_answered": "Its shift ended before it was finished.",
                       "resolved": "Its HMI setpoint is back on target.", "superseded": "A newer mismatch on the zone replaced it.",
                       "cancelled": "Its event was closed: the zone was switched off."}[r["status"]])
    if NEXT[r["status"]] != step:
        raise Problem(409, "wrong-step", "That isn't this request's next step",
                      f"It's waiting for the {NEXT[r['status']]} now. Reload the page.", next=NEXT[r["status"]])
    if operator and r["starts_at"] != shifts.shift_at(now).starts_at:
        raise Problem(409, "other-shift", "This request belongs to another shift", "Each shift answers its own requests.")
    return r


def _text(body: TextIn, what: str) -> str:
    text = body.text.strip()
    if not text:
        raise Problem(422, "invalid", f"Write the {what}", f"The {what} can't be empty", errors=[{"field": "text", "message": f"Write the {what}"}])
    return text


def _add(conn, request_id, kind: str, by: str, body: str, now, question: str | None = None) -> None:
    conn.execute("""INSERT INTO workflow_entry (id, request_id, kind, at, by_user, question, body)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""", (uuid7(), request_id, kind, now, by, question, body))


def _move(conn, request_id, status: str, now) -> None:
    closed = None if status in workflow_mod.OPEN else now
    conn.execute("UPDATE workflow_request SET status = %s, closed_at = %s, updated_at = %s WHERE id = %s",
                 (status, closed, now, request_id))


def _now(conn):
    return conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]


@router.post("/workflow/requests/{request_id}/reason", dependencies=[OPERATOR_ONLY], summary="The operator's reason (WF-01)")
def give_reason(request_id: UUID, body: TextIn, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "reason", True, now)
    _add(conn, request_id, "reason", request.state.principal.username, _text(body, "reason"), now)
    _move(conn, request_id, "waiting_answers" if questions(conn) else "waiting_guidance", now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.post("/workflow/requests/{request_id}/answers", dependencies=[OPERATOR_ONLY],
             summary="Answers to the follow-up questions in effect, in their order (WF-02)")
def give_answers(request_id: UUID, body: AnswersIn, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "answers", True, now)
    asked = questions(conn)
    answers = [a.strip() for a in body.answers]
    errors = [{"field": f"answers[{i}]", "message": "Answer the question"} for i in range(len(asked))
              if i >= len(answers) or not answers[i]]
    if errors or len(answers) > len(asked):
        raise Problem(422, "invalid", "Answer each question", "Every question needs an answer", errors=errors)
    for q, a in zip(asked, answers):
        _add(conn, request_id, "answer", request.state.principal.username, a, now, question=q)
    _move(conn, request_id, "waiting_guidance", now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.post("/workflow/requests/{request_id}/guidance", dependencies=[MANAGER_ONLY],
             summary="A Manager's guidance for the operator, while OCAP matching waits for Phase 3 (GDE-01)")
def give_guidance(request_id: UUID, body: TextIn, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "guidance", False, now)
    _add(conn, request_id, "guidance", request.state.principal.username, _text(body, "guidance"), now)
    _move(conn, request_id, "waiting_acknowledgment", now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.post("/workflow/requests/{request_id}/acknowledge", dependencies=[OPERATOR_ONLY],
             summary="The operator has read the guidance (WF-01: one acknowledgment)")
def acknowledge(request_id: UUID, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "acknowledgment", True, now)
    _add(conn, request_id, "acknowledgment", request.state.principal.username, "", now)
    _move(conn, request_id, "done", now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.get("/config/workflow", dependencies=[PRIVILEGED], summary="The follow-up questions in effect, and their changes")
def get_settings(conn=Depends(connect)) -> dict:
    history = conn.execute("SELECT questions, at, by_user, reason FROM workflow_settings ORDER BY seq DESC LIMIT 10").fetchall()
    return {"questions": history[0]["questions"],
            "history": [{"questions": h["questions"], "at": iso(h["at"]), "by": h["by_user"], "reason": h["reason"]} for h in history]}


@router.put("/config/workflow", dependencies=[ADMIN_ONLY], summary="Change the follow-up questions (up to two)")
def put_settings(body: QuestionsIn, request: Request, conn=Depends(connect)) -> dict:
    asked = [q.strip() for q in body.questions if q.strip()]
    errors = reason_errors(body.reason) + [{"field": f"questions[{i}]", "message": "At most 200 characters"}
                                           for i, q in enumerate(asked) if len(q) > 200]
    if errors:
        raise Problem(422, "invalid", "The questions can't be saved", "Check the fields", errors=errors)
    conn.execute(f"INSERT INTO workflow_settings (questions, by_user, reason) VALUES (%s, {audit.ACTOR}, %s)",
                 (Jsonb(asked), body.reason.strip()))
    audit.record(conn, "workflow.questions", "Follow-up questions: " + (" · ".join(asked) if asked else "none"), body.reason,
                 {"questions": asked})
    conn.commit()
    return get_settings(conn)
