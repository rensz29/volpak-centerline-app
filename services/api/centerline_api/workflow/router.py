"""The reason workflow (WF-01…03, ADR-0025, ADR-0031): each HMI mismatch asks that shift's operator why.

A request moves through its steps in order:
1. the operator's reason: picked from the Excel OCAP rows offered for the mismatch's parameter and direction, with an
   optional note, or typed in English or Filipino and kept as typed (ADR-0039);
2. answers to the follow-up questions: at most two the local model writes from the OCAP sections for the reason, or,
   when it's off, slow or wrong, the fixed ones in effect (none: this step is skipped); a request keeps the questions it
   asked (ADR-0041). Before the reason, the model has asked the opening question, from the OCAP rows for the mismatch
   (ADR-0042, ai/opening.py);
3. up to three OCAP sections that match the event and what was written, for the operator to choose one or "None of
   these apply" (OCP-01); with no match the request goes straight on. A reason picked from an OCAP offers its own
   section only;
4. with no OCAP chosen, a Manager's guidance: text, one optional PDF or Word attachment, and maybe kept as a reusable
   OCAP (GDE-01);
5. the operator's acknowledgment of the chosen section or of the guidance: review only (OCP-02).

monitor-core opens and closes requests (with the event, at the shift's end, after 15 min an alert);
the api records each step. An operator answers only their own shift's requests. Every role reads them.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
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
from ..ai import calls as ai_calls
from ..ai import questions as ai_questions
from ..database import connect
from ..ocap.parse import MAX_BYTES
from ..ocap.choices import direction_of
from ..ocap.store import CODE, LANGUAGES, OcapStore, checked_file, decode_upload
from ..problems import Problem
from ..storage import refuse_uploads

router = APIRouter(prefix="/api/v1", tags=["workflow"])

TEXT_MAX = 2000
NEXT = {"waiting_reason": "reason", "waiting_answers": "answers", "waiting_ocap": "ocap", "waiting_guidance": "guidance",
        "waiting_acknowledgment": "acknowledgment"}
BASE64_MAX = (MAX_BYTES * 4) // 3 + 8
EXCERPT = 280
COLUMNS = """r.id, r.event_id, r.status, r.created_at, r.updated_at, r.escalated_at, r.closed_at, s.code AS shift_code, s.starts_at,
             s.ends_at, s.production_date, e.kind, e.parameter_id, e.zone_id, e.opened_at, e.raw_hmi,
             e.raw_target, st.open AS event_open, st.state AS event_state"""
FROM = """FROM workflow_request r JOIN shift_instance s ON s.id = r.shift_instance_id
          JOIN event e ON e.id = r.event_id JOIN event_state st ON st.event_id = e.id"""


class TextIn(_Camel):
    text: str = Field(max_length=TEXT_MAX)


class ReasonIn(_Camel):
    text: str = Field("", max_length=TEXT_MAX, description="A reason typed by the operator")
    section_id: UUID | None = Field(None, description="Or one of the request's `choices` (ADR-0039)")
    note: str = Field("", max_length=TEXT_MAX, description="With a picked reason: anything to add")


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
          attachments: dict | None = None, choices: list | None = None, asked: list | None = None,
          summary: dict | None = None) -> dict:
    ch = f"{r['parameter_id']}.{r['zone_id']}"
    zone = names.get(ch, {})
    shift = shifts.Shift(r["shift_code"], r["starts_at"], r["ends_at"], r["production_date"])
    return {"id": str(r["id"]), "status": r["status"], "next": NEXT.get(r["status"]), "createdAt": iso(r["created_at"]),
            "updatedAt": iso(r["updated_at"]),
            "escalatedAt": iso(r["escalated_at"]), "closedAt": iso(r["closed_at"]),
            "shift": {"code": shift.code, "label": shifts.label(shift), "startsAt": iso(shift.starts_at), "endsAt": iso(shift.ends_at)},
            "event": {"id": str(r["event_id"]), "channel": ch, "parameterId": r["parameter_id"], "zoneId": r["zone_id"],
                      "parameterName": zone.get("parameterName"), "zoneName": zone.get("zoneName"), "unit": zone.get("unit"),
                      "openedAt": iso(r["opened_at"]), "hmi": _num(r["raw_hmi"]),
                      "target": _num(r["raw_target"]), "open": r["event_open"], "state": r["event_state"]},
            "offered": [{**{k: v for k, v in (sections or {}).get(o["section_id"], {}).items() if k != "body"},
                         "rank": o["rank"], "score": round(float(o["score"]), 4), "method": o["method"],
                         "excerpt": (sections or {}).get(o["section_id"], {}).get("body", "")[:EXCERPT]} for o in offered or []],
            # While it waits for the reason: the OCAP rows the operator can pick it from (ADR-0039)
            "choices": choices or [],
            # The follow-up questions it asked, and who wrote them (ADR-0041); None before the reason
            "asked": [{"question": q["question"], "questionFil": q["fil"], "by": q["by"]} for q in asked or [] if q["ordinal"] > 0] or None,
            # The first question, asked as soon as it opened: the AI's or the fixed one (ADR-0042); None until written
            "opening": next(({"question": q["question"], "questionFil": q["fil"], "by": q["by"]} for q in asked or [] if q["ordinal"] == 0),
                            None),
            # The AI's summary of the sections offered, citing some of them (OCP-02, ADR-0046); None without one
            "summary": None if summary is None else {
                "text": summary["summary"], "textFil": summary["summary_fil"], "at": iso(summary["at"]), "by": "ai",
                "sections": [{"sectionId": str(i), "citation": (sections or {}).get(i, {}).get("citation")} for i in summary["section_ids"]]},
            "summaryTried": summary is not None or bool(r.get("summary_tried")),
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
        for o in conn.execute("""SELECT request_id, rank, section_id, score, method FROM ocap_recommendation
                                  WHERE request_id = ANY(%s) ORDER BY rank""",
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
    found: dict = {}

    def choices(r: dict) -> list:
        if r["status"] != "waiting_reason":
            return []
        key = (r["parameter_id"], direction_of(r["raw_hmi"], r["raw_target"]))
        if key not in found:
            found[key] = OcapStore.choices(conn, *key)
        return found[key]

    asked = _asked(conn, ids)
    summaries = {x["request_id"]: x for x in conn.execute("SELECT * FROM workflow_summary WHERE request_id = ANY(%s)", (ids,))} if ids else {}
    tried = {x["request_id"] for x in conn.execute("""SELECT DISTINCT request_id FROM ai_call WHERE purpose = 'summary'
                                                       AND request_id = ANY(%s)""", (ids,))} if ids else set()
    return [_view(r | {"summary_tried": r["id"] in tried}, entries.get(r["id"], []), names, offered.get(r["id"]), sections, attachments,
                  choices(r), asked.get(r["id"]), summaries.get(r["id"]))
            for r in rows]


def _asked(conn, ids: list) -> dict:
    """Each request's follow-up questions, in order, with who wrote them ("ai" or "fixed")."""
    out: dict = {}
    if ids:
        for q in conn.execute("""SELECT request_id, ordinal, question, question_fil, asked_by FROM workflow_question
                                  WHERE request_id = ANY(%s) ORDER BY ordinal""", (ids,)):
            out.setdefault(q["request_id"], []).append({"ordinal": q["ordinal"], "question": q["question"], "fil": q["question_fil"],
                                                        "by": q["asked_by"]})
    return out


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
    return {"requests": _waiting_for_opening(request, views, now), "questions": questions(conn), "counts": counts,
            "aiOpening": _ai_opens(request),
            "shift": {"code": current.code, "label": shifts.label(current), "endsAt": iso(current.ends_at)}}


@router.get("/workflow/requests/{request_id}", dependencies=[SIGNED_IN], summary="One request, with everything written on it")
def get_request(request_id: UUID, request: Request, conn=Depends(connect)) -> dict:
    return _one(conn, request_id, _names(request, conn))


OPENING_WAIT_S = 45  # how long the chat waits for the AI's opening question before asking the fixed one (ADR-0042)
SUMMARY_WAIT_S = 60  # how long the chat says the AI's summary is on its way (ADR-0046)


def _ai_opens(request: Request) -> bool:
    ai = request.app.state.settings.ai
    return bool(ai.enabled and ai.model and ai.open_every_s > 0)


def _ai_summarises(request: Request) -> bool:
    ai = request.app.state.settings.ai
    return bool(ai.enabled and ai.model and ai.summary_every_s > 0)


def _waiting_for_opening(request: Request, views: list[dict], now) -> list[dict]:
    """Each view says whether its AI opening question, or its AI summary, is still on its way: worth a few seconds' wait
    in the chat."""
    opens, sums = _ai_opens(request), _ai_summarises(request)
    for v in views:
        age = (now - datetime.fromisoformat(v["createdAt"].replace("Z", "+00:00"))).total_seconds()
        v["openingPending"] = opens and v["opening"] is None and v["next"] == "reason" and age < OPENING_WAIT_S
        moved = (now - datetime.fromisoformat(v["updatedAt"].replace("Z", "+00:00"))).total_seconds()
        v["summaryPending"] = sums and not v["summaryTried"] and v["next"] == "ocap" and bool(v["offered"]) and moved < SUMMARY_WAIT_S
    return views


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


def _text(body: TextIn | ReasonIn, what: str) -> str:
    text = body.text.strip()
    if not text:
        raise Problem(422, "invalid", f"Write the {what}", f"The {what} can't be empty", errors=[{"field": "text", "message": f"Write the {what}"}])
    return text


def _add(conn, request_id, kind: str, by: str, body: str, now, question: str | None = None, section=None):
    eid = uuid7()
    conn.execute("""INSERT INTO workflow_entry (id, request_id, kind, at, by_user, question, body, ocap_section_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", (eid, request_id, kind, now, by, question, body, section))
    return eid


def _query(zone: dict, r: dict, written: list[str]) -> str:
    """What the keyword search looks for: the zone, the direction of the change, and what the operator wrote."""
    direction = None
    if r["raw_hmi"] is not None and r["raw_target"] is not None:
        direction = "high above higher increased" if r["raw_hmi"] > r["raw_target"] else "low below lower decreased"
    return " ".join(x for x in [zone.get("parameterName"), zone.get("zoneName"), "HMI setpoint", direction, *written] if x)


def _meaning(written: list[str]) -> str:
    """What the search by meaning compares (ADR-0048): only what the operator wrote. The keyword search carries the
    sealer and the direction; here they'd outweigh the reason, as they do there."""
    return "\n".join(written)


def _ask(request: Request, conn, request_id, now) -> list[str]:
    """The request's follow-up questions, kept with it: the local model's, from the OCAP sections for the reason (the
    picked row, or the three a typed reason finds), or the fixed ones in effect (AI-01, AI-02, ADR-0041)."""
    r = conn.execute("""SELECT e.parameter_id, e.zone_id, e.raw_hmi, e.raw_target FROM workflow_request q
                          JOIN event e ON e.id = q.event_id WHERE q.id = %s""", (request_id,)).fetchone()
    reason = conn.execute("""SELECT body, ocap_section_id FROM workflow_entry WHERE request_id = %s AND kind = 'reason'
                              ORDER BY seq DESC LIMIT 1""", (request_id,)).fetchone()
    zone = _names(request, conn).get(f"{r['parameter_id']}.{r['zone_id']}", {})
    store = request.app.state.ocap_store
    if reason["ocap_section_id"] is not None:
        sections = list(store.sections(conn, [reason["ocap_section_id"]]).values())
    else:
        sections = store.search(conn, _query(zone, r, [reason["body"]]), limit=ai_questions.MAX_SECTIONS,
                                meaning=_meaning([reason["body"]]))
    ai, call_id = ai_questions.ask(request.app.state.settings.ai, conn, request_id, ai_calls.alarm_text(zone, r), reason["body"],
                                   sections, now)
    rows = [(en, fil, "ai", call_id) for en, fil in ai] or [(q, None, "fixed", None) for q in questions(conn)]
    for i, (q, fil, by, cid) in enumerate(rows, start=1):
        conn.execute("""INSERT INTO workflow_question (request_id, ordinal, question, question_fil, asked_by, ai_call_id, at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""", (request_id, i, q, fil, by, cid, now))
    return [q for q, _, _, _ in rows]


def _offer(request: Request, conn, request_id, now) -> str:
    """After the reason and the answers: up to three OCAP sections to choose from (OCP-01), found by the event's zone
    and direction and by what was written; or, with none, straight on to a Manager's guidance."""
    r = conn.execute("""SELECT e.parameter_id, e.zone_id, e.raw_hmi, e.raw_target FROM workflow_request q
                          JOIN event e ON e.id = q.event_id WHERE q.id = %s""", (request_id,)).fetchone()
    zone = _names(request, conn).get(f"{r['parameter_id']}.{r['zone_id']}", {})
    picked = conn.execute("""SELECT e.ocap_section_id FROM workflow_entry e JOIN ocap_section s ON s.id = e.ocap_section_id
                               JOIN ocap_version_status st ON st.version_id = s.version_id AND st.status = 'active'
                              WHERE e.request_id = %s AND e.kind = 'reason'""", (request_id,)).fetchone()
    if picked is not None:  # the reason came from an OCAP row: that row, and no search (ADR-0039)
        conn.execute("""INSERT INTO ocap_recommendation (request_id, rank, section_id, score, method, query, at)
                        VALUES (%s, 1, %s, 1, 'reason', 'The reason picked', %s)""", (request_id, picked["ocap_section_id"], now))
        return "waiting_ocap"
    written = [e["body"] for e in conn.execute("""SELECT body FROM workflow_entry WHERE request_id = %s
                                                     AND kind IN ('reason', 'answer') ORDER BY seq""", (request_id,))]
    query = _query(zone, r, written)
    hits = request.app.state.ocap_store.search(conn, query, limit=3, meaning=_meaning(written))
    for rank, h in enumerate(hits, start=1):
        conn.execute("""INSERT INTO ocap_recommendation (request_id, rank, section_id, score, method, query, at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""", (request_id, rank, h["sectionId"], h["score"], h["method"], query, now))
    return "waiting_ocap" if hits else "waiting_guidance"


def _move(conn, request_id, status: str, now) -> None:
    closed = None if status in workflow_mod.OPEN else now
    conn.execute("UPDATE workflow_request SET status = %s, closed_at = %s, updated_at = %s WHERE id = %s",
                 (status, closed, now, request_id))


def _now(conn):
    return conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]


@router.post("/workflow/requests/{request_id}/reason", dependencies=[OPERATOR_ONLY],
             summary="The operator's reason, typed or picked from the OCAP rows offered (WF-01, ADR-0039)")
def give_reason(request_id: UUID, body: ReasonIn, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "reason", True, now)
    by = request.state.principal.username
    if body.section_id is None:
        _add(conn, request_id, "reason", by, _text(body, "reason"), now)
    else:
        e = conn.execute("""SELECT e.parameter_id, e.raw_hmi, e.raw_target FROM workflow_request r JOIN event e ON e.id = r.event_id
                             WHERE r.id = %s""", (request_id,)).fetchone()
        offered = {c["sectionId"]: c for c in OcapStore.choices(conn, e["parameter_id"], direction_of(e["raw_hmi"], e["raw_target"]))}
        choice = offered.get(str(body.section_id))
        if choice is None:
            raise Problem(422, "not-offered", "That reason isn't offered", "Pick one of the reasons shown, or type your own",
                          errors=[{"field": "sectionId", "message": "Not one of the reasons offered"}])
        note = body.note.strip()
        _add(conn, request_id, "reason", by, choice["label"] + (f"\n{note}" if note else ""), now, section=body.section_id)
    _move(conn, request_id, "waiting_answers" if _ask(request, conn, request_id, now) else _offer(request, conn, request_id, now), now)
    conn.commit()
    return _one(conn, request_id, _names(request, conn))


@router.post("/workflow/requests/{request_id}/answers", dependencies=[OPERATOR_ONLY],
             summary="Answers to the follow-up questions in effect, in their order (WF-02)")
def give_answers(request_id: UUID, body: AnswersIn, request: Request, conn=Depends(connect)) -> dict:
    now = _now(conn)
    _locked(conn, request_id, "answers", True, now)
    # The questions this request asked; one from before ADR-0041 asks the fixed ones in effect
    asked = [q["question"] for q in _asked(conn, [request_id]).get(request_id, []) if q["ordinal"] > 0] or questions(conn)
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
    if body.attachment is not None:
        refuse_uploads(conn)  # protected degraded mode (RES-02): the guidance's text still goes through without a file
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
