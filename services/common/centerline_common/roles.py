"""The services' database role, centerline_app (ADR-0020): its password, from a secret file.

    cd services && PYTHONPATH=common .venv/bin/python -m centerline_common.roles

Migration 0006 creates the role and its grants. This sets its password from
config/secrets/postgres-app-password (0600), making the file with a random password first if
it's missing, and does so again whenever it runs, so the role and the file agree. It connects
as the database owner (config/secrets/postgres-password). The password is never printed.
"""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import replace
from pathlib import Path

from psycopg import sql

from .db import REPO, DatabaseConfig

APP_ROLE = "centerline_app"
APP_PASSWORD = REPO / "config" / "secrets" / "postgres-app-password"


def app_database(owner: DatabaseConfig, password_file: Path = APP_PASSWORD) -> DatabaseConfig:
    """The same database, as the services' role."""
    return replace(owner, user=APP_ROLE, password_file=password_file)


def ensure_password(owner_conn, password_file: Path = APP_PASSWORD) -> None:
    """Give centerline_app the password in the file, writing a random one there first if there's none."""
    if not password_file.exists():
        password_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(32) + "\n")
    password = password_file.read_text(encoding="utf-8").strip()
    owner_conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(APP_ROLE), sql.Literal(password)))
    owner_conn.commit()


def main() -> int:
    owner = DatabaseConfig()
    with owner.connect() as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)).fetchone()
        if not exists:
            print(f"{APP_ROLE} doesn't exist yet: start the api once (it applies migration 0006), then run this again",
                  file=sys.stderr)
            return 1
        ensure_password(conn)
    print(f"{APP_ROLE}: password set from {APP_PASSWORD} (0600). Point the api and monitor-core at it: "
          f'"user": "{APP_ROLE}", "password_file": "…/config/secrets/postgres-app-password".')
    return 0


if __name__ == "__main__":
    sys.exit(main())
