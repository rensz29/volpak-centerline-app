"""Tag mappings in PostgreSQL (ADR-0013): where each register tag arrives on MQTT.

Versions are written once and take effect through activations, like the rules
(versioning.py). Only a version that covers the register, meaning every monitored
zone's setpoint and actual and the machine-state tags, can be activated:
monitor-core can't judge a zone it can't read.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from centerline_common import mapping as mapping_mod
from centerline_common.db import uuid7

from ..problems import Problem
from . import audit
from .rules_store import camel
from .store import invalid
from .versioning import Versioned, reason_errors

MAPPINGS = Versioned("Mapping", "mapping", "mapping_version", "mapping_activation", "mapping_version_id",
                     "active_mapping_version", "centerline.mappings")


def required_view(register) -> list[dict]:
    return [camel(asdict(r)) for r in mapping_mod.required(register)]


def coverage_view(rows: list[dict], register) -> dict:
    c = mapping_mod.coverage(rows, register)
    return {"required": c["required"], "mapped": c["mapped"], "missing": [camel(asdict(r)) for r in c["missing"]]}


def coverage_errors(rows: list[dict], register) -> list[dict]:
    missing = mapping_mod.coverage(rows, register)["missing"]
    if not missing:
        return []
    names = ", ".join(r.label for r in missing[:6]) + (f" and {len(missing) - 6} more" if len(missing) > 6 else "")
    return [{"field": "rows", "message": f"{len(missing)} tag{'s' if len(missing) != 1 else ''} monitor-core needs "
                                         f"{'have' if len(missing) != 1 else 'has'} no place yet: {names}"}]


class MappingStore:
    @staticmethod
    def active_number(conn) -> int | None:
        return MAPPINGS.active_number(conn)

    @staticmethod
    def _content(conn, vid) -> tuple[list[dict], bool]:
        """A version's rows, and whether they still match its fingerprint. Versions saved before ADR-0027 may also
        have recorded a SKU field or placeholder: it counts in their fingerprint, and nothing else reads it."""
        v = conn.execute("""SELECT legacy_sku_topic, legacy_sku_field, legacy_sku_placeholder, sha256
                              FROM mapping_version WHERE id = %s""", (vid,)).fetchone()
        rows = [dict(r) for r in conn.execute("SELECT tag, topic, field FROM tag_mapping WHERE mapping_version_id = %s ORDER BY tag",
                                               (vid,))]
        legacy = ({"topic": v["legacy_sku_topic"], "field": v["legacy_sku_field"]} if v["legacy_sku_topic"]
                  else {"placeholder": v["legacy_sku_placeholder"]} if v["legacy_sku_placeholder"] else None)
        return rows, v["sha256"] == mapping_mod.digest(rows, legacy)

    def overview(self, conn, register, subscriptions: list[str]) -> dict:
        versions = conn.execute("""SELECT v.id, v.number, v.created_at, v.reason, v.source, b.number AS based_on,
                                          r.number AS register_version
                                     FROM mapping_version v
                                     JOIN register_version r ON r.id = v.register_version_id
                                     LEFT JOIN mapping_version b ON b.id = v.based_on_id
                                    ORDER BY v.number DESC""").fetchall()
        state = MAPPINGS.state(conn)
        active = state["active"]["number"] if state["active"] else None
        coverage = None
        if active is not None:
            rows, _ = self._content(conn, next(v["id"] for v in versions if v["number"] == active))
            coverage = coverage_view(rows, register)
        return {
            "active": state["active"],
            "scheduled": state["scheduled"],
            "latest": versions[0]["number"] if versions else None,
            "versions": [{"number": v["number"], "createdAt": audit.iso(v["created_at"]), "reason": v["reason"],
                          "source": v["source"], "basedOn": v["based_on"], "registerVersion": v["register_version"],
                          "status": state["status"](v["number"])} for v in versions],
            "activations": state["activations"],
            "required": required_view(register),
            "coverage": coverage,
            "subscriptions": subscriptions,
        }

    def version(self, conn, number: int, register, subscriptions: list[str]) -> dict:
        v = conn.execute("""SELECT v.id, v.number, v.created_at, v.reason, v.source, b.number AS based_on,
                                   r.number AS register_version
                              FROM mapping_version v JOIN register_version r ON r.id = v.register_version_id
                              LEFT JOIN mapping_version b ON b.id = v.based_on_id WHERE v.number = %s""", (number,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such mapping version", f"Mapping v{number} doesn't exist")
        rows, intact = self._content(conn, v["id"])
        _, warnings = mapping_mod.validate(rows, register, subscriptions)
        return {"number": v["number"], "createdAt": audit.iso(v["created_at"]), "reason": v["reason"], "source": v["source"],
                "basedOn": v["based_on"], "registerVersion": v["register_version"], "intact": intact,
                "rows": rows, "coverage": coverage_view(rows, register), "warnings": warnings}

    @staticmethod
    def _from_body(body) -> list[dict]:
        return [{"tag": r.tag.strip(), "topic": r.topic, "field": (r.field or "").strip() or None} for r in body.rows]

    def check(self, body, register, subscriptions: list[str]) -> dict:
        rows = self._from_body(body)
        errors, warnings = mapping_mod.validate(rows, register, subscriptions)
        return {"errors": errors, "warnings": warnings, "coverage": coverage_view(rows, register)}

    def create(self, conn, body, register, subscriptions: list[str]) -> int:
        """Save a new version (and optionally activate it); commits. Returns its number."""
        MAPPINGS.lock_now(conn)
        latest = conn.execute("SELECT id, number FROM mapping_version ORDER BY number DESC LIMIT 1").fetchone()
        latest_n = latest["number"] if latest else None
        if body.expected_latest != latest_n:
            raise Problem(409, "version-conflict", "The mappings changed meanwhile",
                          f"Mapping v{latest_n} was saved after you started. Reload the page and make your change again.",
                          currentVersion=latest_n)
        rows = self._from_body(body)
        errors, _ = mapping_mod.validate(rows, register, subscriptions)
        errors += reason_errors(body.reason)
        now = MAPPINGS.now(conn)
        if body.activate != "no":
            errors += coverage_errors(rows, register)
        if body.activate == "at" and (body.activate_at is None or body.activate_at <= now):
            errors.append({"field": "activateAt", "message": "Pick a time in the future"})
        based_on = None
        if body.based_on is not None:
            based_on = conn.execute("SELECT id FROM mapping_version WHERE number = %s", (body.based_on,)).fetchone()
            if based_on is None:
                errors.append({"field": "basedOn", "message": f"Mapping v{body.based_on} doesn't exist"})
        if errors:
            raise invalid("The mapping can't be saved", errors)

        number, vid = (latest_n or 0) + 1, uuid7()
        reg = conn.execute("SELECT id FROM register_version ORDER BY seq DESC LIMIT 1").fetchone()
        sha = mapping_mod.digest(rows)
        conn.execute(f"""INSERT INTO mapping_version (id, number, based_on_id, register_version_id, source, sha256, reason,
                                                      created_by)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, {audit.ACTOR})""",
                     (vid, number, based_on["id"] if based_on else None, reg["id"], body.source.strip() or "by hand", sha,
                      body.reason.strip()))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO tag_mapping (mapping_version_id, tag, topic, field) VALUES (%s, %s, %s, %s)",
                            [(vid, r["tag"], r["topic"], r["field"]) for r in rows])
        audit.record(conn, "mapping.version",
                     f"Mapping v{number} saved{f' from v{body.based_on}' if body.based_on else ''}: {len(rows)} tags"
                     f" ({body.source.strip() or 'by hand'})",
                     body.reason, {"version": number, "based_on": body.based_on, "sha256": sha})
        if body.activate != "no":
            MAPPINGS.record(conn, vid, number, body.activate_at if body.activate == "at" else None, body.reason, now)
        conn.commit()
        return number

    def activate(self, conn, number: int, body, register) -> None:
        def complete(conn, vid) -> list[dict]:
            rows, intact = self._content(conn, vid)
            problems = coverage_errors(rows, register)
            if not intact:
                problems.append({"field": "at", "message": f"Mapping v{number} was changed outside Centerline; don't use it"})
            return problems

        MAPPINGS.activate(conn, number, body, precheck=complete)

    @staticmethod
    def cancel(conn, activation_id, body) -> None:
        MAPPINGS.cancel(conn, activation_id, body)

    # -- files ------------------------------------------------------------------------

    @staticmethod
    def import_file(body, register) -> dict:
        """Rows from a probe topic-map.json or a tag,topic,field CSV, for the editor; nothing is saved."""
        if body.format == "topic-map":
            try:
                obj = json.loads(body.content)
                rows, ignored, not_seen = mapping_mod.from_topic_map(obj, register)
            except (json.JSONDecodeError, AttributeError, KeyError, TypeError) as e:
                raise invalid("That isn't a topic-map.json from tools/mqtt-probe",
                              [{"field": "content", "message": f"Not a probe topic map: {e}"}]) from None
            return {"rows": rows, "ignored": ignored, "notSeen": not_seen, "problems": [],
                    "source": f"probe topic map {obj.get('generated', '')[:16]}".strip()}
        rows, problems = mapping_mod.from_csv(body.content)
        return {"rows": rows, "ignored": [], "notSeen": [], "problems": problems, "source": "CSV file"}

    def export_csv(self, conn, number: int) -> str:
        vid = MAPPINGS.version_id(conn, number)
        rows, _ = self._content(conn, vid)
        return mapping_mod.to_csv(rows)
