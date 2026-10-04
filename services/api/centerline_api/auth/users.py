"""Accounts (ADR-0016, IAM-01…04): created, changed and reset by an Administrator.

A new account and a reset get a temporary password, shown once to the Administrator, that
works for 24 h and must be changed at the first sign-in. Accounts are disabled, never deleted:
the audit log and the events name them. Changing an account's roles, disabling it or resetting
its password signs it out everywhere at once (guide §12). The last active Administrator can't
be disabled or lose the role, so the system is never left without one.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Literal
from uuid import UUID

import psycopg
from centerline_common.db import uuid7
from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator

from ..config import audit
from ..config.models import _Camel
from ..database import connect
from ..problems import Problem
from . import sessions
from .deps import ADMIN_ONLY
from .sessions import ADMINISTRATOR, OPERATOR, Principal, roles_text

router = APIRouter(prefix="/api/v1/users", tags=["accounts"], dependencies=[ADMIN_ONLY])

Role = Literal["OPERATOR", "MANAGER", "ADMINISTRATOR"]
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _roles(v: list[str]) -> list[str]:
    roles = sorted(set(v))
    if not roles:
        raise ValueError("Give the account at least one role")
    if OPERATOR in roles and len(roles) > 1:
        raise ValueError("An Operator account has only that role: its sessions follow other rules (SES-01…04)")
    return roles


def _optional(v: str | None) -> str | None:
    return (v or "").strip() or None


class AccountFields(_Camel):
    display_name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(None, max_length=254)
    employee_id: str | None = Field(None, max_length=64)
    roles: list[Role] = Field(min_length=1, max_length=3)
    reason: str = Field("", max_length=500)

    _roles = field_validator("roles")(_roles)

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Enter the person's name")
        return v.strip()

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        v = _optional(v)
        if v is not None and not EMAIL.match(v):
            raise ValueError("Enter an email address like name@example.com")
        return v

    @field_validator("employee_id")
    @classmethod
    def _employee(cls, v: str | None) -> str | None:
        return _optional(v)


class AccountIn(AccountFields):
    username: str = Field(min_length=2, max_length=64)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME.match(v):
            raise ValueError("Use 2–64 letters, digits, dots, dashes or underscores, starting with a letter or digit")
        return v


class AccountUpdateIn(AccountFields):
    active: bool


class ReasonIn(_Camel):
    reason: str = Field("", max_length=500)


COLUMNS = """u.id, u.username, u.display_name, u.email, u.employee_id, u.roles, u.active, u.must_change, u.temp_expires_at,
             u.locked_until, u.last_sign_in_at, u.created_at,
             (SELECT count(*) FROM app_session s WHERE s.user_id = u.id) AS sessions"""


def _public(r: dict) -> dict:
    return {"id": str(r["id"]), "username": r["username"], "displayName": r["display_name"], "email": r["email"],
            "employeeId": r["employee_id"], "roles": sorted(r["roles"]), "active": r["active"],
            "mustChange": r["must_change"], "temporaryExpiresAt": audit.iso(r["temp_expires_at"]),
            "lockedUntil": audit.iso(r["locked_until"]), "lastSignInAt": audit.iso(r["last_sign_in_at"]),
            "createdAt": audit.iso(r["created_at"]), "sessions": r["sessions"]}


def _get(conn, user_id, lock: bool = False) -> dict:
    r = conn.execute(f"SELECT {COLUMNS} FROM app_user u WHERE u.id = %s" + (" FOR UPDATE" if lock else ""),
                     (user_id,)).fetchone()
    if r is None:
        raise Problem(404, "not-found", "No such account", f"Account {user_id} doesn't exist")
    return r


def _taken(e: psycopg.errors.UniqueViolation, fields: dict[str, str | None]) -> Problem:
    """Which of the form's names another account already uses: the error names the value, not the field."""
    detail = (e.diag.message_detail or "").lower()
    used = [f for f, v in fields.items() if v and f"=({v.strip().lower()})" in detail]
    return Problem(409, "name-taken", "That name is already used",
                   "Another account already signs in with this username, email or Employee ID.",
                   errors=[{"field": f, "message": "Already used by another account"} for f in used])


def _admins_left(conn, excluding) -> int:
    return conn.execute("""SELECT count(*) AS n FROM app_user
                            WHERE active AND %s = ANY (roles) AND id <> %s""", (ADMINISTRATOR, excluding)).fetchone()["n"]


def create(conn, passwords, s, fields: dict, reason: str, actor: str | None = None) -> tuple[dict, str]:
    """A new account with a temporary password; returns the account and that password. Doesn't commit."""
    temporary = passwords.temporary()
    now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    uid = uuid7()
    try:
        with conn.transaction():
            conn.execute("""INSERT INTO app_user (id, username, display_name, email, employee_id, roles, password_hash,
                                                  must_change, temp_expires_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s)""",
                         (uid, fields["username"], fields["display_name"], fields.get("email"), fields.get("employee_id"),
                          fields["roles"], passwords.hash(temporary), now + timedelta(hours=s.temporary_password_h)))
    except psycopg.errors.UniqueViolation as e:
        raise _taken(e, {"username": fields["username"], "email": fields.get("email"),
                         "employeeId": fields.get("employee_id")}) from None
    audit.record(conn, "account.create", f"Account {fields['username']} ({fields['display_name']}) created as "
                 f"{roles_text(fields['roles'])}", reason, details={"account": str(uid)}, actor=actor)
    return _get(conn, uid), temporary


@router.get("", summary="Every account, with its roles, state and open sessions")
def list_accounts(conn=Depends(connect)) -> dict:
    rows = conn.execute(f"SELECT {COLUMNS} FROM app_user u ORDER BY u.active DESC, lower(u.display_name)").fetchall()
    return {"accounts": [_public(r) for r in rows]}


@router.post("", status_code=201, summary="Create an account; its temporary password is shown only in this answer")
def create_account(body: AccountIn, request: Request, conn=Depends(connect)) -> dict:
    s = request.app.state.settings.auth
    account, temporary = create(conn, request.app.state.passwords, s,
                                body.model_dump(include={"username", "display_name", "email", "employee_id", "roles"}),
                                body.reason)
    conn.commit()
    return {"account": _public(account), "temporaryPassword": temporary,
            "temporaryExpiresAt": audit.iso(account["temp_expires_at"])}


@router.put("/{user_id}", summary="Change an account; new roles or disabling sign it out everywhere")
def update_account(user_id: UUID, body: AccountUpdateIn, request: Request, conn=Depends(connect)) -> dict:
    me: Principal = request.state.principal
    old = _get(conn, user_id, lock=True)
    roles = sorted(body.roles)
    losing_admin = old["active"] and ADMINISTRATOR in old["roles"] and (not body.active or ADMINISTRATOR not in roles)
    if losing_admin:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('centerline.accounts'))")
        if _admins_left(conn, user_id) == 0:
            raise Problem(409, "last-administrator", "The last Administrator stays",
                          "Make another account an Administrator first: someone must be able to manage the accounts.")
    try:
        with conn.transaction():
            conn.execute("""UPDATE app_user SET display_name = %s, email = %s, employee_id = %s, roles = %s, active = %s,
                                                updated_at = clock_timestamp() WHERE id = %s""",
                         (body.display_name, body.email, body.employee_id, roles, body.active, user_id))
    except psycopg.errors.UniqueViolation as e:
        raise _taken(e, {"email": body.email, "employeeId": body.employee_id}) from None
    changes = []
    if sorted(old["roles"]) != roles:
        changes.append(f"roles {roles_text(old['roles'])} → {roles_text(roles)}")
    if old["active"] != body.active:
        changes.append("enabled" if body.active else "disabled")
    for label, key, new in (("name", "display_name", body.display_name), ("email", "email", body.email),
                            ("Employee ID", "employee_id", body.employee_id)):
        if old[key] != new:
            changes.append(f"{label} {old[key] or '—'} → {new or '—'}")
    ended = 0
    if sorted(old["roles"]) != roles or (old["active"] and not body.active):
        # Takes effect at once (guide §12); an Administrator changing their own roles signs out too
        ended = sessions.end_sessions(conn, user_id)
    if changes:
        audit.record(conn, "account.update", f"Account {old['username']}: " + "; ".join(changes)
                     + (f"; {ended} session(s) signed out" if ended else ""), body.reason, details={"account": str(user_id)})
    conn.commit()
    return {"account": _public(_get(conn, user_id)), "signedOut": ended, "you": str(user_id) == str(me.user_id)}


def issue_temporary(conn, passwords, s, user_id, reason: str, actor: str | None = None) -> tuple[dict, str]:
    """Reset to a temporary password: unlocks the account and signs it out everywhere. Doesn't commit."""
    old = _get(conn, user_id, lock=True)
    temporary = passwords.temporary()
    conn.execute("""UPDATE app_user SET password_hash = %s, must_change = true, temp_expires_at = clock_timestamp() + %s,
                                        failed_count = 0, locked_until = NULL, updated_at = clock_timestamp()
                     WHERE id = %s""", (passwords.hash(temporary), timedelta(hours=s.temporary_password_h), user_id))
    ended = sessions.end_sessions(conn, user_id)
    audit.record(conn, "account.temporary_password", f"Account {old['username']}: temporary password issued"
                 + (f"; {ended} session(s) signed out" if ended else ""), reason, details={"account": str(user_id)},
                 actor=actor)
    return _get(conn, user_id), temporary


@router.post("/{user_id}/temporary-password", summary="Reset to a temporary password, shown only in this answer")
def reset_password(user_id: UUID, body: ReasonIn, request: Request, conn=Depends(connect)) -> dict:
    account, temporary = issue_temporary(conn, request.app.state.passwords, request.app.state.settings.auth, user_id,
                                         body.reason)
    conn.commit()
    return {"account": _public(account), "temporaryPassword": temporary,
            "temporaryExpiresAt": audit.iso(account["temp_expires_at"])}
