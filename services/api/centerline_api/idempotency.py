"""Idempotency-Key on every POST that creates a record (SDD §11, ADR-0028).

The key is claimed before the request runs and the answer is kept with it, for 24 h. The same key again, from the
same session and for the same request, gets the kept answer instead of a second record; for another request it's
refused. Handlers commit their own transactions, so the claim is a separate one: an answer of 500 or more, or an
exception, releases it so the request can be tried again.

Exempt: signing in and out, and the POSTs that only read or check (Analytics queries, connection tests, draft
checks, the mapping import and broker discovery). Without a session nothing is claimed: the handler answers 401.
"""

from __future__ import annotations

import hashlib
import logging
import re

import psycopg
from centerline_common.db import DatabaseUnavailable
from starlette.concurrency import run_in_threadpool
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse, Response

from .auth.sessions import COOKIE, token_hash
from .problems import MEDIA_TYPE, Problem

log = logging.getLogger("centerline.api.idempotency")

HEADER = "Idempotency-Key"
KEEP_H = 24
ABANDONED_MIN = 5  # a claim with no answer this old: the request was cut off, and its outcome is unknown
EXEMPT = re.compile(r"/api/v1/(auth/.*|analytics/query|config/historian/latest"
                    r"|config/connections/(historian/test|mqtt/test|notifications/email-test)"
                    r"|config/(mappings/|routing/|analytics-ranges/)?versions/check|config/mappings/(import|discover))")
# Their answer holds a temporary password, which mustn't be kept: a repeat is refused, not replayed
NO_REPLAY = re.compile(r"/api/v1/users(/[^/]+/temporary-password)?")
_VALID = re.compile(r"[\x21-\x7e]{1,255}")


def _problem(path: str, status: int, slug: str, title: str, detail: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(Problem(status, slug, title, detail).body(path), status_code=status, media_type=MEDIA_TYPE,
                        headers=headers)


class Idempotency:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/api/") \
                or EXEMPT.fullmatch(scope["path"]):
            await self.app(scope, receive, send)
            return
        app, path = scope["app"], scope["path"]
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        token = cookie_parser(headers.get("cookie", "")).get(COOKIE)
        if not token or not app.state.db_ready:
            await self.app(scope, receive, send)  # not signed in (401), or no database yet (503)
            return
        key = headers.get(HEADER.lower())
        if key is None:
            await _problem(path, 400, "idempotency-key-missing", f"{HEADER} needed",
                           f"A request that saves something needs an {HEADER} header: a new random value for each "
                           "action, and the same one when retrying it.")(scope, receive, send)
            return
        if not _VALID.fullmatch(key):
            await _problem(path, 400, "idempotency-key-invalid", f"{HEADER} not valid",
                           f"The {HEADER} must be 1 to 255 visible ASCII characters.")(scope, receive, send)
            return

        body, more = b"", True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
        fingerprint = hashlib.sha256(b"\n".join([b"POST", path.encode(), scope.get("query_string", b""), body])).hexdigest()
        session, db = token_hash(token), app.state.settings.database

        try:
            found = await run_in_threadpool(_claim, db, session, key, fingerprint)
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            log.warning("idempotency keys unavailable, request let through: %s", e)
            found = None
        if found is not None:
            await _answer_repeat(path, found, fingerprint)(scope, receive, send)
            return

        delivered = False

        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        status, content_type, parts = None, None, []

        async def capture(message):
            nonlocal status, content_type
            if message["type"] == "http.response.start":
                status = message["status"]
                content_type = next((v.decode("latin-1") for k, v in message.get("headers", []) if k.lower() == b"content-type"), None)
            elif message["type"] == "http.response.body":
                parts.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_body, capture)
        except BaseException:
            await run_in_threadpool(_release, db, session, key)
            raise
        if status is None or status >= 500:
            await run_in_threadpool(_release, db, session, key)
        else:
            kept = None if NO_REPLAY.fullmatch(path) else b"".join(parts)
            await run_in_threadpool(_complete, db, session, key, status, content_type, kept)


def _answer_repeat(path: str, found: dict, fingerprint: str) -> Response:
    if found["status"] is None:  # the first request hasn't answered: nothing to compare with yet
        if found["abandoned"]:
            return _problem(path, 409, "idempotency-key-interrupted", "Outcome unknown",
                            f"The first request with this {HEADER} was cut off, so whether it went through is unknown. "
                            "Check, then use a new key if it's still needed.")
        return _problem(path, 409, "idempotency-key-in-use", "Still being processed",
                        f"The first request with this {HEADER} is still running. Try again in a moment.",
                        headers={"Retry-After": "1"})
    if found["fingerprint"] != fingerprint:
        return _problem(path, 422, "idempotency-key-reused", f"{HEADER} already used",
                        f"This {HEADER} was already used for a different request. Use a new one for a new action.")
    if found["body"] is None:
        return _problem(path, 409, "idempotency-key-done", "Already done",
                        "This request was already done. Its answer held a temporary password, which isn't kept: "
                        "issue a new one if it was lost.")
    return Response(bytes(found["body"]), status_code=found["status"], media_type=found["content_type"],
                    headers={"Idempotent-Replayed": "true"})


def _claim(db, session: str, key: str, fingerprint: str) -> dict | None:
    """None when this request holds the key now; else what the earlier one with it left."""
    with db.connect(autocommit=True) as conn:
        conn.execute(f"DELETE FROM idempotency_key WHERE created_at < now() - interval '{KEEP_H} hours'")
        for _ in range(2):  # the earlier request may release the key between the two statements
            if conn.execute("""INSERT INTO idempotency_key (session_hash, key, fingerprint) VALUES (%s, %s, %s)
                               ON CONFLICT DO NOTHING RETURNING 1""", (session, key, fingerprint)).fetchone():
                return None
            found = conn.execute(f"""SELECT fingerprint, status, content_type, body,
                                            created_at < now() - interval '{ABANDONED_MIN} minutes' AS abandoned
                                       FROM idempotency_key WHERE session_hash = %s AND key = %s""", (session, key)).fetchone()
            if found:
                return found
        return None


def _complete(db, session: str, key: str, status: int, content_type: str | None, body: bytes | None) -> None:
    try:
        with db.connect(autocommit=True) as conn:
            conn.execute("UPDATE idempotency_key SET status = %s, content_type = %s, body = %s WHERE session_hash = %s AND key = %s",
                         (status, content_type, body, session, key))
    except (DatabaseUnavailable, psycopg.OperationalError) as e:
        log.warning("couldn't keep the answer for an idempotency key: %s", e)


def _release(db, session: str, key: str) -> None:
    try:
        with db.connect(autocommit=True) as conn:
            conn.execute("DELETE FROM idempotency_key WHERE session_hash = %s AND key = %s AND status IS NULL", (session, key))
    except (DatabaseUnavailable, psycopg.OperationalError) as e:
        log.warning("couldn't release an idempotency key: %s", e)
