"""Analytics-valid ranges on the Configuration page (ANA-10/11, ADR-0029).

An Administrator uploads the CSV. It's accepted or rejected as a whole (analytics/ranges.py), and an accepted file is
a version, kept exactly as uploaded with its SHA-256, the reason and who saved it. Versions take effect through
activations like the rules, mappings and routing (OPC-07): now or at a set time; an older one again is a rollback.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

from centerline_common.db import uuid7

from ..analytics import ranges as ranges_mod
from ..problems import Problem
from . import audit
from .store import invalid
from .versioning import Versioned, reason_errors

RANGES = Versioned("Analytics ranges", "analytics_ranges", "analytics_range_version", "analytics_range_activation",
                   "analytics_range_version_id", "active_analytics_range_version", "centerline.analytics_ranges")
MAX_BYTES = 64 * 1024  # eleven rows; anything near this isn't the ranges file


def _decode(body) -> bytes:
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise invalid("The file can't be read", [{"field": "contentBase64", "message": "Not base64: upload the file again"}]) from None
    if len(data) > MAX_BYTES:
        raise invalid("The file is too large", [{"field": "contentBase64", "message": f"Larger than {MAX_BYTES // 1024} KiB: is it the ranges file?"}])
    return data


def _rows_view(register, rows: list[dict]) -> list[dict]:
    names = {p["id"]: p.get("name") for p in register.parameters}
    return [{"parameterId": r["parameter_id"], "parameterName": names.get(r["parameter_id"]), "unit": r["unit"],
             "validMin": r["valid_min"], "validMax": r["valid_max"]} for r in rows]


class RangesStore:
    @staticmethod
    def _rows(conn, vid) -> list[dict]:
        return conn.execute("""SELECT parameter_id, unit, valid_min, valid_max FROM analytics_range
                                WHERE version_id = %s ORDER BY parameter_id""", (vid,)).fetchall()

    def overview(self, conn, register) -> dict:
        versions = conn.execute("""SELECT v.number, v.created_at, v.created_by, v.reason, v.source, v.sha256,
                                          r.number AS register_version
                                     FROM analytics_range_version v
                                     JOIN register_version r ON r.id = v.register_version_id
                                    ORDER BY v.number DESC""").fetchall()
        state = RANGES.state(conn)
        in_effect = ranges_mod.active(conn, register)
        active = conn.execute("SELECT id FROM analytics_range_version WHERE id = active_analytics_range_version()").fetchone()
        return {
            "active": state["active"],
            "scheduled": state["scheduled"],
            "latest": versions[0]["number"] if versions else None,
            "versions": [{"number": v["number"], "createdAt": audit.iso(v["created_at"]), "by": v["created_by"],
                          "reason": v["reason"], "source": v["source"], "sha256": v["sha256"],
                          "registerVersion": v["register_version"], "status": state["status"](v["number"])}
                         for v in versions],
            "activations": state["activations"],
            "rows": _rows_view(register, self._rows(conn, active["id"])) if active else None,
            "problems": in_effect.problems,
            "parameters": [{"parameterId": pid, "unit": unit} for pid, unit in register.units().items()],
            "registerVersion": register.version,
        }

    def version(self, conn, number: int, register) -> dict:
        v = conn.execute("""SELECT v.id, v.number, v.created_at, v.created_by, v.reason, v.source, v.sha256, v.original,
                                   r.number AS register_version
                              FROM analytics_range_version v JOIN register_version r ON r.id = v.register_version_id
                             WHERE v.number = %s""", (number,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such Analytics ranges version", f"Analytics ranges v{number} doesn't exist")
        rows = self._rows(conn, v["id"])
        fits = ranges_mod.parse_ranges(bytes(v["original"]), register, v["source"])
        return {"number": v["number"], "createdAt": audit.iso(v["created_at"]), "by": v["created_by"], "reason": v["reason"],
                "source": v["source"], "sha256": v["sha256"], "registerVersion": v["register_version"],
                "intact": v["sha256"] == hashlib.sha256(bytes(v["original"])).hexdigest(),
                "rows": _rows_view(register, rows), "problems": fits.problems}

    @staticmethod
    def original(conn, number: int) -> tuple[str, bytes]:
        v = conn.execute("SELECT source, original FROM analytics_range_version WHERE number = %s", (number,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such Analytics ranges version", f"Analytics ranges v{number} doesn't exist")
        return v["source"], bytes(v["original"])

    @staticmethod
    def check(body, register) -> dict:
        result = ranges_mod.parse_ranges(_decode(body), register, body.source)
        return {"problems": result.problems, "sha256": result.ranges.sha256 if result.ranges else None,
                "rows": [{"parameterId": pid, "unit": result.ranges.units[pid], "validMin": lo, "validMax": hi}
                         for pid, (lo, hi) in result.ranges.ranges.items()] if result.ranges else None}

    def create(self, conn, body, register) -> int:
        """Save the uploaded file as a new version (and optionally activate it); commits. Returns its number."""
        data = _decode(body)
        RANGES.lock_now(conn)
        latest = conn.execute("SELECT number FROM analytics_range_version ORDER BY number DESC LIMIT 1").fetchone()
        latest_n = latest["number"] if latest else None
        if body.expected_latest != latest_n:
            raise Problem(409, "version-conflict", "The Analytics ranges changed meanwhile",
                          f"Analytics ranges v{latest_n} was saved after you started. Reload the page and upload again.",
                          currentVersion=latest_n)
        parsed = ranges_mod.parse_ranges(data, register, body.source)
        errors = [{"field": "contentBase64", "message": p} for p in parsed.problems] + reason_errors(body.reason)
        if not body.source.strip():
            errors.append({"field": "source", "message": "The file's name"})
        now = RANGES.now(conn)
        if body.activate == "at" and (body.activate_at is None or body.activate_at <= now):
            errors.append({"field": "activateAt", "message": "Pick a time in the future"})
        if errors:
            raise invalid("The Analytics ranges can't be saved: the whole file is rejected", errors)

        reg = conn.execute("SELECT id FROM register_version ORDER BY seq DESC LIMIT 1").fetchone()
        number, vid, ranges = (latest_n or 0) + 1, uuid7(), parsed.ranges
        conn.execute(f"""INSERT INTO analytics_range_version (id, number, register_version_id, source, original, sha256,
                                                              reason, created_by)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, {audit.ACTOR})""",
                     (vid, number, reg["id"], body.source.strip(), data, ranges.sha256, body.reason.strip()))
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO analytics_range (version_id, parameter_id, unit, valid_min, valid_max)
                               VALUES (%s, %s, %s, %s, %s)""",
                            [(vid, pid, ranges.units[pid] or None, lo, hi) for pid, (lo, hi) in ranges.ranges.items()])
        audit.record(conn, "analytics_ranges.version",
                     f"Analytics ranges v{number} saved from {body.source.strip()}: {len(ranges.ranges)} parameters",
                     body.reason, {"version": number, "source": body.source.strip(), "sha256": ranges.sha256})
        if body.activate != "no":
            RANGES.record(conn, vid, number, body.activate_at if body.activate == "at" else None, body.reason, now)
        conn.commit()
        return number

    def activate(self, conn, number: int, body, register) -> None:
        def fits(conn, vid) -> list[dict]:
            v = conn.execute("SELECT source, original, sha256 FROM analytics_range_version WHERE id = %s", (vid,)).fetchone()
            if v["sha256"] != hashlib.sha256(bytes(v["original"])).hexdigest():
                return [{"field": "at", "message": f"Analytics ranges v{number} was changed outside Centerline; don't use it"}]
            return [{"field": "at", "message": p} for p in ranges_mod.parse_ranges(bytes(v["original"]), register, v["source"]).problems]

        RANGES.activate(conn, number, body, precheck=fits)

    @staticmethod
    def cancel(conn, activation_id, body) -> None:
        RANGES.cancel(conn, activation_id, body)
