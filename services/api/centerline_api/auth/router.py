"""Signing in and out (ADR-0016). The session cookie is HttpOnly, Secure and SameSite=Strict (guide §12)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from centerline_common import workflow

from ..config.models import _Camel
from ..database import connect
from . import sessions
from .deps import client_ip, session_any
from .sessions import Principal

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(_Camel):
    name: str = Field(min_length=1, max_length=254, description="Username, email or Employee ID (any case)")
    password: str = Field(min_length=1, max_length=1024)


class PasswordIn(_Camel):
    current: str = Field(min_length=1, max_length=1024)
    new: str = Field(min_length=1, max_length=1024)


def _cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(sessions.COOKIE, token, httponly=True, secure=request.app.state.settings.auth.secure_cookie,
                        samesite="strict", path="/api")


def _login(body: LoginIn, request: Request, response: Response, conn, takeover: bool) -> dict:
    s = request.app.state.settings.auth
    token, principal = sessions.sign_in(conn, s, request.app.state.passwords, body.name, body.password,
                                        client_ip(request, s), request.headers.get("user-agent"), takeover=takeover)
    _cookie(request, response, token)
    if principal.kind == "operator":
        # A new shift's operator: a reason request for every HMI mismatch still open (WF-01, ADR-0025)
        workflow.activate_shift(conn, principal.created_at)
        conn.commit()
    return sessions.describe(conn, principal, s)


@router.post("/login", summary="Sign in with a username, email or Employee ID")
def login(body: LoginIn, request: Request, response: Response, conn=Depends(connect)) -> dict:
    return _login(body, request, response, conn, takeover=False)


@router.post("/takeover", summary="Sign in at an operator workstation, taking over a session with no heartbeat for 5 min")
def takeover(body: LoginIn, request: Request, response: Response, conn=Depends(connect)) -> dict:
    return _login(body, request, response, conn, takeover=True)


@router.get("/session", summary="Who is signed in, and the session's rules; doesn't count as activity")
def session(request: Request, principal: Principal = Depends(session_any), conn=Depends(connect)) -> dict:
    return sessions.describe(conn, principal, request.app.state.settings.auth)


@router.post("/activity", summary="The person is still here: restarts the 15 min inactivity limit")
def activity(request: Request, principal: Principal = Depends(session_any), conn=Depends(connect)) -> dict:
    return sessions.describe(conn, principal, request.app.state.settings.auth)


@router.post("/password", summary="Change your own password; your other sessions are signed out")
def password(body: PasswordIn, request: Request, principal: Principal = Depends(session_any),
             conn=Depends(connect)) -> dict:
    s = request.app.state.settings.auth
    sessions.change_password(conn, s, request.app.state.passwords, principal, body.current, body.new)
    return sessions.describe(conn, sessions.lookup(conn, s, request.cookies.get(sessions.COOKIE), activity=True), s)


@router.post("/logout", summary="Sign out")
def logout(request: Request, response: Response, principal: Principal = Depends(session_any),
           conn=Depends(connect)) -> dict:
    sessions.sign_out(conn, principal)
    response.delete_cookie(sessions.COOKIE, path="/api", httponly=True, samesite="strict",
                           secure=request.app.state.settings.auth.secure_cookie)
    return {"signedOut": True}
