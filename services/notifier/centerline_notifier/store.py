"""The notifier's database work (SDD §8, ADR-0023).

* **Routing**: each new message is routed once by the routing in effect. What matched is frozen
  in `notification_route`, and each channel × target gets a delivery with the message as sent.
  Two notifiers can't route one message twice: the route's key decides.
* **Lanes**: each channel claims its due deliveries (FOR UPDATE SKIP LOCKED), and each attempt
  is recorded with what the provider said.
* **Recovery**: a delivery left mid-attempt by a crash has an unknown outcome. It's tried
  again, unchanged, with the same dedup key and Message-ID.
* **Watching**: if monitor-core's heartbeat goes silent for 60 s, Management gets a Critical
  system alert, and one notice when it's back. Both are ordinary outbox rows, written once.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from centerline_common import routing as routing_mod
from centerline_common.channels import Outcome
from centerline_common.db import uuid7
from centerline_common.isotime import iso, parse
from centerline_common.outbox import add_delivery

from .schedule import GIVE_UP, next_attempt

ROUTE_BATCH = 50
LEASE = timedelta(minutes=2)  # longer than any send takes: the timeouts are 15–20 s
SILENT = "monitor-core silent"


def route_pending(conn, now: datetime, *, line: str, app_url: str | None) -> int:
    """Route every message not routed yet, oldest first. Returns how many were routed."""
    active = conn.execute("SELECT number, rules FROM routing_version WHERE id = active_routing_version()").fetchone()
    rows = conn.execute("""SELECT n.id, n.dedup_key, n.kind, n.event_id, n.created_at, n.payload,
                                  e.kind AS event_kind, e.opened_at, e.rule AS event_rule
                             FROM notification n LEFT JOIN event e ON e.id = n.event_id
                            WHERE NOT EXISTS (SELECT 1 FROM notification_route r WHERE r.notification_id = n.id)
                            ORDER BY n.created_at, n.id LIMIT %s""", (ROUTE_BATCH,)).fetchall()
    for n in rows:
        type_ = routing_mod.type_of(n["kind"], n["payload"])
        places: list[tuple[str, str, str]] = []
        if now - n["created_at"] > GIVE_UP:
            outcome = "expired"  # too old to be worth sending (NOT-05's 24 h)
        elif active is None:
            outcome = "unrouted"  # no routing in effect: nobody to send it to
        else:
            places = routing_mod.match(active["rules"], type_)
            outcome = "routed" if places else "unrouted"
        matched = [r for r in (active["rules"] if active else []) if type_ in r["types"]]
        won = conn.execute("""INSERT INTO notification_route (notification_id, routed_at, type, routing_version, matched, outcome)
                              VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (notification_id) DO NOTHING
                              RETURNING notification_id""",
                           (n["id"], now, type_, active["number"] if active else None, Jsonb(matched), outcome)).fetchone()
        if won and places:
            event = None if n["event_id"] is None else {"kind": n["event_kind"], "opened_at": n["opened_at"],
                                                         "rule": n["event_rule"]}
            for rule, channel, target in places:
                add_delivery(conn, n, type_, channel, target, rule, now, event=event, line=line, app_url=app_url)
        conn.commit()
    return len(rows)


def recover(conn, now: datetime) -> int:
    """Deliveries a crash left mid-attempt: recorded as interrupted and due again at once."""
    rows = conn.execute("""UPDATE notification_delivery SET status = 'RETRYING', next_attempt_at = %s,
                                  last_error = 'Interrupted: the notifier stopped during this attempt, so its outcome is unknown'
                            WHERE status = 'ATTEMPTING' RETURNING id, attempt_count""", (now,)).fetchall()
    for r in rows:
        conn.execute("""INSERT INTO delivery_attempt (id, delivery_id, attempt, started_at, ended_at, outcome, response)
                        VALUES (%s, %s, %s, %s, %s, 'interrupted', 'The notifier stopped during this attempt')
                        ON CONFLICT (delivery_id, attempt) DO NOTHING""", (uuid7(), r["id"], r["attempt_count"], now, now))
    conn.commit()
    return len(rows)


def claim(conn, channel: str, now: datetime, batch: int = 10) -> list[dict]:
    """The channel's due deliveries, each leased for LEASE while it's attempted.

    A lease that runs out means its attempt was cut short (the database or the notifier went
    away): that attempt is recorded as interrupted, and the delivery is tried again."""
    rows = conn.execute("""SELECT id, target, dedup_key, message_id, content, attempt_count, created_at, status
                             FROM notification_delivery
                            WHERE channel = %s AND status IN ('PENDING', 'RETRYING', 'ATTEMPTING') AND next_attempt_at <= %s
                            ORDER BY next_attempt_at, id FOR UPDATE SKIP LOCKED LIMIT %s""", (channel, now, batch)).fetchall()
    for r in rows:
        if r["status"] == "ATTEMPTING":
            conn.execute("""INSERT INTO delivery_attempt (id, delivery_id, attempt, started_at, ended_at, outcome, response)
                            VALUES (%s, %s, %s, %s, %s, 'interrupted', 'The attempt was cut short; its outcome is unknown')
                            ON CONFLICT (delivery_id, attempt) DO NOTHING""", (uuid7(), r["id"], r["attempt_count"], now, now))
        conn.execute("""UPDATE notification_delivery SET status = 'ATTEMPTING', attempt_count = attempt_count + 1,
                               next_attempt_at = %s WHERE id = %s""", (now + LEASE, r["id"]))
    conn.commit()
    return [dict(r, attempt=r["attempt_count"] + 1) for r in rows]


def finish(conn, d: dict, channel: str, outcome: Outcome, started: datetime, ended: datetime) -> str:
    """Record one attempt and what follows from it. Returns the delivery's new status."""
    if outcome.ok:
        status, nxt = ("DELIVERED" if channel == "teams" else "SUBMITTED"), None
    else:
        nxt = next_attempt(d["created_at"], d["attempt"], ended)
        status = "RETRYING" if nxt else "PERMANENT_FAILURE"
    conn.execute("""UPDATE notification_delivery SET status = %s, next_attempt_at = %s, last_error = %s, finished_at = %s
                     WHERE id = %s""",
                 (status, nxt, None if outcome.ok else outcome.response, None if status == "RETRYING" else ended, d["id"]))
    conn.execute("""INSERT INTO delivery_attempt (id, delivery_id, attempt, started_at, ended_at, outcome, response)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                 (uuid7(), d["id"], d["attempt"], started, ended,
                  ("delivered" if channel == "teams" else "submitted") if outcome.ok else "failed", outcome.response))
    conn.commit()
    return status


def watch_monitor(conn, now: datetime, stale_s: float) -> str | None:
    """Raise the Critical "monitor-core silent" alert once per silence, and the notice when it's back."""
    beat = conn.execute("SELECT instance, beat_at FROM monitor_heartbeat ORDER BY beat_at DESC LIMIT 1").fetchone()
    if beat is None:
        return None  # monitor-core has never run here: nothing to watch yet
    raised = None
    if (now - beat["beat_at"]).total_seconds() > stale_s:
        key = f"watch:monitor-core:{beat['instance']}:{beat['beat_at'].isoformat()}"
        raised = _system(conn, key, now, {"kind": SILENT, "instance": beat["instance"], "since": iso(beat["beat_at"]),
                                         "silentS": round((now - beat["beat_at"]).total_seconds())})
    else:
        last = conn.execute("""SELECT dedup_key, payload FROM notification WHERE kind = 'system' AND payload->>'kind' = %s
                                ORDER BY created_at DESC LIMIT 1""", (SILENT,)).fetchone()
        if last and beat["beat_at"] > parse(last["payload"]["since"]):
            raised = _system(conn, last["dedup_key"] + ":back", now,
                             {"kind": "monitor-core back", "instance": beat["instance"], "since": last["payload"]["since"]})
    conn.commit()
    return raised


def _system(conn, key: str, now: datetime, payload: dict) -> str | None:
    row = conn.execute("""INSERT INTO notification (id, dedup_key, kind, event_id, created_at, payload)
                          VALUES (%s, %s, 'system', NULL, %s, %s) ON CONFLICT (dedup_key) DO NOTHING RETURNING dedup_key""",
                       (uuid7(), key, now, Jsonb(payload))).fetchone()
    return row["dedup_key"] if row else None


def beat(conn, instance: str, started: datetime, now: datetime, status: dict) -> None:
    conn.execute("""INSERT INTO notifier_heartbeat (instance, started_at, beat_at, status) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (instance) DO UPDATE SET started_at = EXCLUDED.started_at, beat_at = EXCLUDED.beat_at,
                                                         status = EXCLUDED.status""",
                 (instance, started, now, Jsonb(status)))
    conn.commit()


def backlog(conn) -> dict:
    """Deliveries still to go, and failed for good, per channel: for the heartbeat and the health page."""
    rows = conn.execute("""SELECT channel, count(*) FILTER (WHERE status IN ('PENDING', 'ATTEMPTING', 'RETRYING')) AS waiting,
                                  count(*) FILTER (WHERE status = 'PERMANENT_FAILURE') AS failed
                             FROM notification_delivery GROUP BY channel""").fetchall()
    return {r["channel"]: {"waiting": r["waiting"], "failed": r["failed"]} for r in rows}
