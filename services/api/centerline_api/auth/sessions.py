"""Signing in and sessions (ADR-0016, ADR-0025; IAM-02…04, SES-01…04).

Sessions are rows in PostgreSQL (DD-06). The browser holds a random token in an HttpOnly
cookie; the database keeps only its SHA-256, so reading the table gives no one a session.
Deleting a row signs that browser out at its next request, which is how a role change, a
disabled account or a password reset takes effect at once.

- **Operators** (SES-01, SES-04): one session for the line, only at an operator workstation,
  no inactivity limit. Signing in again at the same workstation replaces its session; another
  workstation may take it over once it has had no heartbeat for 5 min. The session ends with
  the shift it was opened in (SES-03): the next request or sign-in after 06:00, 14:00 or 22:00
  ends it, so a session left over from the last shift blocks nobody.
- **Managers and Administrators** (SES-01, SES-02): at most 10 sessions, each ended after
  15 min without the person's own activity. Background refreshes don't count as activity.
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from centerline_common import shifts
from centerline_common.db import uuid7

from ..config import audit
from ..problems import Problem
from ..settings import AuthSettings
from .passwords import Passwords

COOKIE = "centerline_session"
OPERATOR, MANAGER, ADMINISTRATOR = "OPERATOR", "MANAGER", "ADMINISTRATOR"
ROLE_NAMES = {OPERATOR: "Operator", MANAGER: "Manager", ADMINISTRATOR: "Administrator"}
SEEN_EVERY_S = 30  # the heartbeat is written at most this often
SHIFT_WARNING_S = 300  # an operator is warned 5 min before the shift ends (SES-03)


@dataclass(frozen=True)
class Principal:
    """Who is making this request."""

    user_id: UUID
    username: str
    display_name: str
    roles: frozenset[str]
    must_change: bool
    session_id: UUID
    kind: str  # operator | privileged
    workstation: str | None
    created_at: datetime
    last_active_at: datetime


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def same_address(a: str, b: str) -> bool:
    try:
        x, y = ipaddress.ip_address(a), ipaddress.ip_address(b)
    except ValueError:
        return a == b
    x = x.ipv4_mapped or x if isinstance(x, ipaddress.IPv6Address) else x
    y = y.ipv4_mapped or y if isinstance(y, ipaddress.IPv6Address) else y
    return x == y


def roles_text(roles) -> str:
    return " and ".join(ROLE_NAMES[r] for r in (OPERATOR, MANAGER, ADMINISTRATOR) if r in roles)


def _now(conn) -> datetime:
    return conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def _minutes(td: timedelta) -> int:
    return max(1, math.ceil(td.total_seconds() / 60))


def shift_view(t: datetime) -> dict:
    sh = shifts.shift_at(t)
    return {"code": sh.code, "label": shifts.label(sh), "startsAt": audit.iso(sh.starts_at), "endsAt": audit.iso(sh.ends_at)}


def describe(conn, principal: Principal, s: AuthSettings) -> dict:
    """The session as the page needs it: who, which rules, the inactivity limit and the shift, on the server's clock.

    An operator's session belongs to the shift it was opened in and ends with it (SES-03); `shift`
    is that shift. For Managers and Administrators it's the shift now, for information."""
    privileged = principal.kind == "privileged"
    now = _now(conn)
    return {"user": {"id": str(principal.user_id), "username": principal.username, "displayName": principal.display_name,
                     "roles": sorted(principal.roles), "mustChange": principal.must_change},
            "session": {"kind": principal.kind, "workstation": principal.workstation,
                        "signedInAt": audit.iso(principal.created_at), "lastActiveAt": audit.iso(principal.last_active_at),
                        "idleLimitS": round(s.privileged_idle_min * 60) if privileged else None,
                        "idleWarningS": round(s.idle_warning_min * 60) if privileged else None,
                        "endsWithShift": not privileged, "shiftWarningS": SHIFT_WARNING_S},
            "shift": shift_view(now if privileged else principal.created_at),
            "serverTime": audit.iso(now)}


def _shift_over(created_at: datetime, now: datetime) -> bool:
    return now >= shifts.shift_at(created_at).ends_at


def _end_with_shift(conn, session_id, username: str) -> None:
    """An operator's session ends with the shift it was opened in (SES-03): the next request or sign-in ends it."""
    conn.execute("DELETE FROM app_session WHERE id = %s", (session_id,))
    audit.record(conn, "auth.shift_over", f"{username} signed out: the shift ended", actor=username)


def sign_in(conn, s: AuthSettings, passwords: Passwords, name: str, password: str, ip: str, user_agent: str | None,
            takeover: bool = False) -> tuple[str, Principal]:
    """Check the name and password and open a session; returns the cookie's token. Commits."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('centerline.sessions'))")  # one sign-in at a time
    now = _now(conn)
    u = conn.execute("""SELECT u.* FROM app_user_login l JOIN app_user u ON u.id = l.user_id
                         WHERE l.name = %s FOR UPDATE OF u""", (name.strip().lower(),)).fetchone()
    if u is None:
        passwords.verify(None, password)
        # The typed name isn't kept: people sometimes type their password into it
        audit.record(conn, "auth.sign_in_failed", "Sign-in failed: no account has that name", details={"ip": ip})
        conn.commit()
        raise Problem(401, "sign-in-failed", "Wrong name or password", "Check the name and the password, then try again.")
    if u["locked_until"] is not None and u["locked_until"] > now:
        conn.commit()
        raise Problem(423, "account-locked", "Account locked",
                      f"Too many failed sign-ins. Try again in {_minutes(u['locked_until'] - now)} min, "
                      "or ask an Administrator for a temporary password.")
    if not passwords.verify(u["password_hash"], password):
        failed = u["failed_count"] + 1
        locked = failed >= s.lockout_failures
        conn.execute("UPDATE app_user SET failed_count = %s, locked_until = %s, updated_at = %s WHERE id = %s",
                     (0 if locked else failed, now + timedelta(minutes=s.lockout_min) if locked else None, now, u["id"]))
        audit.record(conn, "auth.sign_in_failed",
                     f"Sign-in failed for {u['username']}: wrong password"
                     + (f"; locked for {s.lockout_min:g} min after {failed} tries" if locked else ""),
                     details={"ip": ip, "failures": failed})
        conn.commit()
        if locked:
            raise Problem(423, "account-locked", "Account locked",
                          f"{failed} failed sign-ins in a row: the account is locked for {s.lockout_min:g} min.")
        raise Problem(401, "sign-in-failed", "Wrong name or password", "Check the name and the password, then try again.")
    if not u["active"]:
        conn.commit()
        raise Problem(403, "account-disabled", "Account disabled", "Ask an Administrator to enable it again.")
    if u["must_change"] and u["temp_expires_at"] is not None and u["temp_expires_at"] <= now:
        conn.commit()
        raise Problem(401, "temporary-password-expired", "Temporary password expired",
                      f"A temporary password works for {s.temporary_password_h:g} h. Ask an Administrator for a new one.")

    roles = frozenset(u["roles"])
    kind = "operator" if OPERATOR in roles else "privileged"
    workstation = None
    if kind == "operator":
        workstation = next((n for n, address in s.operator_workstations if same_address(address, ip)), None)
        if workstation is None:
            conn.commit()
            raise Problem(403, "not-an-operator-workstation", "Operators sign in at the operator workstation",
                          f"This browser ({ip}) isn't the primary or backup operator workstation (SES-04).")
        other = conn.execute("""SELECT s.id, s.ip, s.workstation, s.created_at, s.last_seen_at, u.username
                                  FROM app_session s JOIN app_user u ON u.id = s.user_id
                                 WHERE s.kind = 'operator'""").fetchone()
        if other is not None and _shift_over(other["created_at"], now):  # ended with its shift, if nothing looked since
            _end_with_shift(conn, other["id"], other["username"])
            other = None
        if other is not None:
            quiet = now - other["last_seen_at"]
            here = same_address(other["ip"], ip)
            stale = quiet >= timedelta(minutes=s.operator_takeover_min)
            if not here and not (stale and takeover):
                conn.commit()
                raise Problem(409, "operator-signed-in", "An operator is signed in at another workstation",
                              f"{other['username']} is signed in at {other['workstation']}, last seen "
                              f"{round(quiet.total_seconds())} s ago. "
                              + ("It has had no heartbeat for 5 min, so you can take it over."
                                 if stale else f"It can be taken over after {s.operator_takeover_min:g} min without a heartbeat."),
                              takeoverAvailable=stale, workstation=other["workstation"], operator=other["username"],
                              lastSeen=audit.iso(other["last_seen_at"]))
            conn.execute("DELETE FROM app_session WHERE id = %s", (other["id"],))
            if here:
                audit.record(conn, "auth.session_replaced", f"{u['username']} signed in at {workstation}, "
                             f"replacing the session of {other['username']}", details={"ip": ip}, actor=u["username"])
            else:
                audit.record(conn, "auth.takeover", f"{u['username']} took over the operator session of "
                             f"{other['username']} at {other['workstation']} (no heartbeat for {_minutes(quiet)} min)",
                             details={"ip": ip, "from": other["workstation"], "to": workstation}, actor=u["username"])
    else:
        conn.execute("DELETE FROM app_session WHERE kind = 'privileged' AND last_active_at < %s",
                     (now - timedelta(minutes=s.privileged_idle_min),))
        open_ = conn.execute("SELECT count(*) AS n FROM app_session WHERE kind = 'privileged'").fetchone()["n"]
        if open_ >= s.privileged_sessions_max:
            conn.commit()
            raise Problem(409, "too-many-sessions", "Too many Manager and Administrator sessions",
                          f"{open_} are open, the most allowed (SES-01). Sign out somewhere else, or wait until one "
                          f"ends after {s.privileged_idle_min:g} min without activity.")

    token = secrets.token_urlsafe(32)
    sid = uuid7()
    row = conn.execute("""INSERT INTO app_session (id, token_sha256, user_id, kind, ip, workstation, user_agent)
                          VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING created_at, last_active_at""",
                       (sid, token_hash(token), u["id"], kind, ip, workstation, (user_agent or "")[:300] or None)).fetchone()
    rehash = passwords.hash(password) if passwords.needs_rehash(u["password_hash"]) else u["password_hash"]
    conn.execute("""UPDATE app_user SET failed_count = 0, locked_until = NULL, last_sign_in_at = %s, password_hash = %s,
                                        updated_at = %s WHERE id = %s""", (now, rehash, now, u["id"]))
    audit.record(conn, "auth.sign_in", f"{u['username']} signed in ({roles_text(roles)}) from {ip}"
                 + (f" at {workstation}" if workstation else ""), details={"ip": ip, "session": str(sid)}, actor=u["username"])
    conn.commit()
    return token, Principal(u["id"], u["username"], u["display_name"], roles, u["must_change"], sid, kind, workstation,
                            row["created_at"], row["last_active_at"])


def lookup(conn, s: AuthSettings, token: str | None, activity: bool) -> Principal:
    """The session behind a cookie, or 401. Writes the heartbeat and, for a person's own action, the activity. Commits."""
    if not token:
        raise Problem(401, "not-signed-in", "Sign in to continue", "This needs a signed-in account.")
    r = conn.execute("""SELECT s.id, s.kind, s.workstation, s.created_at, s.last_seen_at, s.last_active_at,
                               u.id AS user_id, u.username, u.display_name, u.roles, u.active, u.must_change
                          FROM app_session s JOIN app_user u ON u.id = s.user_id
                         WHERE s.token_sha256 = %s""", (token_hash(token),)).fetchone()
    if r is None:
        raise Problem(401, "session-ended", "Your session has ended", "Sign in again.")
    now = _now(conn)
    idle = timedelta(minutes=s.privileged_idle_min)
    if r["kind"] == "operator" and _shift_over(r["created_at"], now):  # the shift handover (SES-03, ADR-0025)
        _end_with_shift(conn, r["id"], r["username"])
        conn.commit()
        end = shifts.shift_at(r["created_at"]).ends_at.astimezone(shifts.MANILA)
        raise Problem(401, "shift-over", f"Your shift ended at {end:%H:%M}",
                      "The next shift's operator signs in now. Anything you hadn't sent was cleared.")
    if not r["active"] or (r["kind"] == "privileged" and now - r["last_active_at"] > idle):
        conn.execute("DELETE FROM app_session WHERE id = %s", (r["id"],))
        conn.commit()
        if not r["active"]:
            raise Problem(401, "session-ended", "Your session has ended", "The account has been disabled.")
        raise Problem(401, "session-expired", "Signed out after inactivity",
                      f"Manager and Administrator sessions end after {s.privileged_idle_min:g} min without activity (SES-02).")
    last_active = now if activity else r["last_active_at"]
    if activity or (now - r["last_seen_at"]).total_seconds() >= SEEN_EVERY_S:
        conn.execute("UPDATE app_session SET last_seen_at = %s, last_active_at = %s WHERE id = %s", (now, last_active, r["id"]))
    # The audit log names whoever is signed in on this connection (config.audit.record)
    conn.execute("SELECT set_config('centerline.actor', %s, false)", (r["username"],))
    conn.commit()
    return Principal(r["user_id"], r["username"], r["display_name"], frozenset(r["roles"]), r["must_change"], r["id"],
                     r["kind"], r["workstation"], r["created_at"], last_active)


def sign_out(conn, principal: Principal) -> None:
    conn.execute("DELETE FROM app_session WHERE id = %s", (principal.session_id,))
    audit.record(conn, "auth.sign_out", f"{principal.username} signed out")
    conn.commit()


def end_sessions(conn, user_id, keep: UUID | None = None) -> int:
    """Sign an account out everywhere (a role change, disablement or reset), optionally keeping one session."""
    rows = conn.execute("DELETE FROM app_session WHERE user_id = %s AND id IS DISTINCT FROM %s RETURNING id",
                        (user_id, keep)).fetchall()
    return len(rows)


def change_password(conn, s: AuthSettings, passwords: Passwords, principal: Principal, current: str, new: str) -> None:
    """The person's own change; ends their other sessions. Commits."""
    u = conn.execute("SELECT id, password_hash, must_change FROM app_user WHERE id = %s FOR UPDATE",
                     (principal.user_id,)).fetchone()
    if not passwords.verify(u["password_hash"], current):
        raise Problem(403, "wrong-password", "Your current password isn't right", "Type the password you signed in with.",
                      errors=[{"field": "current", "message": "This isn't your current password"}])
    previous = [r["hash"] for r in conn.execute(
        "SELECT hash FROM app_user_password WHERE user_id = %s ORDER BY set_at DESC LIMIT %s",
        (u["id"], s.password_history)).fetchall()]
    problems = passwords.problems(new, u["password_hash"], previous)
    if problems:
        raise Problem(422, "weak-password", "Choose another password", "; ".join(problems),
                      errors=[{"field": "new", "message": p} for p in problems])
    now = _now(conn)
    hashed = passwords.hash(new)
    conn.execute("""UPDATE app_user SET password_hash = %s, must_change = false, temp_expires_at = NULL, updated_at = %s
                     WHERE id = %s""", (hashed, now, u["id"]))
    conn.execute("INSERT INTO app_user_password (user_id, set_at, hash) VALUES (%s, %s, %s)", (u["id"], now, hashed))
    ended = end_sessions(conn, u["id"], keep=principal.session_id)
    audit.record(conn, "auth.password_changed", f"{principal.username} changed their password"
                 + ("" if not u["must_change"] else ", replacing the temporary one")
                 + (f"; {ended} other session(s) signed out" if ended else ""))
    conn.commit()
