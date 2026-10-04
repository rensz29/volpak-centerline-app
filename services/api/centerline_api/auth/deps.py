"""Who may call what (ADR-0016): FastAPI dependencies that every router uses, and the CSRF guard.

Every endpoint needs a signed-in account except signing in and `GET /api/v1/health/live`.
The roles the owner decided (O-13):

| Area | Read | Change |
|---|---|---|
| Digital Centerline, events | every role | acknowledging a Critical: Manager |
| Analytics | Manager, Administrator | (read-only) |
| Configuration: Rules tab | Manager, Administrator | Manager |
| Configuration: Connections, Tags, Mappings | Manager, Administrator | Administrator |
| Accounts, detailed health | Administrator | Administrator |

A temporary password must be changed before anything else works (IAM-03).
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from ..database import connect
from ..problems import MEDIA_TYPE, Problem
from ..settings import AuthSettings
from . import sessions
from .sessions import ADMINISTRATOR, MANAGER, OPERATOR, Principal

CSRF_HEADER = "X-Centerline-CSRF"  # browsers can't add it to a cross-site request without the api's consent
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip(request: Request, s: AuthSettings) -> str:
    """The browser's address. Behind the proxy, the proxy's own X-Forwarded-For entry (the last one) counts."""
    peer = request.client.host if request.client else "unknown"
    if peer in s.trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            return forwarded
    return peer


def session_any(request: Request, conn=Depends(connect)) -> Principal:
    """Any signed-in session, even one that must change its temporary password first."""
    principal = sessions.lookup(conn, request.app.state.settings.auth, request.cookies.get(sessions.COOKIE),
                                activity=request.method in UNSAFE)
    request.state.principal = principal
    return principal


def current_session(principal: Principal = Depends(session_any)) -> Principal:
    if principal.must_change:
        raise Problem(403, "password-change-required", "Change your password first",
                      "You signed in with a temporary password: choose your own before anything else.")
    return principal


def require(*roles: str):
    def check(principal: Principal = Depends(current_session)) -> Principal:
        if not principal.roles & set(roles):
            raise Problem(403, "not-allowed", "Your role can't do this",
                          f"This needs the {' or '.join(sessions.ROLE_NAMES[r] for r in roles)} role.")
        return principal

    check.roles = frozenset(roles)  # read by the access test
    return check


SIGNED_IN = Depends(current_session)
PRIVILEGED = Depends(require(MANAGER, ADMINISTRATOR))
MANAGER_ONLY = Depends(require(MANAGER))
ADMIN_ONLY = Depends(require(ADMINISTRATOR))
OPERATOR_ONLY = Depends(require(OPERATOR))  # the reason workflow (ADR-0025)
EVERY_ROLE = frozenset({OPERATOR, MANAGER, ADMINISTRATOR})


class CsrfGuard:
    """Refuse a state-changing api call that doesn't carry the CSRF header (on top of SameSite=Strict cookies)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] in UNSAFE and scope["path"].startswith("/api/")
                and (dict(scope["headers"]).get(CSRF_HEADER.lower().encode()) != b"1")):
            body = Problem(403, "csrf", "Request refused", f"State-changing requests need the {CSRF_HEADER}: 1 header.",
                           ).body(scope["path"])
            await JSONResponse(body, status_code=403, media_type=MEDIA_TYPE)(scope, receive, send)
            return
        await self.app(scope, receive, send)
