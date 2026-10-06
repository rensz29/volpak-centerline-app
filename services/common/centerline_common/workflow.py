"""The reason workflow's requests (WF-01…03, ADR-0025), shared by monitor-core and the api.

One request per HMI mismatch per shift (`UNIQUE (event_id, shift_instance_id)`):
- monitor-core opens it with the event, in the same transaction (HMI-02, NOT-03);
- an operator signing in to a new shift gets one for each mismatch still open;
- it closes with its event (resolved, superseded, or cancelled by a changeover or a switch-off);
- at the end of its shift an unfinished one closes as not answered (O-11, owner 2026-10-01);
- one still open 15 min after it was made alerts Management, once (WF-03, A-05).

Every write is safe to repeat, so monitor-core's disk journal can replay it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import shifts
from .db import uuid7

OPEN = ["waiting_reason", "waiting_answers", "waiting_ocap", "waiting_guidance", "waiting_acknowledgment"]
CLOSED_BY = {"RESOLVED": "resolved", "SUPERSEDED": "superseded"}  # any other closing state cancels it
ESCALATE_AFTER = timedelta(minutes=15)  # WF-03


def open_request(conn, event_id, at: datetime) -> bool:
    """The request for an HMI mismatch in the shift at `at`; True if it's new."""
    sid = shifts.shift_id(conn, at)
    return conn.execute("""INSERT INTO workflow_request (id, event_id, shift_instance_id, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (event_id, shift_instance_id) DO NOTHING
                           RETURNING id""", (uuid7(), event_id, sid, at, at)).fetchone() is not None


def close_requests(conn, event_id, state: str, at: datetime) -> None:
    """The event closed: so does its open request, whatever it had reached."""
    conn.execute("""UPDATE workflow_request SET status = %s, closed_at = %s, updated_at = %s
                     WHERE event_id = %s AND status = ANY(%s)""", (CLOSED_BY.get(state, "cancelled"), at, at, event_id, OPEN))


def activate_shift(conn, now: datetime) -> int:
    """An operator signed in: a request in this shift for every HMI mismatch still open. Returns how many were new."""
    events = conn.execute("""SELECT e.id FROM event e JOIN event_state s ON s.event_id = e.id
                              WHERE s.open AND e.kind = 'HMI_MISMATCH' ORDER BY e.opened_at""").fetchall()
    return sum(open_request(conn, e["id"], now) for e in events)


def close_ended_shifts(conn, now: datetime) -> int:
    """Requests whose shift is over and still unfinished close as not answered, at the shift's end."""
    rows = conn.execute("""UPDATE workflow_request r SET status = 'not_answered', closed_at = s.ends_at, updated_at = %s
                             FROM shift_instance s
                            WHERE s.id = r.shift_instance_id AND s.ends_at <= %s AND r.status = ANY(%s)
                           RETURNING r.id""", (now, now, OPEN)).fetchall()
    return len(rows)


def overdue(conn, now: datetime) -> list[dict]:
    """Requests open for 15 min that haven't alerted Management yet, with what the message needs."""
    return conn.execute("""SELECT r.id, r.event_id, r.created_at, r.status, e.parameter_id, e.zone_id, e.raw_hmi,
                                  e.raw_target, e.opened_at, s.code AS shift, s.starts_at, s.ends_at, s.production_date
                             FROM workflow_request r JOIN event e ON e.id = r.event_id
                             JOIN shift_instance s ON s.id = r.shift_instance_id
                            WHERE r.status = ANY(%s) AND r.escalated_at IS NULL AND r.created_at <= %s
                            ORDER BY r.created_at""", (OPEN, now - ESCALATE_AFTER)).fetchall()
