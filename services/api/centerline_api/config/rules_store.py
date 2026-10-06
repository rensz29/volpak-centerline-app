"""Monitoring rules in PostgreSQL (ADR-0012, ADR-0027): versions and activations.

A version is written once, with its rules, and never changed. It takes effect
through an activation, now or at a set time; activating an older version again
is a rollback (OPC-07). monitor-core reads the version in effect with
active_config_version() and pins each event to it.

Versions saved before ADR-0027 may hold rows for a SKU. They stay as written and count
in the version's fingerprint; the page gets them as `carryOver`, the zones' rows a new
version can start from.
"""

from __future__ import annotations

import json
from decimal import Decimal

from centerline_common import rules as rules_mod
from centerline_common.db import REPO, uuid7
from centerline_common.rules import FIELDS, NUMERIC
from psycopg.types.json import Jsonb

from ..problems import Problem
from . import audit
from .store import invalid
from .versioning import Versioned, reason_errors

PROPOSAL = REPO / "db" / "seed" / "rules-proposal.json"
RULES = Versioned("Rules", "rules", "config_version", "config_activation", "config_version_id",
                  "active_config_version", "centerline.rules")


def _camel_key(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(p.capitalize() for p in rest)


def camel(obj):
    """Stored snake_case → the api's camelCase; numeric columns come back as Decimal."""
    if isinstance(obj, dict):
        return {_camel_key(k): camel(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [camel(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


class RulesStore:
    # -- reading ------------------------------------------------------------------

    @staticmethod
    def proposal() -> dict:
        raw = json.loads(PROPOSAL.read_text(encoding="utf-8"))
        return {"source": raw.get("source"), "settings": camel(raw["settings"]), "rules": camel(raw["rules"])}

    @staticmethod
    def active_number(conn) -> int | None:
        return RULES.active_number(conn)

    @staticmethod
    def _content(conn, version_id) -> tuple[dict, list[dict], bool]:
        """Settings, every stored row (with the SKU of rows saved for one), and whether they match the fingerprint."""
        v = conn.execute("SELECT settings, sha256 FROM config_version WHERE id = %s", (version_id,)).fetchone()
        rows = conn.execute(f"SELECT legacy_sku_code AS sku_code, parameter_id, zone_id, {', '.join(FIELDS)} FROM parameter_rule "
                            "WHERE config_version_id = %s ORDER BY parameter_id, zone_id NULLS FIRST, legacy_sku_code NULLS FIRST",
                            (version_id,)).fetchall()
        rules = [{"sku": r["sku_code"], "parameter_id": r["parameter_id"], "zone_id": r["zone_id"],
                  **{f: r[f] for f in FIELDS}} for r in rows]
        return v["settings"], rules, v["sha256"] == rules_mod.digest(v["settings"], rules)

    @staticmethod
    def _gaps(settings: dict, rules: list[dict], register) -> list[dict]:
        """What each zone lacks: limits (the line isn't judged) or a target (its HMI setpoint isn't)."""
        return [{**camel({k: v for k, v in g.items() if k != "missing"}), "missing": [_camel_key(f) for f in g["missing"]]}
                for g in rules_mod.readiness(rules, settings["defaults"], register.zones)]

    @staticmethod
    def _line(rules: list[dict]) -> list[dict]:
        """The rows that judge the zones, without the SKU key rows saved before ADR-0027 have."""
        return [{k: v for k, v in r.items() if k != "sku"} for r in rules if r.get("sku") is None]

    def overview(self, conn, register) -> dict:
        versions = conn.execute("""SELECT v.id, v.number, v.created_at, v.reason, b.number AS based_on,
                                          r.number AS register_version
                                     FROM config_version v
                                     JOIN register_version r ON r.id = v.register_version_id
                                     LEFT JOIN config_version b ON b.id = v.based_on_id
                                    ORDER BY v.number DESC""").fetchall()
        state = RULES.state(conn)
        active = state["active"]["number"] if state["active"] else None
        gaps = None
        if active is not None:
            vid = next(v["id"] for v in versions if v["number"] == active)
            settings, rules, _ = self._content(conn, vid)
            gaps = self._gaps(settings, rules, register)
        return {
            "active": state["active"],
            "scheduled": state["scheduled"],
            "latest": versions[0]["number"] if versions else None,
            "versions": [{"number": v["number"], "createdAt": audit.iso(v["created_at"]), "reason": v["reason"],
                          "basedOn": v["based_on"], "registerVersion": v["register_version"],
                          "status": state["status"](v["number"])} for v in versions],
            "activations": state["activations"],
            "gaps": gaps,
        }

    def version(self, conn, number: int, register) -> dict:
        v = conn.execute("""SELECT v.id, v.number, v.created_at, v.reason, b.number AS based_on, r.number AS register_version
                              FROM config_version v JOIN register_version r ON r.id = v.register_version_id
                              LEFT JOIN config_version b ON b.id = v.based_on_id WHERE v.number = %s""", (number,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such rules version", f"Rules v{number} doesn't exist")
        settings, rules, intact = self._content(conn, v["id"])
        carried, legacy = rules_mod.carry_over(rules)
        return {"number": v["number"], "createdAt": audit.iso(v["created_at"]), "reason": v["reason"],
                "basedOn": v["based_on"], "registerVersion": v["register_version"], "intact": intact,
                "settings": camel(settings), "rules": camel(self._line(rules)),
                "gaps": self._gaps(settings, rules, register),
                # Saved for a SKU before ADR-0027: the rows a new version starts from, with that SKU's targets
                "carryOver": {"from": legacy, "rules": camel(carried)} if legacy else None}

    # -- checking and saving ----------------------------------------------------------

    @staticmethod
    def _from_body(body) -> tuple[dict, list[dict]]:
        settings = body.settings.model_dump()
        rules = []
        for r in body.rules:
            row = r.model_dump()
            for f in NUMERIC:
                if row[f] is not None:
                    row[f] = Decimal(str(row[f]))  # exact decimals, as typed
            rules.append(row)
        return settings, rules

    def check(self, conn, body, register) -> dict:
        """What a save would say, without saving: problems, and what each zone would lack."""
        settings, rules = self._from_body(body)
        return {"errors": rules_mod.validate(rules, settings["defaults"], register.zones),
                "gaps": self._gaps(settings, rules, register)}

    def create(self, conn, body, register) -> int:
        """Save a new version (and optionally activate it); commits. Returns its number."""
        RULES.lock_now(conn)
        latest = conn.execute("SELECT id, number FROM config_version ORDER BY number DESC LIMIT 1").fetchone()
        latest_n = latest["number"] if latest else None
        if body.expected_latest != latest_n:
            raise Problem(409, "version-conflict", "The rules changed meanwhile",
                          f"Rules v{latest_n} was saved after you started. Reload the page and make your change again.",
                          currentVersion=latest_n)
        settings, rules = self._from_body(body)
        errors = rules_mod.validate(rules, settings["defaults"], register.zones)
        errors += reason_errors(body.reason)
        now = RULES.now(conn)
        if body.activate == "at" and (body.activate_at is None or body.activate_at <= now):
            errors.append({"field": "activateAt", "message": "Pick a time in the future"})
        based_on = None
        if body.based_on is not None:
            based_on = conn.execute("SELECT id FROM config_version WHERE number = %s", (body.based_on,)).fetchone()
            if based_on is None:
                errors.append({"field": "basedOn", "message": f"Rules v{body.based_on} doesn't exist"})
        if errors:
            raise invalid("The rules can't be saved", errors)

        keep = [r for r in rules if not rules_mod.is_empty(r)]
        number, vid = (latest_n or 0) + 1, uuid7()
        reg = conn.execute("SELECT id FROM register_version ORDER BY seq DESC LIMIT 1").fetchone()
        sha = rules_mod.digest(settings, keep)
        conn.execute(f"""INSERT INTO config_version (id, number, based_on_id, register_version_id, settings, sha256, reason,
                                                    created_by)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, {audit.ACTOR})""",
                     (vid, number, based_on["id"] if based_on else None, reg["id"], Jsonb(settings), sha, body.reason.strip()))
        with conn.cursor() as cur:
            cur.executemany(f"""INSERT INTO parameter_rule (config_version_id, parameter_id, zone_id, {', '.join(FIELDS)})
                                VALUES (%s, %s, %s{', %s' * len(FIELDS)})""",
                            [(vid, r["parameter_id"], r["zone_id"], *(r[f] for f in FIELDS)) for r in keep])
        audit.record(conn, "rules.version",
                     f"Rules v{number} saved{f' from v{body.based_on}' if body.based_on else ''}: {len(keep)} rule rows",
                     body.reason, {"version": number, "based_on": body.based_on, "sha256": sha})
        if body.activate != "no":
            RULES.record(conn, vid, number, body.activate_at if body.activate == "at" else None, body.reason, now)
        conn.commit()
        return number

    @staticmethod
    def activate(conn, number: int, body) -> None:
        RULES.activate(conn, number, body)

    @staticmethod
    def cancel(conn, activation_id, body) -> None:
        RULES.cancel(conn, activation_id, body)
