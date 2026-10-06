"""The Digital Centerline page's data (ADR-0015): monitor-core's live state, its events, and acknowledgments.

monitor-core writes its heartbeat, with every zone's values and states, every 2 s; the api
reads it and the events from PostgreSQL (invariant 3: services talk through the database).
States come from monitor-core only; nothing here judges. Every role may read (ADR-0016); a
Manager acknowledges a Critical, and monitor-core applies it within 2 s (ACT-04).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from centerline_common.db import uuid7
from centerline_common import isotime
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field

from ..auth.deps import MANAGER_ONLY, PRIVILEGED, SIGNED_IN
from ..config import audit
from ..config.audit import iso
from ..config.models import _Camel
from ..database import connect
from ..problems import Problem
from ..workflow.router import requests_of_event
from .control import control_view

router = APIRouter(prefix="/api/v1", tags=["monitoring"], dependencies=[SIGNED_IN])
STALE_S = 60  # a heartbeat older than this means monitor-core isn't running (guide §6.7)


def _num(v) -> str | None:
    return None if v is None else format(Decimal(v).normalize(), "f")


def _zone_names(register) -> dict[str, dict]:
    return {z.channel: {"parameterName": z.parameter_name, "zoneName": z.zone_name, "unit": z.unit} for z in register.zones}


EVENT_COLUMNS = """e.id, e.kind, e.parameter_id, e.zone_id, e.opened_at, e.raw_target, e.raw_hmi, e.raw_actual,
                   e.supersedes_event_id, e.rule, s.state, s.severity, s.open, s.closed_at, s.acknowledged_at"""


def _event(r: dict, names: dict[str, dict]) -> dict:
    ch = f"{r['parameter_id']}.{r['zone_id']}"
    return {"id": str(r["id"]), "kind": r["kind"], "parameterId": r["parameter_id"], "zoneId": r["zone_id"], "channel": ch,
            **names.get(ch, {"parameterName": r["parameter_id"], "zoneName": r["zone_id"], "unit": None}),
            "openedAt": iso(r["opened_at"]), "state": r["state"], "severity": r["severity"],
            "open": r["open"], "closedAt": iso(r["closed_at"]), "acknowledgedAt": iso(r["acknowledged_at"]),
            "target": _num(r["raw_target"]), "hmi": _num(r["raw_hmi"]), "actual": _num(r["raw_actual"]),
            "supersedes": str(r["supersedes_event_id"]) if r["supersedes_event_id"] else None,
            "rulesVersion": (r["rule"] or {}).get("rules_version")}


@router.get("/monitoring/live", summary="Every monitored zone's values and states, and the open events")
def live(request: Request, conn=Depends(connect)) -> dict:
    register = request.app.state.register_store.load(conn)
    names = _zone_names(register)
    beat = conn.execute("""SELECT instance, started_at, beat_at, status, extract(epoch FROM clock_timestamp() - beat_at) AS age,
                                  clock_timestamp() AS now
                             FROM monitor_heartbeat ORDER BY beat_at DESC LIMIT 1""").fetchone()
    alive = beat is not None and float(beat["age"]) < STALE_S
    status = beat["status"] if alive else {}
    events = [_event(r, names) for r in conn.execute(
        f"SELECT {EVENT_COLUMNS} FROM event e JOIN event_state s ON s.event_id = e.id WHERE s.open ORDER BY e.opened_at DESC")]
    by_zone: dict[str, list[str]] = {}
    for e in events:
        by_zone.setdefault(e["channel"], []).append(e["id"])

    parameters: list[dict] = []
    for z in register.zones:
        if not parameters or parameters[-1]["id"] != z.parameter_id:
            parameters.append({"id": z.parameter_id, "name": z.parameter_name, "unit": z.unit, "zones": []})
        zs = (status.get("zones") or {}).get(z.channel)
        parameters[-1]["zones"].append({"id": z.zone_id, "name": z.zone_name, "channel": z.channel, "known": zs is not None,
                                        **(zs or {}), "events": by_zone.get(z.channel, [])})
    now = beat["now"] if beat else conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    return {
        "serverTime": iso(now),
        "monitor": None if beat is None else {
            "instance": beat["instance"], "startedAt": iso(beat["started_at"]), "beatAt": iso(beat["beat_at"]),
            "ageS": round(float(beat["age"]), 1), "alive": alive,
            **{k: beat["status"].get(k) for k in ("judging", "reasons", "connected", "actualPaused", "stop",
                                                   "warmupUntil", "rulesVersion", "mappingVersion", "registerVersion", "lastLive")}},
        "parameters": parameters,
        "events": events,
        # Zones switched off and maintenance windows, from the database: shown even while monitor-core is down
        "control": control_view(conn, {z.channel: {"channel": z.channel, "parameterId": z.parameter_id,
                                                   "parameterName": z.parameter_name, "zoneName": z.zone_name}
                                       for z in register.zones}),
        "counts": {"zones": len(register.zones),
                   "hmiOpen": sum(1 for e in events if e["kind"] == "HMI_MISMATCH"),
                   "warning": sum(1 for e in events if e["kind"] == "ACTUAL" and e["severity"] == "WARNING"),
                   "critical": sum(1 for e in events if e["kind"] == "ACTUAL" and e["severity"] == "CRITICAL")},
    }


Kind = Literal["HMI_MISMATCH", "ACTUAL"]
Sev = Literal["WARNING", "CRITICAL"]
CHANNEL = r"^[A-Z0-9]+\.[A-Za-z0-9_-]+$"
EXPORT_MAX = 10_000
MANILA = timezone(timedelta(hours=8))


def _filters(open_: bool | None, kind: str | None, severity: str | None, channel: str | None,
             since: datetime | None, until: datetime | None, reached: str | None = None) -> tuple[list[str], list]:
    """`severity` is the event's latest; `reached` asks whether it ever was, e.g. a Critical that went back to Warning."""
    clauses, args = [], []
    if reached:
        clauses.append("EXISTS (SELECT 1 FROM event_transition t WHERE t.event_id = e.id AND t.state = %s)")
        args.append(reached)
    if open_ is not None:
        clauses.append("s.open" if open_ else "NOT s.open")
    if kind:
        clauses.append("e.kind = %s")
        args.append(kind)
    if severity:
        clauses.append("s.severity = %s")
        args.append(severity)
    if channel:
        pid, zid = channel.split(".", 1)
        clauses.append("e.parameter_id = %s AND e.zone_id = %s")
        args += [pid, zid]
    if since:
        clauses.append("e.opened_at >= %s")
        args.append(since)
    if until:
        clauses.append("e.opened_at < %s")
        args.append(until)
    return clauses, args


def _where(clauses: list[str]) -> str:
    return f"WHERE {' AND '.join(clauses)}" if clauses else ""


@router.get("/events", summary="Events, newest first, with filters; `next` pages further back")
def list_events(request: Request, open: bool | None = None, kind: Kind | None = None, severity: Sev | None = None,
                reached: Sev | None = None, channel: str | None = Query(None, pattern=CHANNEL), since: datetime | None = None,
                until: datetime | None = None, before: str | None = Query(None, description="The `next` of the previous page"),
                limit: int = Query(50, ge=1, le=200), conn=Depends(connect)) -> dict:
    names = _zone_names(request.app.state.register_store.load(conn))
    clauses, args = _filters(open, kind, severity, channel, since, until, reached)
    if before:
        try:
            at, eid = before.split("|", 1)
            clauses.append("(e.opened_at, e.id) < (%s, %s)")
            args += [isotime.parse(at), UUID(eid)]
        except ValueError:
            raise Problem(422, "invalid-cursor", "Invalid page cursor", "Use the `next` value of the previous page") from None
    rows = conn.execute(f"SELECT {EVENT_COLUMNS} FROM event e JOIN event_state s ON s.event_id = e.id {_where(clauses)} "
                        "ORDER BY e.opened_at DESC, e.id DESC LIMIT %s", (*args, limit)).fetchall()
    last = rows[-1] if len(rows) == limit else None
    return {"events": [_event(r, names) for r in rows],
            "next": f"{isotime.iso(last['opened_at'])}|{last['id']}" if last else None}


@router.get("/events/counts", summary="Open events by kind and severity, for the sidebar and the bell")
def event_counts(conn=Depends(connect)) -> dict:
    r = conn.execute("""SELECT count(*) FILTER (WHERE e.kind = 'HMI_MISMATCH') AS hmi,
                               count(*) FILTER (WHERE e.kind = 'ACTUAL' AND s.severity = 'WARNING') AS warning,
                               count(*) FILTER (WHERE e.kind = 'ACTUAL' AND s.severity = 'CRITICAL') AS critical,
                               count(*) FILTER (WHERE e.kind = 'ACTUAL' AND s.severity = 'CRITICAL'
                                                  AND s.acknowledged_at IS NULL) AS unacknowledged
                          FROM event e JOIN event_state s ON s.event_id = e.id WHERE s.open""").fetchone()
    return {"open": r["hmi"] + r["warning"] + r["critical"], "hmi": r["hmi"], "warning": r["warning"],
            "critical": r["critical"], "unacknowledgedCritical": r["unacknowledged"]}


def _manila(t: datetime | None) -> str:
    return "" if t is None else t.astimezone(MANILA).isoformat(timespec="seconds")


@router.get("/events/export.csv", dependencies=[PRIVILEGED],
            summary=f"The events matching the filters as UTF-8 CSV, newest first, up to {EXPORT_MAX:,} (EXP-01)")
def export_events(request: Request, open: bool | None = None, kind: Kind | None = None, severity: Sev | None = None,
                  reached: Sev | None = None, channel: str | None = Query(None, pattern=CHANNEL), since: datetime | None = None,
                  until: datetime | None = None, conn=Depends(connect)) -> Response:
    names = _zone_names(request.app.state.register_store.load(conn))
    clauses, args = _filters(open, kind, severity, channel, since, until, reached)
    rows = conn.execute(f"""SELECT {EVENT_COLUMNS},
                                   (SELECT a.by_user FROM event_acknowledgment a WHERE a.event_id = e.id ORDER BY a.seq DESC LIMIT 1) AS ack_by
                              FROM event e JOIN event_state s ON s.event_id = e.id {_where(clauses)}
                             ORDER BY e.opened_at DESC, e.id DESC LIMIT %s""", (*args, EXPORT_MAX)).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Opened (Manila)", "Closed (Manila)", "Kind", "Severity", "State", "Parameter", "Zone", "Channel",
                "Target at opening", "HMI at opening", "Actual at opening", "Unit", "Rules version", "Acknowledged (Manila)",
                "Acknowledged by", "Event ID"])
    for r in rows:
        e = _event(r, names)
        w.writerow([_manila(r["opened_at"]), _manila(r["closed_at"]), "HMI mismatch" if e["kind"] == "HMI_MISMATCH" else "Actual",
                    (e["severity"] or "").title(), e["state"], e["parameterName"], e["zoneName"], e["channel"],
                    e["target"] or "", e["hmi"] or "", e["actual"] or "", e["unit"] or "", e["rulesVersion"] or "",
                    _manila(r["acknowledged_at"]), r["ack_by"] or "", e["id"]])
    filters = {k: (isotime.iso(v) if isinstance(v, datetime) else v) for k, v in
               (("open", open), ("kind", kind), ("severity", severity), ("reached", reached), ("channel", channel),
                ("since", since), ("until", until))
               if v is not None}
    audit.record(conn, "events.export", f"Events exported as CSV: {len(rows)} event(s)", details={"filters": filters, "rows": len(rows)})
    conn.commit()
    stamp = datetime.now(MANILA).strftime("%Y%m%d-%H%M")
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",  # the BOM tells Excel it's UTF-8
                    headers={"Content-Disposition": f'attachment; filename="centerline-events-{stamp}.csv"'})


def _delivery_state(n: dict) -> str:
    """One message's state for the event's evidence (ADR-0023): routed or not, and how its deliveries went."""
    if n["outcome"] is None:
        return "pending"
    if n["outcome"] != "routed":
        return n["outcome"]  # unrouted, expired
    statuses = {d["status"] for d in n["deliveries"]}
    if "PERMANENT_FAILURE" in statuses:
        return "failed"
    return "waiting" if statuses & {"PENDING", "ATTEMPTING", "RETRYING"} else "sent"


@router.get("/events/{event_id}", summary="One event: its transitions, notifications and the rule it was judged by")
def get_event(event_id: UUID, request: Request, conn=Depends(connect)) -> dict:
    names = _zone_names(request.app.state.register_store.load(conn))
    row = conn.execute(f"""SELECT {EVENT_COLUMNS}, c.number AS rules_number, m.number AS mapping_number, r.number AS register_number
                             FROM event e JOIN event_state s ON s.event_id = e.id
                             JOIN config_version c ON c.id = e.config_version_id
                             JOIN mapping_version m ON m.id = e.mapping_version_id
                             JOIN register_version r ON r.id = e.register_version_id
                            WHERE e.id = %s""", (event_id,)).fetchone()
    if row is None:
        raise Problem(404, "not-found", "No such event", f"Event {event_id} doesn't exist")
    transitions = conn.execute("SELECT seq, at, state, inputs FROM event_transition WHERE event_id = %s ORDER BY seq",
                               (event_id,)).fetchall()
    notes = conn.execute("""SELECT n.id, n.kind, n.created_at, r.outcome,
                                   coalesce(jsonb_agg(jsonb_build_object('channel', d.channel, 'target', d.target, 'status', d.status)
                                                      ORDER BY d.created_at) FILTER (WHERE d.id IS NOT NULL), '[]') AS deliveries
                              FROM notification n LEFT JOIN notification_route r ON r.notification_id = n.id
                              LEFT JOIN notification_delivery d ON d.notification_id = n.id AND d.status <> 'REDRIVEN'
                             WHERE n.event_id = %s GROUP BY n.id, r.outcome ORDER BY n.created_at""", (event_id,)).fetchall()
    acks = conn.execute("""SELECT at, by_user, note, critical_period FROM event_acknowledgment WHERE event_id = %s
                            ORDER BY seq""", (event_id,)).fetchall()
    return {**_event(row, names), "rule": row["rule"],
            "versions": {"rules": row["rules_number"], "mapping": row["mapping_number"], "register": row["register_number"]},
            "transitions": [{"seq": t["seq"], "at": iso(t["at"]), "state": t["state"], "inputs": t["inputs"]} for t in transitions],
            "notifications": [{"id": str(n["id"]), "kind": n["kind"], "at": iso(n["created_at"]), "status": _delivery_state(n),
                               "deliveries": n["deliveries"]} for n in notes],
            "acknowledgments": [{"at": iso(a["at"]), "by": a["by_user"], "note": a["note"], "criticalPeriod": a["critical_period"]}
                                for a in acks],
            "acknowledgeable": _acknowledgeable(conn, event_id)[0],
            "requests": requests_of_event(conn, event_id, names)}  # the reason workflow, one per shift (ADR-0025)


class AcknowledgeIn(_Camel):
    note: str = Field("", max_length=500)


def _acknowledgeable(conn, event_id) -> tuple[bool, str, int]:
    """Whether a Manager can acknowledge the event now, why not, and its current Critical period (ACT-04)."""
    r = conn.execute("""SELECT e.kind, s.open, s.severity, s.acknowledged_at,
                               (SELECT count(*) FROM event_transition t WHERE t.event_id = e.id AND t.state = 'CRITICAL') AS period
                          FROM event e JOIN event_state s ON s.event_id = e.id WHERE e.id = %s""", (event_id,)).fetchone()
    if r is None:
        raise Problem(404, "not-found", "No such event", f"Event {event_id} doesn't exist")
    if not r["open"]:
        return False, "The event has closed", r["period"]
    if r["kind"] != "ACTUAL" or r["severity"] != "CRITICAL":
        return False, "Only an open Critical can be acknowledged (ACT-04)", r["period"]
    given = conn.execute("SELECT 1 FROM event_acknowledgment WHERE event_id = %s AND critical_period = %s",
                         (event_id, r["period"])).fetchone()
    if r["acknowledged_at"] is not None or given is not None:
        return False, "This Critical is already acknowledged", r["period"]
    return True, "", r["period"]


@router.post("/events/{event_id}/acknowledge", dependencies=[MANAGER_ONLY], status_code=202,
             summary="A Manager acknowledges a Critical: its repeats stop once monitor-core applies it (ACT-04)")
def acknowledge(event_id: UUID, body: AcknowledgeIn, request: Request, conn=Depends(connect)) -> dict:
    principal = request.state.principal
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"centerline.ack.{event_id}",))
    ok, why, period = _acknowledgeable(conn, event_id)
    if not ok:
        raise Problem(409, "not-acknowledgeable", "Can't acknowledge this event", why)
    ack_id = uuid7()
    row = conn.execute("""INSERT INTO event_acknowledgment (id, event_id, by_user, note, critical_period)
                          VALUES (%s, %s, %s, %s, %s) RETURNING at""",
                       (ack_id, event_id, principal.username, body.note.strip() or None, period)).fetchone()
    names = _zone_names(request.app.state.register_store.load(conn))
    ev = conn.execute("SELECT parameter_id, zone_id FROM event WHERE id = %s", (event_id,)).fetchone()
    zone = names.get(f"{ev['parameter_id']}.{ev['zone_id']}", {}).get("zoneName", f"{ev['parameter_id']}.{ev['zone_id']}")
    audit.record(conn, "event.acknowledge", f"Critical on {zone} acknowledged", body.note.strip() or None,
                 details={"event": str(event_id), "acknowledgment": str(ack_id), "critical_period": period})
    conn.commit()
    return {"acknowledgedBy": principal.username, "at": iso(row["at"]), "criticalPeriod": period,
            "note": body.note.strip() or None}


@router.get("/monitoring/brief-changes", summary="Setpoints back on target before the delay ended (HMI-05), newest first")
def brief_changes(request: Request, limit: int = Query(20, ge=1, le=200), conn=Depends(connect)) -> dict:
    names = _zone_names(request.app.state.register_store.load(conn))
    rows = conn.execute("""SELECT id, parameter_id, zone_id, mode, started_at, ended_at, raw_target, raw_hmi
                             FROM lightweight_change ORDER BY ended_at DESC LIMIT %s""", (limit,)).fetchall()
    out = []
    for r in rows:
        ch = f"{r['parameter_id']}.{r['zone_id']}"
        out.append({"id": str(r["id"]), "channel": ch, **names.get(ch, {"parameterName": r["parameter_id"], "zoneName": r["zone_id"],
                                                                         "unit": None}),
                    "mode": r["mode"], "startedAt": iso(r["started_at"]), "endedAt": iso(r["ended_at"]),
                    "seconds": round((r["ended_at"] - r["started_at"]).total_seconds(), 1),
                    "target": _num(r["raw_target"]), "hmi": _num(r["raw_hmi"])})
    return {"briefChanges": out}
