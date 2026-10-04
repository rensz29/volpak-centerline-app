"""Monitoring control (ADR-0017): zones switched off (MON-01) and maintenance windows (MNT-01).

- A **Manager** switches monitoring off for a zone, or for all of a parameter's zones, with a
  reason, and on again. monitor-core closes the zone's open event as "Monitoring disabled"
  within 2 s, with no recovery notice; switched on again, the zone is judged on fresh values.
- An **Administrator** opens a maintenance window for the whole line or chosen zones, now or at
  a set time, with a planned end, and extends or ends it. Past its planned end a window stays
  in force, overdue, until it's ended; monitor-core alerts Management once.
- Every role sees what is switched off and every window. Each change is audited.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from centerline_common.db import uuid7
from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator

from ..auth.deps import ADMIN_ONLY, MANAGER_ONLY, SIGNED_IN
from ..config import audit
from ..config.audit import iso
from ..config.models import _Camel, _aware
from ..database import connect
from ..problems import Problem

router = APIRouter(prefix="/api/v1", tags=["monitoring control"], dependencies=[SIGNED_IN])
MANILA_HINT = "e.g. 2026-10-01T06:00:00+08:00"


class SwitchIn(_Camel):
    channels: list[str] = Field(min_length=1, max_length=200, description="Zones, e.g. P02.V3; all of a parameter's for the parameter")
    on: bool
    reason: str = Field("", max_length=500)


class WindowIn(_Camel):
    scope: Literal["line", "zones"]
    channels: list[str] = Field(default_factory=list, max_length=200)
    reason: str = Field(min_length=1, max_length=500)
    start: datetime | None = Field(None, description=f"Empty: now. {MANILA_HINT}")
    end: datetime = Field(description=f"The planned end, {MANILA_HINT}")

    _tz = field_validator("start", "end")(_aware)


class ExtendIn(_Camel):
    end: datetime
    reason: str = Field("", max_length=500)

    _tz = field_validator("end")(_aware)


class EndIn(_Camel):
    reason: str = Field("", max_length=500)


def _zones(request: Request, conn) -> dict[str, dict]:
    """The monitored zones, by channel: only these can be switched or put under maintenance."""
    return {z.channel: {"channel": z.channel, "parameterId": z.parameter_id, "parameterName": z.parameter_name,
                        "zoneName": z.zone_name} for z in request.app.state.register_store.load(conn).zones}


def _now(conn) -> datetime:
    return conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def _status(w: dict, now: datetime) -> str:
    if w["ended_at"] is not None:
        return "cancelled" if w["ended_at"] < w["planned_start"] else "ended"
    if now < w["planned_start"]:
        return "scheduled"
    return "overdue" if now > w["planned_end"] else "active"


def _window(w: dict, zones: dict[str, dict], now: datetime) -> dict:
    return {"id": str(w["id"]), "scope": w["scope"], "status": _status(w, now), "reason": w["reason"],
            "zones": [zones.get(ch, {"channel": ch, "zoneName": ch, "parameterName": "", "parameterId": ""}) for ch in w["channels"]],
            "plannedStart": iso(w["planned_start"]), "plannedEnd": iso(w["planned_end"]),
            "createdAt": iso(w["created_at"]), "createdBy": w["created_by"],
            "endedAt": iso(w["ended_at"]), "endedBy": w["ended_by"]}


def _get(conn, window_id: UUID) -> dict:
    w = conn.execute("SELECT * FROM maintenance_window WHERE id = %s FOR UPDATE", (window_id,)).fetchone()
    if w is None:
        raise Problem(404, "not-found", "No such maintenance window", f"Window {window_id} doesn't exist")
    return w


def control_view(conn, zones: dict[str, dict]) -> dict:
    """What is switched off, and the maintenance windows not ended; the live page shows both."""
    now = _now(conn)
    off = conn.execute("""SELECT * FROM (SELECT DISTINCT ON (channel) channel, enabled, at, by_user, reason
                                           FROM monitoring_switch ORDER BY channel, seq DESC) latest
                           WHERE NOT enabled ORDER BY at""").fetchall()
    windows = conn.execute("SELECT * FROM maintenance_window WHERE ended_at IS NULL ORDER BY planned_start").fetchall()
    return {"serverTime": iso(now),
            "switchedOff": [{**zones.get(r["channel"], {"channel": r["channel"], "zoneName": r["channel"], "parameterName": "",
                                                        "parameterId": ""}),
                             "since": iso(r["at"]), "by": r["by_user"], "reason": r["reason"]} for r in off],
            "maintenance": [_window(w, zones, now) for w in windows]}


def _describe(channels: list[str], zones: dict[str, dict]) -> str:
    return ", ".join(f"{zones[ch]['zoneName']} ({ch})" for ch in channels)


@router.get("/monitoring/control", summary="Zones switched off, and maintenance windows not ended")
def get_control(request: Request, conn=Depends(connect)) -> dict:
    return control_view(conn, _zones(request, conn))


@router.post("/monitoring/switch", dependencies=[MANAGER_ONLY],
             summary="Switch monitoring off for zones, with a reason, or on again (MON-01)")
def switch(body: SwitchIn, request: Request, conn=Depends(connect)) -> dict:
    zones = _zones(request, conn)
    unknown = [ch for ch in body.channels if ch not in zones]
    if unknown:
        raise Problem(422, "unknown-zone", "Not a monitored zone", f"{', '.join(unknown)} isn't a monitored zone of the register",
                      errors=[{"field": "channels", "message": f"Not monitored: {', '.join(unknown)}"}])
    if not body.on and not body.reason.strip():
        raise Problem(422, "reason-needed", "Give a reason", "Switching monitoring off needs a reason, kept in the history",
                      errors=[{"field": "reason", "message": "Why is monitoring switched off?"}])
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('centerline.monitoring_switch'))")
    latest = {r["channel"]: r["enabled"] for r in conn.execute(
        "SELECT DISTINCT ON (channel) channel, enabled FROM monitoring_switch ORDER BY channel, seq DESC").fetchall()}
    # Only zones that change: switching off a zone that is off already adds nothing
    changing = [ch for ch in dict.fromkeys(body.channels) if latest.get(ch, True) != body.on]
    user = request.state.principal.username
    for ch in changing:
        conn.execute("INSERT INTO monitoring_switch (id, channel, enabled, by_user, reason) VALUES (%s, %s, %s, %s, %s)",
                     (uuid7(), ch, body.on, user, body.reason.strip() or None))
    if changing:
        audit.record(conn, "monitoring.switch", f"Monitoring switched {'on' if body.on else 'off'}: {_describe(changing, zones)}",
                     body.reason, details={"channels": changing, "on": body.on})
    conn.commit()
    return {**control_view(conn, zones), "changed": changing}


@router.get("/maintenance", summary="Maintenance windows, newest first, ended ones included")
def list_windows(request: Request, limit: int = Query(50, ge=1, le=500), conn=Depends(connect)) -> dict:
    zones, now = _zones(request, conn), _now(conn)
    rows = conn.execute("SELECT * FROM maintenance_window ORDER BY planned_start DESC LIMIT %s", (limit,)).fetchall()
    return {"serverTime": iso(now), "windows": [_window(w, zones, now) for w in rows]}


@router.post("/maintenance", dependencies=[ADMIN_ONLY], status_code=201,
             summary="Open a maintenance window, now or at a set time, for the line or chosen zones (MNT-01)")
def create_window(body: WindowIn, request: Request, conn=Depends(connect)) -> dict:
    zones, now = _zones(request, conn), _now(conn)
    channels = list(dict.fromkeys(body.channels)) if body.scope == "zones" else []
    errors = []
    if body.scope == "zones" and not channels:
        errors.append({"field": "channels", "message": "Choose the zones the work is on"})
    if unknown := [ch for ch in channels if ch not in zones]:
        errors.append({"field": "channels", "message": f"Not monitored: {', '.join(unknown)}"})
    start = body.start or now
    if (now - start).total_seconds() > 60:
        errors.append({"field": "start", "message": "The start can't be in the past; leave it empty for now"})
    if body.end <= max(start, now):
        errors.append({"field": "end", "message": "The planned end must be after the start and in the future"})
    if errors:
        raise Problem(422, "invalid-window", "Check the maintenance window", "; ".join(e["message"] for e in errors), errors=errors)
    wid = uuid7()
    w = conn.execute("""INSERT INTO maintenance_window (id, scope, channels, reason, planned_start, planned_end, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                     (wid, body.scope, channels, body.reason.strip(), start, body.end,
                      request.state.principal.username)).fetchone()
    what = "the whole line" if body.scope == "line" else _describe(channels, zones)
    audit.record(conn, "maintenance.open",
                 f"Maintenance {'started' if start <= now else 'scheduled'} on {what}, planned {iso(start)} to {iso(body.end)}",
                 body.reason, details={"window": str(wid), "scope": body.scope, "channels": channels})
    conn.commit()
    return _window(w, zones, _now(conn))


@router.post("/maintenance/{window_id}/extend", dependencies=[ADMIN_ONLY], summary="Move a window's planned end")
def extend_window(window_id: UUID, body: ExtendIn, request: Request, conn=Depends(connect)) -> dict:
    zones, now = _zones(request, conn), _now(conn)
    w = _get(conn, window_id)
    if w["ended_at"] is not None:
        raise Problem(409, "window-ended", "This window has ended", "Open a new one instead.")
    if body.end <= max(w["planned_start"], now):
        raise Problem(422, "invalid-window", "Check the planned end", "The planned end must be after the start and in the future",
                      errors=[{"field": "end", "message": "Must be after the start and in the future"}])
    w = conn.execute("UPDATE maintenance_window SET planned_end = %s WHERE id = %s RETURNING *", (body.end, window_id)).fetchone()
    audit.record(conn, "maintenance.extend", f"Maintenance \"{w['reason']}\" now planned to end {iso(body.end)}", body.reason,
                 details={"window": str(window_id)})
    conn.commit()
    return _window(w, zones, _now(conn))


@router.post("/maintenance/{window_id}/end", dependencies=[ADMIN_ONLY],
             summary="End a window now; one that hasn't started is cancelled")
def end_window(window_id: UUID, body: EndIn, request: Request, conn=Depends(connect)) -> dict:
    zones, now = _zones(request, conn), _now(conn)
    w = _get(conn, window_id)
    if w["ended_at"] is not None:
        raise Problem(409, "window-ended", "This window has ended already", "Nothing to do.")
    w = conn.execute("UPDATE maintenance_window SET ended_at = %s, ended_by = %s WHERE id = %s RETURNING *",
                     (now, request.state.principal.username, window_id)).fetchone()
    cancelled = now < w["planned_start"]
    audit.record(conn, "maintenance.cancel" if cancelled else "maintenance.end",
                 f"Maintenance \"{w['reason']}\" {'cancelled before it started' if cancelled else 'ended'}", body.reason,
                 details={"window": str(window_id)})
    conn.commit()
    return _window(w, zones, _now(conn))
