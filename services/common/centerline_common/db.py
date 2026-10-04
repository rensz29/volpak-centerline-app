"""PostgreSQL access (ADR-0012): connection settings, connections and UUIDv7 keys.

The password is read from a file on every connect, never from configuration or
the environment. Connections use READ COMMITTED, which the audit chain relies on.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REPO = Path(__file__).resolve().parents[3]


class DatabaseUnavailable(Exception):
    """The database can't be reached, or the password file is missing."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Defaults match the development database in deploy/dev/compose.yaml."""

    host: str = "127.0.0.1"
    port: int = 55432
    dbname: str = "centerline"
    user: str = "centerline"
    password_file: Path | None = REPO / "config" / "secrets" / "postgres-password"
    connect_timeout_s: int = 3

    @classmethod
    def from_dict(cls, raw: dict, base: Path) -> DatabaseConfig:
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        if known.get("password_file"):
            known["password_file"] = (base / os.path.expanduser(known["password_file"])).resolve()
        return cls(**known)

    def describe(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"

    def connect(self, autocommit: bool = False) -> psycopg.Connection:
        password = None
        if self.password_file:
            try:
                password = Path(self.password_file).read_text(encoding="utf-8").strip()
            except OSError as e:
                raise DatabaseUnavailable(f"can't read the database password file: {e}") from None
        try:
            return psycopg.connect(host=self.host, port=self.port, dbname=self.dbname, user=self.user,
                                   password=password, connect_timeout=self.connect_timeout_s,
                                   autocommit=autocommit, row_factory=dict_row, application_name="centerline")
        except psycopg.OperationalError as e:
            first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            raise DatabaseUnavailable(f"{self.describe()}: {first}") from None


def uuid7() -> uuid.UUID:
    """A time-ordered UUID (RFC 9562 version 7): 48 bits of Unix milliseconds, then random bits."""
    value = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10), "big")
    value = value & ~(0xF << 76) | 0x7 << 76  # version 7
    value = value & ~(0x3 << 62) | 0x2 << 62  # RFC variant
    return uuid.UUID(int=value)
