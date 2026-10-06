"""Idempotency-Key on the POSTs that create a record (SDD §11, ADR-0028)."""

from __future__ import annotations

import pytest
from centerline_api.auth.sessions import COOKIE, token_hash
from centerline_api.idempotency import EXEMPT

from .conftest import add_account, new_client, sign_in

TEST_MESSAGE = {"channel": "email", "target": "lead@plant.test", "note": "Checking the relay"}
# The POSTs that save nothing, and signing in and out: every other POST needs a key
SAVE_NOTHING = {"/api/v1/auth/login", "/api/v1/auth/takeover", "/api/v1/auth/activity", "/api/v1/auth/password",
                "/api/v1/auth/logout", "/api/v1/analytics/query", "/api/v1/config/historian/latest",
                "/api/v1/config/connections/historian/test", "/api/v1/config/connections/mqtt/test",
                "/api/v1/config/connections/notifications/email-test", "/api/v1/config/versions/check",
                "/api/v1/config/mappings/versions/check", "/api/v1/config/routing/versions/check",
                "/api/v1/config/analytics-ranges/versions/check",
                "/api/v1/config/mappings/import", "/api/v1/config/mappings/discover"}


def _count(database, sql: str) -> int:
    with database.connect() as conn:
        return conn.execute(sql).fetchone()["n"]


def _session(client) -> str:
    return token_hash(client.cookies[COOKIE])


def test_every_post_needs_a_key_except_those_that_save_nothing(make_client):
    posts = {path for path, ops in make_client(roles=None).app.openapi()["paths"].items() if "post" in ops}
    assert {p for p in posts if EXEMPT.fullmatch(p)} == SAVE_NOTHING
    assert len(posts - SAVE_NOTHING) == 25  # a new POST route is a decision: add it to SAVE_NOTHING only if it saves nothing


def test_a_creating_post_needs_a_key_and_a_read_only_one_doesnt(make_client):
    c = make_client()
    r = c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": None})
    assert (r.status_code, r.json()["type"]) == (400, "/problems/idempotency-key-missing")
    assert c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "two words"}).status_code == 400
    assert c.post("/api/v1/config/historian/latest", json={"tags": []}, headers={"Idempotency-Key": None}).status_code != 400
    signed_out = new_client(c.app)  # not signed in: the sign-in check answers first
    assert signed_out.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": None}).status_code == 401


def test_a_repeat_gets_the_first_answer_and_makes_nothing_more(make_client, database):
    c = make_client()
    first = c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "k-1"})
    again = c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "k-1"})
    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json() and again.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert _count(database, "SELECT count(*) AS n FROM notification WHERE kind = 'test'") == 1
    # the same key for another request is refused; a new key makes a new message
    other = c.post("/api/v1/notifications/test", json={**TEST_MESSAGE, "note": "Again"}, headers={"Idempotency-Key": "k-1"})
    assert (other.status_code, other.json()["type"]) == (422, "/problems/idempotency-key-reused")
    assert c.post("/api/v1/notifications/test", json=TEST_MESSAGE).status_code == 201
    assert _count(database, "SELECT count(*) AS n FROM notification WHERE kind = 'test'") == 2


def test_a_key_is_one_sessions_own(make_client, database):
    c = make_client()
    other = new_client(c.app)
    sign_in(other, add_account(c.app, database))
    assert c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "shared"}).status_code == 201
    r = other.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "shared"})
    assert r.status_code == 201 and "Idempotent-Replayed" not in r.headers  # not someone else's answer
    assert _count(database, "SELECT count(*) AS n FROM notification WHERE kind = 'test'") == 2


def test_a_temporary_password_is_never_kept_so_a_repeat_is_refused(make_client, database, owner):
    c = make_client()
    body = {"username": "cy", "displayName": "Cy", "roles": ["MANAGER"]}
    made = c.post("/api/v1/users", json=body, headers={"Idempotency-Key": "new-cy"})
    assert made.status_code == 201 and made.json()["temporaryPassword"]
    again = c.post("/api/v1/users", json=body, headers={"Idempotency-Key": "new-cy"})
    assert (again.status_code, again.json()["type"]) == (409, "/problems/idempotency-key-done")
    assert _count(database, "SELECT count(*) AS n FROM app_user WHERE username = 'cy'") == 1
    with owner.connect() as conn:
        row = conn.execute("SELECT status, body FROM idempotency_key WHERE key = 'new-cy'").fetchone()
    assert (row["status"], row["body"]) == (201, None)


def test_a_request_still_running_or_cut_off_and_keys_past_24_h(make_client, owner):
    c = make_client()
    session = _session(c)
    with owner.connect() as conn:
        conn.execute("INSERT INTO idempotency_key (session_hash, key, fingerprint) VALUES (%s, 'busy', 'x')", (session,))
        conn.execute("""INSERT INTO idempotency_key (session_hash, key, fingerprint, created_at)
                        VALUES (%s, 'lost', 'x', now() - interval '10 minutes')""", (session,))
        conn.execute("""INSERT INTO idempotency_key (session_hash, key, fingerprint, created_at, status, body)
                        VALUES (%s, 'old', 'x', now() - interval '25 hours', 201, '\\x7b7d')""", (session,))
        conn.commit()
    busy = c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "busy"})
    assert (busy.status_code, busy.json()["type"], busy.headers["Retry-After"]) == (409, "/problems/idempotency-key-in-use", "1")
    lost = c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "lost"})
    assert (lost.status_code, lost.json()["type"]) == (409, "/problems/idempotency-key-interrupted")
    # a day later the key is gone and can be used again
    assert c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "old"}).status_code == 201


def test_an_answer_that_failed_on_the_server_releases_the_key(make_client, database, monkeypatch):
    c = make_client()
    from centerline_api.notifications import router as notifications
    from centerline_api.problems import Problem

    def crash(*args, **kwargs):
        raise RuntimeError("the outbox write blew up")

    def unavailable(*args, **kwargs):
        raise Problem(503, "database-unavailable", "The Centerline database isn't reachable", "gone for a moment")

    monkeypatch.setattr(notifications, "add_delivery", crash)
    with pytest.raises(RuntimeError):
        c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "retry-me"})
    monkeypatch.setattr(notifications, "add_delivery", unavailable)
    assert c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "retry-me"}).status_code == 503
    monkeypatch.undo()
    assert c.post("/api/v1/notifications/test", json=TEST_MESSAGE, headers={"Idempotency-Key": "retry-me"}).status_code == 201
    assert _count(database, "SELECT count(*) AS n FROM notification WHERE kind = 'test'") == 1
