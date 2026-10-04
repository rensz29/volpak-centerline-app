"""Monitoring rules in PostgreSQL (ADR-0012): versions, activations and SKUs.

A version is written once, with its rules, and never changed. It takes effect
through an activation, now or at a set time; activating an older version again
is a rollback (OPC-07). monitor-core (Phase 1) will read the version in effect
with active_config_version() and pin each event to it.
"""

from __future__ import annotations

import json
from decimal import Decimal

from centerline_common import rules as rules_mod
from centerline_common.db import REPO, uuid7
from centerline_common.rules import FIELDS, NUMERIC
from psycopg import errors as pg_errors
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
    def skus(conn) -> list[dict]:
        return conn.execute("SELECT code, name FROM sku ORDER BY code").fetchall()

    @staticmethod
    def active_number(conn) -> int | None:
        return RULES.active_number(conn)

    @staticmethod
    def _content(conn, version_id) -> tuple[dict, list[dict], bool]:
        v = conn.execute("SELECT settings, sha256 FROM config_version WHERE id = %s", (version_id,)).fetchone()
        rows = conn.execute(f"SELECT sku_code, parameter_id, zone_id, {', '.join(FIELDS)} FROM sku_parameter_rule "
                            "WHERE config_version_id = %s ORDER BY parameter_id, zone_id NULLS FIRST, sku_code NULLS FIRST",
                            (version_id,)).fetchall()
        rules = [{"sku": r["sku_code"], "parameter_id": r["parameter_id"], "zone_id": r["zone_id"],
                  **{f: r[f] for f in FIELDS}} for r in rows]
        return v["settings"], rules, v["sha256"] == rules_mod.digest(v["settings"], rules)

    @staticmethod
    def _readiness(settings: dict, rules: list[dict], register, skus: list[str]) -> dict:
        ready = rules_mod.readiness(rules, settings["defaults"], register.zones, skus)
        return {sku: [{**camel({k: v for k, v in g.items() if k != "missing"}),
                       "missing": [_camel_key(f) for f in g["missing"]]} for g in gaps]
                for sku, gaps in ready.items()}

    def overview(self, conn, register) -> dict:
        versions = conn.execute("""SELECT v.id, v.number, v.created_at, v.reason, b.number AS based_on,
                                          r.number AS register_version
                                     FROM config_version v
                                     JOIN register_version r ON r.id = v.register_version_id
                                     LEFT JOIN config_version b ON b.id = v.based_on_id
                                    ORDER BY v.number DESC""").fetchall()
        state = RULES.state(conn)
        active = state["active"]["number"] if state["active"] else None
        skus = self.skus(conn)
        readiness = {}
        if active is not None:
            vid = next(v["id"] for v in versions if v["number"] == active)
            settings, rules, _ = self._content(conn, vid)
            readiness = self._readiness(settings, rules, register, [s["code"] for s in skus])
        return {
            "active": state["active"],
            "scheduled": state["scheduled"],
            "latest": versions[0]["number"] if versions else None,
            "versions": [{"number": v["number"], "createdAt": audit.iso(v["created_at"]), "reason": v["reason"],
                          "basedOn": v["based_on"], "registerVersion": v["register_version"],
                          "status": state["status"](v["number"])} for v in versions],
            "activations": state["activations"],
            "skus": [{"code": s["code"], "name": s["name"]} for s in skus],
            "readiness": readiness,
        }

    def version(self, conn, number: int, register) -> dict:
        v = conn.execute("""SELECT v.id, v.number, v.created_at, v.reason, b.number AS based_on, r.number AS register_version
                              FROM config_version v JOIN register_version r ON r.id = v.register_version_id
                              LEFT JOIN config_version b ON b.id = v.based_on_id WHERE v.number = %s""", (number,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such rules version", f"Rules v{number} doesn't exist")
        settings, rules, intact = self._content(conn, v["id"])
        return {"number": v["number"], "createdAt": audit.iso(v["created_at"]), "reason": v["reason"],
                "basedOn": v["based_on"], "registerVersion": v["register_version"], "intact": intact,
                "settings": camel(settings), "rules": camel(rules),
                "readiness": self._readiness(settings, rules, register, [s["code"] for s in self.skus(conn)])}

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
        """What a save would say, without saving: problems and SKU readiness."""
        settings, rules = self._from_body(body)
        skus = [s["code"] for s in self.skus(conn)]
        return {"errors": rules_mod.validate(rules, settings["defaults"], register.zones, set(skus)),
                "readiness": self._readiness(settings, rules, register, skus)}

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
        errors = rules_mod.validate(rules, settings["defaults"], register.zones, {s["code"] for s in self.skus(conn)})
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
            cur.executemany(f"""INSERT INTO sku_parameter_rule (config_version_id, sku_code, parameter_id, zone_id, {', '.join(FIELDS)})
                                VALUES (%s, %s, %s, %s{', %s' * len(FIELDS)})""",
                            [(vid, r["sku"], r["parameter_id"], r["zone_id"], *(r[f] for f in FIELDS)) for r in keep])
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

    # -- SKUs ------------------------------------------------------------------------------

    def add_sku(self, conn, body) -> None:
        code, name = body.code.strip(), body.name.strip()
        try:
            conn.execute("INSERT INTO sku (code, name) VALUES (%s, %s)", (code, name))
        except pg_errors.UniqueViolation:
            raise Problem(409, "sku-exists", "That SKU is already in the list", f"SKU {code} exists") from None
        audit.record(conn, "sku.add", f"SKU {code} added: {name}", body.reason)
        conn.commit()

    def rename_sku(self, conn, code: str, body) -> None:
        old = conn.execute("SELECT name FROM sku WHERE code = %s FOR UPDATE", (code,)).fetchone()
        if old is None:
            raise Problem(404, "not-found", "No such SKU", f"SKU {code} isn't in the list")
        conn.execute("UPDATE sku SET name = %s, updated_at = clock_timestamp() WHERE code = %s", (body.name.strip(), code))
        audit.record(conn, "sku.rename", f"SKU {code} renamed from {old['name']} to {body.name.strip()}", body.reason)
        conn.commit()

    def delete_sku(self, conn, code: str, reason: str) -> None:
        used = conn.execute("""SELECT min(v.number) AS n FROM sku_parameter_rule r
                                 JOIN config_version v ON v.id = r.config_version_id WHERE r.sku_code = %s""", (code,)).fetchone()
        if used["n"] is not None:
            raise Problem(409, "sku-in-use", "The SKU is used by saved rules",
                          f"Rules v{used['n']} has rules for SKU {code}, and saved versions never change, so it stays in the list.")
        if conn.execute("DELETE FROM sku WHERE code = %s RETURNING code", (code,)).fetchone() is None:
            raise Problem(404, "not-found", "No such SKU", f"SKU {code} isn't in the list")
        audit.record(conn, "sku.delete", f"SKU {code} removed", reason)
        conn.commit()
