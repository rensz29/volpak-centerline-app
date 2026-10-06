"""The audit log in PostgreSQL (ADR-0012): who, when, what and why for every configuration change,
sign-in and account change.

Rows are append-only and hash-chained by the database (db/migrations/0001). The actor is the
signed-in user the api set on the request's connection (auth.sessions.lookup), unless the
caller names one. Nothing secret goes in.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from centerline_common.db import uuid7
from centerline_common import isotime
from psycopg.types.json import Jsonb

LEGACY = Path("history") / "audit.jsonl"  # where the Configuration page kept its history before ADR-0012
# SQL for whoever is signed in on this connection (auth.sessions.lookup); NULL without a session
ACTOR = "nullif(current_setting('centerline.actor', true), '')"


def iso(t: datetime | None) -> str | None:
    return isotime.iso(t, "seconds")


def record(conn, action: str, summary: str, reason: str | None = None, details: dict | None = None,
           at: datetime | None = None, actor: str | None = None) -> None:
    """Add one entry, inside the caller's transaction."""
    conn.execute(f"""INSERT INTO audit_log (id, at, actor, action, summary, reason, details)
                     VALUES (%s, %s, coalesce(%s, {ACTOR}), %s, %s, %s, %s)""",
                 (uuid7(), at, actor, action, summary, (reason or "").strip() or None, Jsonb(details or {})))


def tail(conn, n: int = 15) -> list[dict]:
    # newest first by time; imported entries keep their own times but joined the chain later
    rows = conn.execute("SELECT at, actor, action, summary, reason, details FROM audit_log ORDER BY at DESC, seq DESC LIMIT %s",
                        (n,)).fetchall()
    return [{"at": iso(r["at"]), "user": r["actor"], "action": r["action"], "summary": r["summary"],
             "reason": r["reason"], "from": r["details"].get("from"), "to": r["details"].get("to")} for r in rows]


def import_legacy(conn, config_dir: Path) -> int:
    """Copy history/audit.jsonl into the audit log once, keeping each entry's time. The file stays as it is."""
    path = config_dir / LEGACY
    if not path.exists():
        return 0
    if conn.execute("SELECT 1 FROM audit_log WHERE details->>'imported_from' = %s LIMIT 1", (str(LEGACY),)).fetchone():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            at = datetime.fromisoformat(e["at"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        extra = {k: v for k, v in e.items() if k not in ("at", "user", "action", "summary", "reason")}
        record(conn, e.get("action") or "unknown", e.get("summary") or e.get("action") or "", e.get("reason"),
               {**extra, "imported_from": str(LEGACY)}, at=at)
        count += 1
    return count
