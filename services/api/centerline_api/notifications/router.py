"""The Notifications log (ADR-0023): every message, how it was routed, and each delivery with its attempts.

Managers and Administrators read it. Only Administrators send a TEST message (NOT-07) and
re-drive a delivery that failed for good, saying why (NOT-05); both are audited. A TEST goes
to one recipient the Administrator names, outside the routing, so it can try an address
before the routing uses it.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from centerline_common import connections, isotime, messages
from centerline_common import routing as routing_mod
from centerline_common.db import uuid7
from centerline_common.outbox import add_delivery, event_of
from fastapi import APIRouter, Depends, Query, Request
from psycopg.types.json import Jsonb
from pydantic import Field

from ..auth.deps import ADMIN_ONLY, PRIVILEGED
from ..config import audit
from ..config.audit import iso
from ..config.models import _Camel
from ..config.versioning import reason_errors
from ..database import connect
from ..problems import Problem

router = APIRouter(prefix="/api/v1", tags=["notifications"])

WAITING = ("PENDING", "ATTEMPTING", "RETRYING")
STATES = {  # what the page's filter means
    "waiting": "EXISTS (SELECT 1 FROM notification_delivery d WHERE d.notification_id = n.id "
               "AND d.status IN ('PENDING', 'ATTEMPTING', 'RETRYING'))",
    "failed": "EXISTS (SELECT 1 FROM notification_delivery d WHERE d.notification_id = n.id AND d.status = 'PERMANENT_FAILURE')",
    "unrouted": "r.outcome IN ('unrouted', 'expired')",
    "test": "n.kind = 'test'",
}
TYPE_LABEL = {**routing_mod.TYPES, "test": "TEST message"}


class TestIn(_Camel):
    channel: Literal["teams", "email"]
    target: str = Field(min_length=1, max_length=200)
    note: str = Field("", max_length=300)


class RedriveIn(_Camel):
    reason: str = ""


def _delivery(d: dict, attempts: list[dict] | None = None, content: bool = False) -> dict:
    out = {"id": str(d["id"]), "channel": d["channel"], "target": d["target"], "rule": d["rule"], "status": d["status"],
           "attempts": d["attempt_count"], "createdAt": iso(d["created_at"]), "nextAttemptAt": iso(d["next_attempt_at"]),
           "finishedAt": iso(d["finished_at"]), "lastError": d["last_error"],
           "redriveOf": str(d["redrive_of"]) if d["redrive_of"] else None, "redrivenBy": d["redriven_by"],
           "redriveReason": d["redrive_reason"]}
    if content:
        out |= {"messageId": d["message_id"], "dedupKey": d["dedup_key"], "content": d["content"],
                "attemptLog": [{"attempt": a["attempt"], "startedAt": iso(a["started_at"]), "endedAt": iso(a["ended_at"]),
                                "outcome": a["outcome"], "response": a["response"]} for a in attempts or []]}
    return out


def _summary(n: dict, deliveries: list[dict]) -> dict:
    type_ = n["type"] or routing_mod.type_of(n["kind"], n["payload"])
    # as sent, when it was; otherwise as it would read
    subject = deliveries[0]["content"]["subject"] if deliveries else messages.render(n, type_)["subject"]
    return {"id": str(n["id"]), "createdAt": iso(n["created_at"]), "kind": n["kind"], "type": type_,
            "typeLabel": TYPE_LABEL.get(type_, type_), "subject": subject,
            "eventId": str(n["event_id"]) if n["event_id"] else None,
            "outcome": n["outcome"] or "pending", "routingVersion": n["routing_version"],
            "deliveries": [_delivery(d) for d in deliveries]}


COLUMNS = """n.id, n.dedup_key, n.kind, n.event_id, n.created_at, n.payload, r.type, r.outcome, r.routing_version,
             r.routed_at, r.matched"""
DELIVERY_COLUMNS = """id, notification_id, channel, target, rule, dedup_key, message_id, content, status, attempt_count,
                      created_at, next_attempt_at, finished_at, last_error, redrive_of, redriven_by, redrive_reason"""


@router.get("/notifications", dependencies=[PRIVILEGED], summary="Messages, newest first, with their deliveries; `next` pages back")
def list_notifications(state: Literal["all", "waiting", "failed", "unrouted", "test"] = "all",
                       before: str | None = Query(None, description="The `next` of the previous page"),
                       limit: int = Query(50, ge=1, le=200), conn=Depends(connect)) -> dict:
    clauses, args = ([STATES[state]] if state in STATES else []), []
    if before:
        try:
            at, nid = before.split("|", 1)
            clauses.append("(n.created_at, n.id) < (%s, %s)")
            args += [isotime.parse(at), UUID(nid)]
        except ValueError:
            raise Problem(422, "invalid-cursor", "Invalid page cursor", "Use the `next` value of the previous page") from None
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"""SELECT {COLUMNS} FROM notification n LEFT JOIN notification_route r ON r.notification_id = n.id
                            {where} ORDER BY n.created_at DESC, n.id DESC LIMIT %s""", (*args, limit)).fetchall()
    by_n: dict = {}
    if rows:
        for d in conn.execute(f"SELECT {DELIVERY_COLUMNS} FROM notification_delivery WHERE notification_id = ANY(%s) "
                              "ORDER BY created_at, id", ([r["id"] for r in rows],)):
            by_n.setdefault(d["notification_id"], []).append(d)
    c = conn.execute("""SELECT count(*) FILTER (WHERE status IN ('PENDING', 'ATTEMPTING', 'RETRYING')) AS waiting,
                               count(*) FILTER (WHERE status = 'PERMANENT_FAILURE') AS failed FROM notification_delivery""").fetchone()
    last = rows[-1] if len(rows) == limit else None
    return {"notifications": [_summary(r, by_n.get(r["id"], [])) for r in rows],
            "next": f"{isotime.iso(last['created_at'])}|{last['id']}" if last else None,
            "counts": {"waiting": c["waiting"], "failed": c["failed"]}}


def _detail(conn, nid) -> dict:
    n = conn.execute(f"""SELECT {COLUMNS} FROM notification n LEFT JOIN notification_route r ON r.notification_id = n.id
                          WHERE n.id = %s""", (nid,)).fetchone()
    if n is None:
        raise Problem(404, "not-found", "No such message", "It may have been on another Centerline")
    deliveries = conn.execute(f"SELECT {DELIVERY_COLUMNS} FROM notification_delivery WHERE notification_id = %s "
                              "ORDER BY created_at, id", (nid,)).fetchall()
    attempts: dict = {}
    if deliveries:
        for a in conn.execute("SELECT * FROM delivery_attempt WHERE delivery_id = ANY(%s) ORDER BY attempt",
                              ([d["id"] for d in deliveries],)):
            attempts.setdefault(a["delivery_id"], []).append(a)
    out = _summary(n, deliveries)
    out["payload"] = n["payload"]
    out["dedupKey"] = n["dedup_key"]
    out["route"] = None if n["outcome"] is None else {"routedAt": iso(n["routed_at"]), "routingVersion": n["routing_version"],
                                                      "matched": n["matched"], "outcome": n["outcome"]}
    out["deliveries"] = [_delivery(d, attempts.get(d["id"]), content=True) for d in deliveries]
    return out


@router.get("/notifications/{notification_id}", dependencies=[PRIVILEGED],
            summary="One message: its payload, how it was routed, and each delivery with what was sent and every attempt")
def get_notification(notification_id: UUID, conn=Depends(connect)) -> dict:
    return _detail(conn, notification_id)


@router.post("/notifications/test", dependencies=[ADMIN_ONLY], status_code=201,
             summary="Send a TEST - NO PRODUCTION EVENT message to one recipient (NOT-07)")
def send_test(body: TestIn, request: Request, conn=Depends(connect)) -> dict:
    target = body.target.strip()
    if body.channel == "email" and not routing_mod.EMAIL.fullmatch(target):
        raise Problem(422, "invalid", "Not an email address", f"{target} isn't an email address",
                      errors=[{"field": "target", "message": f"{target} isn't an email address"}])
    cfg = connections.notifications_config(request.app.state.settings.config_dir)
    now = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
    nid = uuid7()
    n = {"id": nid, "dedup_key": f"test:{nid}", "kind": "test", "event_id": None, "created_at": now,
         "payload": {"test": True, "by": request.state.principal.username, "note": body.note.strip() or None}}
    conn.execute("""INSERT INTO notification (id, dedup_key, kind, event_id, created_at, payload)
                    VALUES (%s, %s, 'test', NULL, %s, %s)""", (nid, n["dedup_key"], now, Jsonb(n["payload"])))
    conn.execute("""INSERT INTO notification_route (notification_id, routed_at, type, routing_version, matched, outcome)
                    VALUES (%s, %s, 'test', NULL, '[]', 'test')""", (nid, now))
    add_delivery(conn, n, "test", body.channel, target, None, now, event=None, line=cfg["line"], app_url=cfg["app_url"])
    audit.record(conn, "notifications.test",
                 f"TEST message to {target} on {routing_mod.CHANNELS[body.channel]}", body.note,
                 {"notification": str(nid), "channel": body.channel, "target": target})
    conn.commit()
    return _detail(conn, nid)


@router.post("/deliveries/{delivery_id}/redrive", dependencies=[ADMIN_ONLY],
             summary="Send a delivery that failed for good again, saying why (NOT-05)")
def redrive(delivery_id: UUID, body: RedriveIn, request: Request, conn=Depends(connect)) -> dict:
    if errors := reason_errors(body.reason):
        raise Problem(422, "invalid", "Say why it's sent again", errors[0]["message"], errors=errors)
    d = conn.execute(f"SELECT {DELIVERY_COLUMNS} FROM notification_delivery WHERE id = %s FOR UPDATE", (delivery_id,)).fetchone()
    if d is None:
        raise Problem(404, "not-found", "No such delivery", "Reload the page")
    if d["status"] != "PERMANENT_FAILURE":
        raise Problem(409, "not-failed", "Only a permanent failure can be re-driven",
                      f"This delivery is {d['status'].replace('_', ' ').lower()}: it isn't finished with, or it already arrived.")
    n = conn.execute("""SELECT n.id, n.dedup_key, n.kind, n.event_id, n.created_at, n.payload, r.type
                          FROM notification n JOIN notification_route r ON r.notification_id = n.id WHERE n.id = %s""",
                     (d["notification_id"],)).fetchone()
    cfg = connections.notifications_config(request.app.state.settings.config_dir)
    now = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
    conn.execute("UPDATE notification_delivery SET status = 'REDRIVEN' WHERE id = %s", (delivery_id,))
    new_id = add_delivery(conn, n, n["type"], d["channel"], d["target"], d["rule"], now, event=event_of(conn, n["event_id"]),
                          line=cfg["line"], app_url=cfg["app_url"],
                          redrive={"of": delivery_id, "by": request.state.principal.username, "reason": body.reason.strip()})
    audit.record(conn, "notifications.redrive",
                 f"Re-drove the {routing_mod.CHANNELS[d['channel']]} delivery to {d['target']}, which failed for good",
                 body.reason, {"notification": str(n["id"]), "delivery": str(delivery_id), "new_delivery": new_id})
    conn.commit()
    return _detail(conn, n["id"])
