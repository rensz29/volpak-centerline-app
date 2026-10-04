"""Notification routing on the Configuration page (ADR-0023): who gets which messages, on which channel.

Versions are written once and take effect through activations, like the rules and the mappings
(OPC-07). A version that leaves a kind of Critical with nobody to tell can be saved, but not
activated (ACT-03). The first version starts from db/seed/routing-proposal.json.
"""

from __future__ import annotations

import json

from centerline_common import routing as routing_mod
from centerline_common.db import REPO, uuid7
from psycopg.types.json import Jsonb

from ..problems import Problem
from . import audit
from .store import invalid
from .versioning import Versioned, reason_errors

ROUTING = Versioned("Routing", "routing", "routing_version", "routing_activation", "routing_version_id",
                    "active_routing_version", "centerline.routing")
PROPOSAL = REPO / "db" / "seed" / "routing-proposal.json"


def _rules(body) -> list[dict]:
    return routing_mod.normalize([r.model_dump() for r in body.rules])


def _critical_errors(rules: list[dict]) -> list[dict]:
    gaps = routing_mod.critical_gaps(rules)
    return [{"field": "rules", "message": "Critical alerts must reach someone (ACT-03): "
             + ", ".join(routing_mod.TYPES[t] for t in gaps)}] if gaps else []


def types_view() -> list[dict]:
    return [{"id": t, "label": label, "critical": t in routing_mod.CRITICAL} for t, label in routing_mod.TYPES.items()]


class RoutingStore:
    @staticmethod
    def proposal() -> dict:
        raw = json.loads(PROPOSAL.read_text(encoding="utf-8"))
        rules = routing_mod.normalize(raw["rules"])
        return {"source": raw["source"], "rules": rules, "warnings": routing_mod.warnings(rules)}

    @staticmethod
    def active_rules(conn) -> tuple[int | None, list[dict]]:
        row = conn.execute("SELECT number, rules FROM routing_version WHERE id = active_routing_version()").fetchone()
        return (row["number"], row["rules"]) if row else (None, [])

    def overview(self, conn) -> dict:
        versions = conn.execute("""SELECT v.number, v.created_at, v.created_by, v.reason, b.number AS based_on
                                     FROM routing_version v LEFT JOIN routing_version b ON b.id = v.based_on_id
                                    ORDER BY v.number DESC""").fetchall()
        state = ROUTING.state(conn)
        _, rules = self.active_rules(conn)
        return {
            "active": state["active"],
            "scheduled": state["scheduled"],
            "latest": versions[0]["number"] if versions else None,
            "versions": [{"number": v["number"], "createdAt": audit.iso(v["created_at"]), "by": v["created_by"],
                          "reason": v["reason"], "basedOn": v["based_on"], "status": state["status"](v["number"])}
                         for v in versions],
            "activations": state["activations"],
            "rules": rules if state["active"] else None,
            "warnings": routing_mod.warnings(rules) if state["active"] else [],
            "types": types_view(),
            "channels": [{"id": c, "label": label} for c, label in routing_mod.CHANNELS.items()],
        }

    def version(self, conn, number: int) -> dict:
        v = conn.execute("""SELECT v.number, v.created_at, v.created_by, v.reason, v.rules, v.sha256, b.number AS based_on
                              FROM routing_version v LEFT JOIN routing_version b ON b.id = v.based_on_id
                             WHERE v.number = %s""", (number,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such routing version", f"Routing v{number} doesn't exist")
        return {"number": v["number"], "createdAt": audit.iso(v["created_at"]), "by": v["created_by"], "reason": v["reason"],
                "basedOn": v["based_on"], "rules": v["rules"], "intact": v["sha256"] == routing_mod.digest(v["rules"]),
                "warnings": routing_mod.warnings(v["rules"])}

    @staticmethod
    def check(body) -> dict:
        rules = _rules(body)
        return {"errors": routing_mod.validate(rules), "warnings": routing_mod.warnings(rules)}

    def create(self, conn, body) -> int:
        """Save a new version (and optionally activate it); commits. Returns its number."""
        ROUTING.lock_now(conn)
        latest = conn.execute("SELECT number FROM routing_version ORDER BY number DESC LIMIT 1").fetchone()
        latest_n = latest["number"] if latest else None
        if body.expected_latest != latest_n:
            raise Problem(409, "version-conflict", "The routing changed meanwhile",
                          f"Routing v{latest_n} was saved after you started. Reload the page and make your change again.",
                          currentVersion=latest_n)
        rules = _rules(body)
        errors = routing_mod.validate(rules) + reason_errors(body.reason)
        now = ROUTING.now(conn)
        if body.activate != "no":
            errors += _critical_errors(rules)
        if body.activate == "at" and (body.activate_at is None or body.activate_at <= now):
            errors.append({"field": "activateAt", "message": "Pick a time in the future"})
        based_on = None
        if body.based_on is not None:
            based_on = conn.execute("SELECT id FROM routing_version WHERE number = %s", (body.based_on,)).fetchone()
            if based_on is None:
                errors.append({"field": "basedOn", "message": f"Routing v{body.based_on} doesn't exist"})
        if errors:
            raise invalid("The routing can't be saved", errors)

        number, vid, sha = (latest_n or 0) + 1, uuid7(), routing_mod.digest(rules)
        conn.execute(f"""INSERT INTO routing_version (id, number, based_on_id, rules, sha256, reason, created_by)
                         VALUES (%s, %s, %s, %s, %s, %s, {audit.ACTOR})""",
                     (vid, number, based_on["id"] if based_on else None, Jsonb(rules), sha, body.reason.strip()))
        recipients = len({(r["channel"], t.lower()) for r in rules for t in r["targets"]})
        audit.record(conn, "routing.version",
                     f"Routing v{number} saved{f' from v{body.based_on}' if body.based_on else ''}: {len(rules)} rule"
                     f"{'s' if len(rules) != 1 else ''}, {recipients} recipient{'s' if recipients != 1 else ''}",
                     body.reason, {"version": number, "based_on": body.based_on, "sha256": sha})
        if body.activate != "no":
            ROUTING.record(conn, vid, number, body.activate_at if body.activate == "at" else None, body.reason, now)
        conn.commit()
        return number

    def activate(self, conn, number: int, body) -> None:
        def complete(conn, vid) -> list[dict]:
            v = conn.execute("SELECT rules, sha256 FROM routing_version WHERE id = %s", (vid,)).fetchone()
            problems = _critical_errors(v["rules"])
            if v["sha256"] != routing_mod.digest(v["rules"]):
                problems.append({"field": "at", "message": f"Routing v{number} was changed outside Centerline; don't use it"})
            return problems

        ROUTING.activate(conn, number, body, precheck=complete)

    @staticmethod
    def cancel(conn, activation_id, body) -> None:
        ROUTING.cancel(conn, activation_id, body)
