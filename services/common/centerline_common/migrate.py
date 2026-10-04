"""Apply db/migrations/*.sql in order, once each (ADR-0012).

Each file runs in its own transaction and is recorded in schema_migration with
its SHA-256. A file changed after it was applied is refused: add a new one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import psycopg

from .db import REPO

MIGRATIONS = REPO / "db" / "migrations"
LOCK = 7243101  # pg_advisory_lock key: one migrator at a time


class MigrationError(Exception):
    pass


def apply(conn: psycopg.Connection, directory: Path = MIGRATIONS) -> list[str]:
    """Apply pending migrations; returns the versions applied now."""
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK,))  # session lock: survives the commits below
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migration (
                        version    text PRIMARY KEY,
                        sha256     text NOT NULL,
                        applied_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
    conn.commit()
    applied = []
    try:
        done = {r["version"]: r["sha256"] for r in conn.execute("SELECT version, sha256 FROM schema_migration")}
        conn.commit()
        for path in sorted(directory.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if path.stem in done:
                if done[path.stem] != digest:
                    raise MigrationError(f"{path.name} changed after it was applied; add a new migration instead")
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migration (version, sha256) VALUES (%s, %s)", (path.stem, digest))
            applied.append(path.stem)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        conn.commit()
    return applied


def status(conn: psycopg.Connection, directory: Path = MIGRATIONS) -> dict:
    """Applied and pending migration versions."""
    exists = conn.execute("SELECT to_regclass('schema_migration') IS NOT NULL AS ok").fetchone()["ok"]
    applied = [r["version"] for r in conn.execute("SELECT version FROM schema_migration ORDER BY version")] if exists else []
    conn.commit()
    return {"applied": applied, "pending": [p.stem for p in sorted(directory.glob("*.sql")) if p.stem not in applied]}
