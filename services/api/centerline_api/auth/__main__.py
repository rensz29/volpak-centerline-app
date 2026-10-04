"""Accounts from the server's command line (ADR-0016): the first Administrator, and a way back in.

    cd services
    PYTHONPATH=common:api .venv/bin/python -m centerline_api.auth create-admin \\
        --username szyrelle --name "Szyrelle" --out ../config/secrets/first-admin-password
    PYTHONPATH=common:api .venv/bin/python -m centerline_api.auth temporary-password --username szyrelle

Each prints a temporary password (it works for 24 h and must be changed at the first sign-in),
or with --out writes it to that file, created readable by you only, so it needn't appear on
screen. The database comes from the api config (CENTERLINE_API_CONFIG, else services/api/
config.json); the migrations run first. Every use is audited as done on the server.
Only someone with a shell on the server can run this, which is the point.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from centerline_common import migrate
from centerline_common.db import DatabaseUnavailable
from pydantic import ValidationError

from ..database import migrate_as_owner
from ..problems import Problem
from ..settings import load_settings
from . import users
from .passwords import Passwords
from .sessions import ADMINISTRATOR

ACTOR = "server command line"


def _secret_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m centerline_api.auth", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create-admin", help="create an Administrator account (Manager too, unless --roles says otherwise)")
    c.add_argument("--username", required=True)
    c.add_argument("--name", required=True, help="the person's name as the pages show it")
    c.add_argument("--email")
    c.add_argument("--employee-id")
    c.add_argument("--roles", default="MANAGER,ADMINISTRATOR", help="comma-separated; must include ADMINISTRATOR")
    c.add_argument("--reason", default="First Administrator, created on the server")
    c.add_argument("--out", type=Path, help="write the temporary password to this file (0600) instead of printing it")
    t = sub.add_parser("temporary-password", help="issue a temporary password, e.g. for a locked-out Administrator")
    t.add_argument("--username", required=True)
    t.add_argument("--reason", default="Temporary password issued on the server")
    t.add_argument("--out", type=Path, help="write the temporary password to this file (0600) instead of printing it")
    args = ap.parse_args(argv)

    settings = load_settings()
    passwords = Passwords(settings.auth)
    try:
        migrate_as_owner(settings)  # the owner migrates; the accounts are written as the services' role (ADR-0020)
        with settings.database.connect() as conn:
            if settings.migrate_database is None:
                migrate.apply(conn)
                conn.commit()
            if args.command == "create-admin":
                roles = sorted({r.strip().upper() for r in args.roles.split(",") if r.strip()})
                if ADMINISTRATOR not in roles:
                    print("--roles must include ADMINISTRATOR", file=sys.stderr)
                    return 2
                body = users.AccountIn(username=args.username, display_name=args.name, email=args.email,
                                       employee_id=args.employee_id, roles=roles, reason=args.reason)
                account, temporary = users.create(
                    conn, passwords, settings.auth,
                    body.model_dump(include={"username", "display_name", "email", "employee_id", "roles"}),
                    body.reason, actor=ACTOR)
            else:
                row = conn.execute("SELECT id FROM app_user WHERE username = %s", (args.username.strip().lower(),)).fetchone()
                if row is None:
                    print(f"No account has the username {args.username}", file=sys.stderr)
                    return 1
                account, temporary = users.issue_temporary(conn, passwords, settings.auth, row["id"], args.reason,
                                                           actor=ACTOR)
            conn.commit()
    except ValidationError as e:
        for err in e.errors():
            print(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}", file=sys.stderr)
        return 2
    except Problem as e:
        print(f"{e.title}: {e.detail}", file=sys.stderr)
        return 1
    except DatabaseUnavailable as e:
        print(f"The database isn't reachable: {e}", file=sys.stderr)
        return 1

    until = account["temp_expires_at"].astimezone().strftime("%Y-%m-%d %H:%M")
    if args.out:
        _secret_file(args.out, temporary)
        print(f"{account['username']}: temporary password written to {args.out} (valid until {until}). "
              "Sign in, choose your own password, then delete the file.")
    else:
        print(f"{account['username']}: temporary password {temporary} (valid until {until}); "
              "it must be changed at the first sign-in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
