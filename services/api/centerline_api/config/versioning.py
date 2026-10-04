"""Numbered versions that take effect through activations (OPC-07): shared by the rules and the mappings.

A version is written once and never changed. An activation makes it take effect
now or at a set time; the version in effect is the latest activation whose time
has come, and activating an older version again is a rollback. A scheduled
activation can be cancelled until it takes effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from centerline_common.db import uuid7

from ..problems import Problem
from . import audit
from .store import invalid

MANILA = timezone(timedelta(hours=8))


def manila(t: datetime) -> str:
    return t.astimezone(MANILA).strftime("%d %b %Y %H:%M")


def reason_errors(text: str, field: str = "reason") -> list[dict]:
    return [] if len(text.strip()) >= 3 else [{"field": field, "message": "Say why (at least 3 characters)"}]


@dataclass(frozen=True)
class Versioned:
    label: str  # "Rules", "Mapping": how people see a version, e.g. "Rules v3"
    action: str  # audit action prefix
    versions: str  # table of versions
    activations: str  # table of activations
    version_column: str  # the activations table's reference to a version
    active_function: str  # SQL function returning the version in effect
    lock: str  # advisory lock name serialising saves and activations

    def lock_now(self, conn) -> None:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.lock,))

    @staticmethod
    def now(conn) -> datetime:
        return conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]

    def active_number(self, conn) -> int | None:
        row = conn.execute(f"SELECT number FROM {self.versions} WHERE id = {self.active_function}()").fetchone()
        return row["number"] if row else None

    def version_id(self, conn, number: int):
        row = conn.execute(f"SELECT id FROM {self.versions} WHERE number = %s", (number,)).fetchone()
        if row is None:
            raise Problem(404, "not-found", f"No such {self.label.lower()} version", f"{self.label} v{number} doesn't exist")
        return row["id"]

    def state(self, conn) -> dict:
        """What's in effect, what's scheduled, recent activations, and each version's status."""
        acts = conn.execute(f"""SELECT a.id, v.number, a.effective_at, a.created_at, a.created_by, a.reason, a.cancelled_at,
                                       a.cancelled_by, a.cancel_reason
                                  FROM {self.activations} a JOIN {self.versions} v ON v.id = a.{self.version_column}
                                 ORDER BY a.effective_at DESC, a.created_at DESC""").fetchall()
        now, active = self.now(conn), self.active_number(conn)
        live = [a for a in acts if a["cancelled_at"] is None]
        in_effect = next((a for a in live if a["effective_at"] <= now), None)
        scheduled = [a for a in live if a["effective_at"] > now]
        was_active = {a["number"] for a in live if a["effective_at"] <= now}

        def status(n: int) -> str:
            if n == active:
                return "active"
            if any(a["number"] == n for a in scheduled):
                return "scheduled"
            return "previous" if n in was_active else "saved"

        return {
            "active": None if in_effect is None else {"number": active, "since": audit.iso(in_effect["effective_at"]),
                                                      "reason": in_effect["reason"], "by": in_effect["created_by"]},
            "scheduled": [{"id": str(a["id"]), "number": a["number"], "at": audit.iso(a["effective_at"]),
                           "reason": a["reason"], "by": a["created_by"]} for a in reversed(scheduled)],
            "activations": [{"id": str(a["id"]), "number": a["number"], "at": audit.iso(a["effective_at"]),
                             "createdAt": audit.iso(a["created_at"]), "reason": a["reason"], "by": a["created_by"],
                             "cancelledAt": audit.iso(a["cancelled_at"]), "cancelledBy": a["cancelled_by"],
                             "cancelReason": a["cancel_reason"]}
                            for a in acts[:20]],
            "status": status,
        }

    def record(self, conn, vid, number: int, at: datetime | None, reason: str, now: datetime) -> None:
        """Append an activation (now when ``at`` is None) and audit it; the caller commits."""
        active = self.active_number(conn)
        again = conn.execute(f"""SELECT 1 FROM {self.activations} WHERE {self.version_column} = %s
                                   AND cancelled_at IS NULL AND effective_at <= %s LIMIT 1""", (vid, now)).fetchone() is not None
        effective = at or now
        conn.execute(f"""INSERT INTO {self.activations} (id, {self.version_column}, effective_at, reason, created_by)
                         VALUES (%s, %s, %s, %s, {audit.ACTOR})""",
                     (uuid7(), vid, effective, reason.strip()))
        what = f"{self.label} v{number} {'scheduled for ' + manila(at) + ' Manila' if at else 'activated'}"
        if again:
            what += " (rollback)"
        if active is not None and active != number and at is None:
            what += f", replacing v{active}"
        audit.record(conn, f"{self.action}.activate", what, reason,
                     {"version": number, "effective_at": audit.iso(effective), "replaces": active})

    def activate(self, conn, number: int, body, precheck=None) -> None:
        """Activate now or at body.at; ``precheck(conn, version_id)`` may add problems. Commits."""
        self.lock_now(conn)
        vid = self.version_id(conn, number)
        active = self.active_number(conn)
        if body.expected_active != active:
            raise Problem(409, "version-conflict", f"The {self.label.lower()} in effect changed meanwhile",
                          f"{f'{self.label} v{active}' if active else 'Nothing'} is in effect now. Reload the page and try again.",
                          currentActive=active)
        now = self.now(conn)
        errors = reason_errors(body.reason)
        if body.at is not None and body.at <= now:
            errors.append({"field": "at", "message": "Pick a time in the future, or leave it empty to activate now"})
        if body.at is None and active == number:
            errors.append({"field": "at", "message": f"{self.label} v{number} is already in effect"})
        if precheck:
            errors += precheck(conn, vid)
        if errors:
            raise invalid(f"{self.label} v{number} can't be activated", errors)
        self.record(conn, vid, number, body.at, body.reason, now)
        conn.commit()

    def cancel(self, conn, activation_id, body) -> None:
        if errors := reason_errors(body.reason):
            raise invalid("The activation can't be cancelled", errors)
        row = conn.execute(f"""UPDATE {self.activations} SET cancelled_at = clock_timestamp(), cancel_reason = %s,
                                      cancelled_by = {audit.ACTOR}
                                WHERE id = %s AND cancelled_at IS NULL AND effective_at > clock_timestamp()
                            RETURNING {self.version_column} AS vid, effective_at""", (body.reason.strip(), activation_id)).fetchone()
        if row is None:
            raise Problem(409, "not-scheduled", "Nothing to cancel",
                          "That activation has already taken effect or was cancelled. Reload the page.")
        number = conn.execute(f"SELECT number FROM {self.versions} WHERE id = %s", (row["vid"],)).fetchone()["number"]
        audit.record(conn, f"{self.action}.cancel",
                     f"Scheduled activation of {self.label} v{number} for {manila(row['effective_at'])} Manila cancelled",
                     body.reason, {"version": number, "activation": str(activation_id)})
        conn.commit()
