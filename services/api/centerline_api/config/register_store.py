"""The parameter register in PostgreSQL (ADR-0007, ADR-0012): each save is a new version.

config/parameter-register.json seeds the database on first start. After that the
database is the source, and the file is rewritten after every save for the
Phase 0 tools and for git. A file edited by hand is never overwritten silently:
it's copied to history/ first, and the page says its edits aren't in use.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from centerline_common import register as register_mod
from centerline_common.db import uuid7
from centerline_common.register import Register
from psycopg.types.json import Jsonb

from ..problems import Problem
from . import audit
from .store import invalid, write_atomic

MANILA = timezone(timedelta(hours=8))
ZONE_ID = re.compile(r"^[A-Z0-9_]{1,16}$")
KINDS = ("setpoint", "actual")
LOCK = "centerline.register"


def content_sha(raw: dict) -> str:
    text = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RegisterStore:
    def __init__(self, export_path: Path):
        self.export_path = export_path

    # -- reading ------------------------------------------------------------------

    def current(self, conn) -> dict:
        row = conn.execute("SELECT id, number, content, sha256 FROM register_version ORDER BY seq DESC LIMIT 1").fetchone()
        if row is None:
            raise Problem(503, "register-missing", "The register isn't in the database yet",
                          "Restart the api so it can import config/parameter-register.json.")
        return row

    def raw(self, conn) -> dict:
        return self.current(conn)["content"]

    def load(self, conn) -> Register:
        return register_mod.parse(self.raw(conn))

    def _known(self, conn, sha: str) -> bool:
        return conn.execute("SELECT 1 FROM register_version WHERE sha256 = %s", (sha,)).fetchone() is not None

    def _file(self) -> dict | None:
        try:
            return json.loads(self.export_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    # -- start-up -------------------------------------------------------------------

    def seed(self, conn) -> str | None:
        """First start: the register file becomes the first version in the database."""
        if conn.execute("SELECT 1 FROM register_version LIMIT 1").fetchone():
            return None
        raw = self._file()
        if raw is None:
            raise FileNotFoundError(f"can't seed the register: {self.export_path} is missing or not JSON")
        number = raw.get("version") or self.next_number(conn)
        raw["version"] = number
        self._insert(conn, raw, f"Imported from {self.export_path.name}")
        audit.record(conn, "register.import", f"Register {number} imported from {self.export_path.name}",
                     details={"to": number})
        return number

    def drop_sku(self, conn) -> str | None:
        """A register saved before ADR-0027 names a SKU tag (none was ever set). The next version leaves it out,
        and the file follows; returns that version's number, or None when there's nothing to drop. Commits."""
        cur = self.current(conn)
        if "sku" not in cur["content"]:
            return None
        raw = deepcopy(cur["content"])
        raw.pop("sku")
        raw["version"] = self.next_number(conn)
        self._insert(conn, raw, "No SKU tag: Centerline doesn't use one (ADR-0027)")
        audit.record(conn, "register.version", f"Register {raw['version']}: the unused SKU entry removed (ADR-0027)",
                     details={"from": cur["number"], "to": raw["version"]})
        conn.commit()
        self.export(conn, raw)
        return raw["version"]

    def file_status(self, conn) -> str | None:
        """None when the file matches the database; otherwise why it doesn't. Refreshes an out-of-date export."""
        cur = self.current(conn)
        raw = self._file()
        if raw is not None and content_sha(raw) == cur["sha256"]:
            return None
        if raw is None or self._known(conn, content_sha(raw)):
            self.export(conn, cur["content"])  # missing, or an older export: bring it up to date
            return None
        return (f"{self.export_path.name} has hand edits that aren't in the database, so they aren't used. "
                "Make the change on the Tags tab; the next save keeps a copy of the edited file in history/.")

    # -- writing --------------------------------------------------------------------

    def next_number(self, conn) -> str:
        """<Manila date>.<n>, one more than any number used today. Numbers are never reused."""
        today = datetime.now(MANILA).date().isoformat()
        rows = conn.execute("SELECT number FROM register_version WHERE number LIKE %s", (f"{today}.%",)).fetchall()
        used = [int(m.group(1)) for r in rows if (m := re.fullmatch(rf"{today}\.(\d+)", r["number"]))]
        return f"{today}.{max(used, default=0) + 1}"

    def _insert(self, conn, raw: dict, reason: str) -> None:
        conn.execute(f"""INSERT INTO register_version (id, number, content, sha256, reason, created_by)
                         VALUES (%s, %s, %s, %s, %s, {audit.ACTOR})""",
                     (uuid7(), raw["version"], Jsonb(raw), content_sha(raw), reason))

    def export(self, conn, raw: dict) -> None:
        """Rewrite the file for the tools, keeping a copy first if it holds edits the database doesn't have."""
        current = self._file()
        if self.export_path.exists() and (current is None or not self._known(conn, content_sha(current))):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            keep = self.export_path.parent / "history" / f"{self.export_path.stem}.hand-edited.{stamp}.json"
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.export_path, keep)
        write_atomic(self.export_path, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")

    def update_parameter(self, conn, pid: str, body, known_tags: set[str]) -> Register:
        """Validate and save one parameter as a new register version; commits, then rewrites the file."""
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK,))
        cur = self.current(conn)
        raw, current = deepcopy(cur["content"]), cur["number"]
        if body.base_version != current:
            raise Problem(409, "version-conflict", "The register changed meanwhile",
                          f"The register is now version {current}; reload the page and try again.",
                          currentVersion=current)
        param = next((p for p in raw["parameters"] if p["id"] == pid), None)
        if param is None:
            raise Problem(404, "not-found", "No such parameter", f"{pid} isn't in the register")
        ns = raw["namespace"]
        used_elsewhere = {z.get(k): f"{p['id']} · {z.get('name')} {k}"
                          for p in raw["parameters"] if p["id"] != pid
                          for z in p.get("zones", []) for k in KINDS if z.get(k)}
        errors: list[dict] = []
        zones, ids, names, own_tags = [], set(), set(), {}
        for i, z in enumerate(body.zones):
            zid, name = z.id.strip().upper(), z.name.strip()
            if not ZONE_ID.match(zid):
                errors.append({"field": f"zones[{i}].id", "message": f"Zone ID {z.id!r}: use 1–16 capital letters, digits or _"})
            elif zid in ids:
                errors.append({"field": f"zones[{i}].id", "message": f"Zone ID {zid} appears twice"})
            if not name:
                errors.append({"field": f"zones[{i}].name", "message": "Every zone needs a name"})
            elif name.lower() in names:
                errors.append({"field": f"zones[{i}].name", "message": f"Zone name {name!r} appears twice"})
            ids.add(zid)
            names.add(name.lower())
            entry = {"id": zid, "name": name, "setpoint": None, "actual": None}
            for kind in KINDS:
                tag = (getattr(z, kind) or "").strip()
                if not tag:
                    continue
                rel = tag[len(ns) + 1:] if tag.startswith(ns + ".") else tag
                field = f"zones[{i}].{kind}"
                if f"{ns}.{rel}" not in known_tags:
                    errors.append({"field": field, "message": f"{rel} isn't a tag in Timebase under this machine"})
                elif rel in used_elsewhere:
                    errors.append({"field": field, "message": f"{rel} is already used by {used_elsewhere[rel]}"})
                elif rel in own_tags:
                    errors.append({"field": field, "message": f"{rel} is already used by {own_tags[rel]}"})
                own_tags[rel] = f"{name} {kind}"
                entry[kind] = rel
            zones.append(entry)
        if body.status == "active" and (not zones or any(not z["setpoint"] or not z["actual"] for z in zones)):
            errors.append({"field": "status", "message": "Monitoring needs at least one zone, each with a setpoint and an actual tag"})
        if body.status == "analytics_only" and (not zones or any(not z["actual"] for z in zones)):
            errors.append({"field": "status", "message": "Analytics needs at least one zone, each with an actual tag"})
        if len(body.reason.strip()) < 3:
            errors.append({"field": "reason", "message": "Say why you're changing this (at least 3 characters)"})
        if errors:
            raise invalid("The parameter can't be saved", errors)

        before = deepcopy(param)
        param["status"] = body.status
        param["zones"] = zones
        used = {z[k] for z in zones for k in KINDS if z[k]}
        if param.get("candidate_tags"):
            param["candidate_tags"] = [t for t in param["candidate_tags"] if t not in used]
        raw["version"] = self.next_number(conn)
        self._insert(conn, raw, body.reason.strip())
        audit.record(conn, "register.parameter", f"{pid} {param['name']}: {len(zones)} zone(s), status {body.status}",
                     body.reason, {"from": current, "to": raw["version"], "before": before, "after": param})
        conn.commit()
        self.export(conn, raw)
        return register_mod.parse(raw)
