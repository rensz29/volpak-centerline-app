"""Adding deliveries to the outbox (ADR-0023), shared by the notifier and the api.

The notifier adds them when it routes a message; the api adds a TEST message's (NOT-07) and an
Administrator's re-drive (NOT-05). Each delivery stores its content as it will be sent, so
every retry sends the same message with the same dedup key and Message-ID.
"""

from __future__ import annotations

from datetime import datetime

from psycopg.types.json import Jsonb

from . import messages
from .db import uuid7


def event_of(conn, event_id) -> dict | None:
    """What a message about an event says about it: its kind, when it opened, its SKU and the rule it was judged by."""
    if event_id is None:
        return None
    return conn.execute("SELECT kind, opened_at, sku_code, rule FROM event WHERE id = %s", (event_id,)).fetchone()


def add_delivery(conn, n: dict, type_: str, channel: str, target: str, rule: str | None, now: datetime, *,
                 event: dict | None, line: str, app_url: str | None, redrive: dict | None = None) -> str:
    """One delivery of notification n, due now; returns its id. A re-drive gets its own dedup key and Message-ID."""
    did = uuid7()
    dedup = f"{n['dedup_key']}:{channel}:{target}" + (f":redrive:{did}" if redrive else "")
    message_id = f"<{did}@centerline>"
    content = messages.content(n, type_, channel, target, dedup, message_id, event=event, line=line, app_url=app_url)
    conn.execute("""INSERT INTO notification_delivery (id, notification_id, channel, target, rule, dedup_key, message_id,
                                                       content, created_at, next_attempt_at, redrive_of, redriven_by, redrive_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                 (did, n["id"], channel, target, rule, dedup, message_id, Jsonb(content), now, now,
                  (redrive or {}).get("of"), (redrive or {}).get("by"), (redrive or {}).get("reason")))
    return str(did)
