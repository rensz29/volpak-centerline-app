"""The reason workflow (WF-01…03, ADR-0025, ADR-0031): each HMI mismatch asks that shift's operator why.

A request moves through its steps in order:
1. the operator's reason, in English or Filipino, kept as typed;
2. answers to the follow-up questions in effect (none: this step is skipped);
3. up to three OCAP sections that match the event and what was written, for the operator to choose one or "None of
   these apply" (OCP-01); with no match the request goes straight on;
4. with no OCAP chosen, a Manager's guidance: text, one optional PDF or Word attachment, and maybe kept as a reusable
   OCAP (GDE-01);
5. the operator's acknowledgment of the chosen section or of the guidance: review only (OCP-02).

monitor-core opens and closes requests (with the event, at the shift's end, after 15 min an alert);
the api records each step. An operator answers only their own shift's requests. Every role reads them.
"""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

from centerline_common import shifts
from centerline_common import workflow as workflow_mod
from centerline_common.db import uuid7
from fastapi import APIRouter, Depends, Request, Response
from psycopg.types.json import Jsonb
from pydantic import Field

from ..auth.deps import ADMIN_ONLY, MANAGER_ONLY, OPERATOR_ONLY, PRIVILEGED, SIGNED_IN
from ..config import audit
from ..config.audit import iso
from ..config.models import _Camel
from ..config.versioning import reason_errors
from ..database import connect
from ..ocap.parse import MAX_BYTES
from ..ocap.store import CODE, LANGUAGES, OcapStore, checked_file, decode_upload
from ..problems import Problem

router = APIRouter(prefix="/api/v1", tags=["workflow"])

TEXT_MAX = 2000
NEXT = {"waiting_reason": "reason", "waiting_answers": "answers", "waiting_ocap": "ocap", "waiting_guidance": "guidance",
        "waiting_acknowledgment": "acknowledgment"}
BASE64_MAX = (MAX_BYTES * 4) // 3 + 8
EXCERPT = 280
COLUMNS = """r.id, r.event_id, r.status, r.created_at, r.escalated_at, r.closed_at, s.code AS shift_code, s.starts_at,
             s.ends_at, s.production_date, e.kind, e.parameter_id, e.zone_id, e.opened_at, e.raw_hmi,
             e.raw_target, st.open AS event_open, st.state AS event_state"""
FROM = """FROM workflow_request r JOIN shift_instance s ON s.id = r.shift_instance_id
          JOIN event e ON e.id = r.event_id JOIN event_state st ON st.event_id = e.id"""


class TextIn(_Camel):
    text: str = Field(max_length=TEXT_MAX)


class AnswersIn(_Camel):
    answers: list[str] = Field(max_length=2)


class OcapChoiceIn(_Camel):
    section_id: UUID | None = Field(None, description="One of the sections offered; empty: none of these apply")


class AttachmentIn(_Camel):
    name: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(max_length=BASE64_MAX)


class ReusableIn(_Camel):
    code: str = Field(max_length=40, description="The new OCAP's code, e.g. OCAP-050")
    title: str = Field(max_length=200)
    language: str = "en"


class GuidanceIn(TextIn):
    attachment: AttachmentIn | None = Field(None, description="One PDF or Word file (GDE-01)")
    reusable: ReusableIn | None = Field(None, description="Also keep this guidance as a reusable OCAP (GDE-01)")


class QuestionsIn(_Camel):
    questions: list[str] = Field(max_length=2)
    reason: str = ""


def questions(conn) -> list[str]:
    return conn.execute("SELECT questions FROM workflow_settings ORDER BY seq DESC LIMIT 1").fetchone()["questions"]


def _num(v) -> str | None:
    return None if v is None else format(v.normalize(), "f")


def _entry(e: dict, sections: dict, attachments: dict) -> dict:
    out = {"kind": e["kind"], "at": iso(e["at"]), "by": e["by_user"], "question": e["question"], "body": e["body"]}
    if e.get("ocap_section_id") is not None:
        out["section"] = sections.get(e["ocap_section_id"])
    if e["id"] in attachments:
        out["attachment"] = attachments[e["id"]]
    return out


def _view(r: dict, entries: list[dict], names: dict, offered: list | None = None, sections: dict | None = None,
          attachments: dict | None = None) -> dict:
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
            "offered": [{**{k: v for k, v in (sections or {}).get(o["section_id"], {}).items() if k != "body"},
                         "rank": o["rank"], "score": round(float(o["score"]), 4),
                         "excerpt": (sections or {}).get(o["section_id"], {}).get("body", "")[:EXCERPT]} for o in offered or []],
            "entries": [_entry(e, sections or {}, attachments or {}) for e in entries]}


def _names(request: Request, conn) -> dict:
    register = request.app.state.register_store.load(conn)
    return {z.channel: {"parameterName": z.parameter_name, "zoneName": z.zone_name, "unit": z.unit} for z in register.zones}


def _entries(conn, ids: list) -> dict:
    out: dict = {}
    if ids:
        for e in conn.execute("SELECT * FROM workflow_entry WHERE request_id = ANY(%s) ORDER BY seq", (ids,)):
            out.setdefault(e["request_id"], []).append(e)
    return out


def _views(conn, rows: list[dict], names: dict) -> list[dict]:
    """The requests with what was written, the OCAP sections offered and chosen, and the guidance's attachments."""
    ids = [r["id"] for r in rows]
    entries = _entries(conn, ids)
    offered: dict = {}
    if ids:
        for o in conn.execute("SELECT request_id, rank, section_id, score FROM ocap_recommendation WHERE request_id = ANY(%s) ORDER BY rank",
                              (ids,)):
            offered.setdefault(o["request_id"], []).append(o)
    wanted = {o["section_id"] for os_ in offered.values() for o in os_}
    wanted |= {e["ocap_section_id"] for es in entries.values() for e in es if e.get("ocap_section_id")}
    sections = OcapStore.sections(conn, list(wanted))
    entry_ids = [e["id"] for es in entries.values() for e in es if e["kind"] == "guidance"]
    attachments = {a["entry_id"]: {"id": str(a["id"]), "name": a["name"], "mediaType": a["media_type"], "size": a["size"],
                                   "scan": a["scan"]}
                   for a in (conn.execute("""SELECT id, entry_id, name, media_type, length(content) AS size, scan
                                               FROM workflow_attachment WHERE entry_id = ANY(%s)""", (entry_ids,))
                             if entry_ids else [])}
    return [_view(r, entries.get(r["id"], []), names, offered.get(r["id"]), sections, attachments) for r in rows]


def requests_of_event(conn, event_id, names: dict) -> list[dict]:
    """Every request an event raised, one per shift, with what was written: for the event's evidence."""
    rows = conn.execute(f"SELECT {COLUMNS} {FROM} WHERE r.event_id = %s ORDER BY r.created_at", (event_id,)).fetchall()
    return _views(conn, rows, names)


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
    views = _views(conn, rows, _names(request, conn))
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
    return _views(conn, [r], names)[0] | {"questions": questions(conn)}


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


def _add(conn, request_id, kind: str, by: str, body: str, now, question: str | None = None, section=None):
    eid = uuid7()
    conn.execute("""INSERT INTO workflow_entry (id, request_id, kind, at, by_user, question, body, ocap_section_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", (eid, request_id, kind, now, by, question, body, section))
    return eid


def _offer(request: Request, conn, request_id, now) -> str:
    """After the reason and the answers: up to three OCAP sections to choose from (OCP-01), found by the event's zone
    and direction and by what was written; or, with none, straight on to a Manager's guidance."""
    r = conn.execute("""SELECT e.parameter_id, e.zone_id, e.raw_hmi, e.raw_target FROM workflow_request q
                          JOIN event e ON e.id = q.event_id WHERE q.id = %s""", (request_id,)).fetchone()
    zone = _names(request, conn).get(f"{r['parameter_id']}.{r['zone_id']}", {})
    written = [e["body"] for e in conn.execute("""SELECT body FROM workflow_entry WHERE request_id = %s
                                                     AND kind IN ('reason', 'answer') ORDER BY seq""", (request_id,))]
    direction = None
    if r["raw_hmi"] is not None and r["raw_target"] is not None:
        direction = "high above higher increased" if r["raw_hmi"] > r["raw_target"] else "low below lower decreased"
    query = " ".join(x for x in [zone.get("parameterName"), zone.get("zoneName"), "HMI setpoint", direction, *written] if x)
    hits = request.app.state.ocap_store.search(conn, query, limit=3)
    for rank, h in enumerate(hits, start=1):
        conn.execute("""INSERT INTO ocap_recommendation (request_id, rank, section_id, score, method, query, at)
                        VALUES (%s, %s, %s, %s, 'keyword', %s, %s)""", (request_id, rank, h["sectionId"], h["score"], query, now))
    return "waiting_ocap" if hits else "waiting_guidance"


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
    _move(conn, request_id, "waiting_answers" if questions(conn) else _offer(request, conn, request_id, now), now)
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
    _move(conn, request_id, _offer(request, conn, request_id, now), now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.post("/workflow/requests/{request_id}/ocap", dependencies=[OPERATOR_ONLY],
             summary="The OCAP section that applies, of those offered, or none of them (OCP-01)")
def choose_ocap(request_id: UUID, body: OcapChoiceIn, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "ocap", True, now)
    by = request.state.principal.username
    if body.section_id is None:
        _add(conn, request_id, "ocap_choice", by, "None of these apply", now)
        _move(conn, request_id, "waiting_guidance", now)
    else:
        offered = {o["section_id"] for o in conn.execute("SELECT section_id FROM ocap_recommendation WHERE request_id = %s",
                                                         (request_id,))}
        if body.section_id not in offered:
            raise Problem(422, "not-offered", "That section wasn't offered", "Choose one of the sections offered, or none",
                          errors=[{"field": "sectionId", "message": "Not one of those offered"}])
        section = request.app.state.ocap_store.sections(conn, [body.section_id])[body.section_id]
        _add(conn, request_id, "ocap_choice", by, section["citation"], now, section=body.section_id)
        _move(conn, request_id, "waiting_acknowledgment", now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.post("/workflow/requests/{request_id}/guidance", dependencies=[MANAGER_ONLY],
             summary="A Manager's guidance when no OCAP applies: text, one optional file, maybe a reusable OCAP (GDE-01)")
def give_guidance(request_id: UUID, body: GuidanceIn, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "guidance", False, now)
    text = _text(body, "guidance")
    by = request.state.principal.username
    errors = []
    if body.reusable is not None:
        code = body.reusable.code.strip()
        if not CODE.fullmatch(code):
            errors.append({"field": "reusable.code", "message": "The new OCAP's code, e.g. OCAP-050: letters, digits, . _ / -"})
        elif conn.execute("SELECT 1 FROM ocap_document WHERE lower(code) = lower(%s)", (code,)).fetchone():
            errors.append({"field": "reusable.code", "message": f"{code} already exists: choose another code"})
        if not body.reusable.title.strip():
            errors.append({"field": "reusable.title", "message": "A title for the new OCAP"})
        if body.reusable.language not in LANGUAGES:
            errors.append({"field": "reusable.language", "message": "English (en) or Filipino (fil)"})
    if errors:
        raise Problem(422, "invalid", "The guidance can't be saved", "; ".join(e["message"] for e in errors), errors=errors)
    file = None
    if body.attachment is not None:  # scanned before anything is written (SEC-01)
        data = decode_upload(body.attachment.content_base64, "attachment.contentBase64")
        file = (data, *checked_file(conn, data, body.attachment.name, request.app.state.settings.scanner, "Guidance attachment"))
    entry = _add(conn, request_id, "guidance", by, text, now)
    if file is not None:
        data, media_type, verdict, detail = file
        conn.execute("""INSERT INTO workflow_attachment (id, entry_id, name, media_type, content, sha256, scan, scan_detail, at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (uuid7(), entry, body.attachment.name.strip(), media_type, data, hashlib.sha256(data).hexdigest(),
                      verdict, detail, now))
    if body.reusable is not None:
        request.app.state.ocap_store.write(conn, body.reusable.code, body.reusable.title, body.reusable.language, text,
                                           f"Written from {by}'s guidance on a reason request")
    _move(conn, request_id, "waiting_acknowledgment", now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.get("/workflow/attachments/{attachment_id}", dependencies=[SIGNED_IN], summary="A guidance's file, as it was uploaded")
def attachment(attachment_id: UUID, conn=Depends(connect)) -> Response:
    a = conn.execute("SELECT name, media_type, content FROM workflow_attachment WHERE id = %s", (attachment_id,)).fetchone()
    if a is None:
        raise Problem(404, "not-found", "No such file", "Reload the page")
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", a["name"]).strip() or "attachment"
    return Response(bytes(a["content"]), media_type=a["media_type"], headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.post("/workflow/requests/{request_id}/acknowledge", dependencies=[OPERATOR_ONLY],
             summary="The operator has reviewed the OCAP section or the guidance (WF-01, OCP-02: review only)")
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
