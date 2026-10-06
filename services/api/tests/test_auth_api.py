"""Signing in and sessions (ADR-0016; IAM-02…04, SES-01…04)."""

from __future__ import annotations

import time
from dataclasses import replace

from .conftest import FAST_AUTH, PASSWORD, add_account, new_client, sign_in

OPERATOR = ["OPERATOR"]
DESKS = (("Line desk", "10.0.0.5"), ("Backup desk", "10.0.0.6"))


def audit(database, action: str) -> list[dict]:
    with database.connect() as conn:
        return conn.execute("SELECT actor, summary, details FROM audit_log WHERE action = %s ORDER BY seq", (action,)).fetchall()


def test_sign_in_with_the_username_email_or_employee_id_in_any_case(make_client, database):
    c = make_client(roles=None)
    add_account(c.app, database, ["MANAGER"], username="ana", email="Ana.Cruz@Plant.example", employee_id="E-1042",
                display_name="Ana Cruz")
    for name in ("ANA", "ana.cruz@plant.EXAMPLE", "e-1042"):
        body = sign_in(new_client(c.app), name)
        assert body["user"]["username"] == "ana" and body["user"]["roles"] == ["MANAGER"]
    r = new_client(c.app).post("/api/v1/auth/login", json={"name": "ana", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert all(f in cookie for f in ("httponly", "secure", "samesite=strict", "path=/api"))
    assert "Ana Cruz" not in r.headers["set-cookie"]  # the cookie is only a random token
    assert body["session"] == {**body["session"], "kind": "privileged", "idleLimitS": 900, "idleWarningS": 780}


def test_five_wrong_passwords_lock_the_account_for_15_minutes(make_client, database):
    c = make_client(roles=None, auth=replace(FAST_AUTH, lockout_min=0.01))  # 0.6 s
    add_account(c.app, database, ["MANAGER"], username="ben")
    for _ in range(4):
        r = c.post("/api/v1/auth/login", json={"name": "ben", "password": "wrong password here"})
        assert r.status_code == 401 and r.json()["type"] == "/problems/sign-in-failed"
    r = c.post("/api/v1/auth/login", json={"name": "ben", "password": "wrong password here"})
    assert r.status_code == 423 and "locked" in r.json()["detail"]
    r = c.post("/api/v1/auth/login", json={"name": "ben", "password": PASSWORD})
    assert r.status_code == 423  # even with the right password, until the lock ends
    time.sleep(0.8)
    sign_in(c, "ben")
    failed = audit(database, "auth.sign_in_failed")
    assert len(failed) == 5 and "locked" in failed[-1]["summary"]
    assert audit(database, "auth.sign_in")[-1]["actor"] == "ben"


def test_an_unknown_name_fails_like_a_wrong_password_and_isnt_recorded(make_client, database):
    c = make_client(roles=None)
    r = c.post("/api/v1/auth/login", json={"name": "my-secret-password", "password": "x"})
    assert r.status_code == 401 and r.json()["title"] == "Wrong name or password"
    (entry,) = audit(database, "auth.sign_in_failed")
    assert "my-secret-password" not in str(entry)  # people type passwords into the name field


def test_a_temporary_password_must_be_changed_first_and_a_new_one_must_be_strong(make_client):
    admin = make_client()
    made = admin.post("/api/v1/users", json={"username": "cy", "displayName": "Cy", "roles": ["MANAGER"]}).json()
    temporary = made["temporaryPassword"]
    c = new_client(admin.app)
    assert sign_in(c, "cy", temporary)["user"]["mustChange"] is True
    r = c.get("/api/v1/monitoring/live")
    assert r.status_code == 403 and r.json()["type"] == "/problems/password-change-required"
    for new, why in (("short one", "at least 12"), ("password1234", "breaches"), (temporary, "not the one you have now")):
        r = c.post("/api/v1/auth/password", json={"current": temporary, "new": new})
        assert r.status_code == 422 and why in r.json()["detail"], new
    r = c.post("/api/v1/auth/password", json={"current": "not it", "new": "a long and fresh passphrase"})
    assert r.status_code == 403 and r.json()["errors"][0]["field"] == "current"
    r = c.post("/api/v1/auth/password", json={"current": temporary, "new": "a long and fresh passphrase"})
    assert r.status_code == 200 and r.json()["user"]["mustChange"] is False
    assert c.get("/api/v1/monitoring/live").status_code == 200


def test_a_temporary_password_stops_working_after_24_hours(make_client, database):
    admin = make_client()
    temporary = admin.post("/api/v1/users", json={"username": "dee", "displayName": "Dee", "roles": ["MANAGER"]}).json()[
        "temporaryPassword"]
    with database.connect() as conn:
        conn.execute("UPDATE app_user SET temp_expires_at = now() - interval '1 min' WHERE username = 'dee'")
        conn.commit()
    r = new_client(admin.app).post("/api/v1/auth/login", json={"name": "dee", "password": temporary})
    assert r.status_code == 401 and r.json()["type"] == "/problems/temporary-password-expired"


def test_the_last_five_passwords_cant_be_used_again(make_client, database):
    c = make_client(roles=None)
    add_account(c.app, database, ["MANAGER"], username="eve")
    sign_in(c, "eve")
    words = [f"passphrase number {n} for eve" for n in range(1, 7)]
    current = PASSWORD
    for w in words[:5]:
        assert c.post("/api/v1/auth/password", json={"current": current, "new": w}).status_code == 200
        current = w
    r = c.post("/api/v1/auth/password", json={"current": current, "new": words[0]})
    assert r.status_code == 422 and "last 5" in r.json()["detail"]
    assert c.post("/api/v1/auth/password", json={"current": current, "new": words[5]}).status_code == 200
    assert c.post("/api/v1/auth/password", json={"current": words[5], "new": words[0]}).status_code == 200  # six back now


def test_changing_the_password_signs_out_the_other_sessions(make_client, database):
    c = make_client(roles=None)
    add_account(c.app, database, ["MANAGER"], username="fay")
    other = new_client(c.app)
    sign_in(c, "fay")
    sign_in(other, "fay")
    assert c.post("/api/v1/auth/password", json={"current": PASSWORD, "new": "a brand new passphrase"}).status_code == 200
    assert c.get("/api/v1/monitoring/live").status_code == 200
    assert other.get("/api/v1/monitoring/live").json()["type"] == "/problems/session-ended"


def test_manager_sessions_end_after_inactivity_and_background_refreshes_dont_count(make_client, database):
    """SES-02's 15 min, checked by moving the session's last activity back rather than waiting for it."""
    c = make_client(roles=None)
    add_account(c.app, database, ["MANAGER"], username="gus")
    sign_in(c, "gus")

    def quiet(minutes: float):  # nobody has touched the session for this long
        with database.connect() as conn:
            conn.execute("""UPDATE app_session SET last_active_at = clock_timestamp() - make_interval(secs => %s)
                             WHERE user_id = (SELECT id FROM app_user WHERE username = 'gus')""", (minutes * 60,))
            conn.commit()

    def last_active():
        with database.connect() as conn:
            return conn.execute("""SELECT last_active_at FROM app_session
                                    WHERE user_id = (SELECT id FROM app_user WHERE username = 'gus')""").fetchone()["last_active_at"]

    quiet(14)
    before = last_active()
    assert c.get("/api/v1/monitoring/live").status_code == 200  # only the live page refreshing: not activity
    assert last_active() == before
    assert c.post("/api/v1/auth/activity").status_code == 200  # the person's own action
    assert last_active() > before
    quiet(15.1)
    r = c.get("/api/v1/monitoring/live")
    assert r.status_code == 401 and r.json()["type"] == "/problems/session-expired"


def test_at_most_ten_manager_and_administrator_sessions(make_client, database):
    c = make_client(roles=None, auth=replace(FAST_AUTH, privileged_sessions_max=2))
    add_account(c.app, database, ["MANAGER"], username="hal")
    first, second = new_client(c.app), new_client(c.app)
    sign_in(first, "hal")
    sign_in(second, "hal")
    r = c.post("/api/v1/auth/login", json={"name": "hal", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["type"] == "/problems/too-many-sessions"
    assert first.post("/api/v1/auth/logout").json() == {"signedOut": True}
    sign_in(c, "hal")
    assert first.get("/api/v1/monitoring/live").json()["type"] == "/problems/not-signed-in"  # the cookie is gone


def test_operators_sign_in_only_at_an_operator_workstation_and_never_time_out(make_client, database):
    auth = replace(FAST_AUTH, operator_workstations=DESKS, privileged_idle_min=0.01)
    app = make_client(roles=None, auth=auth).app
    add_account(app, database, OPERATOR, username="ivy")
    r = new_client(app, "10.0.0.9").post("/api/v1/auth/login", json={"name": "ivy", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["type"] == "/problems/not-an-operator-workstation"
    desk = new_client(app, "10.0.0.5")
    session = sign_in(desk, "ivy")["session"]
    assert (session["kind"], session["workstation"], session["idleLimitS"]) == ("operator", "Line desk", None)
    time.sleep(0.8)  # longer than the (shortened) Manager limit
    assert desk.get("/api/v1/monitoring/live").status_code == 200


def test_one_operator_session_for_the_line_taken_over_after_5_minutes_without_a_heartbeat(make_client, database):
    app = make_client(roles=None, auth=replace(FAST_AUTH, operator_workstations=DESKS)).app
    add_account(app, database, OPERATOR, username="jo")
    add_account(app, database, OPERATOR, username="kim")
    primary, backup = new_client(app, "10.0.0.5"), new_client(app, "10.0.0.6")
    sign_in(primary, "jo")

    r = backup.post("/api/v1/auth/login", json={"name": "kim", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["takeoverAvailable"] is False and r.json()["workstation"] == "Line desk"
    r = backup.post("/api/v1/auth/takeover", json={"name": "kim", "password": PASSWORD})
    assert r.status_code == 409  # not while the other one is alive
    with database.connect() as conn:  # the Line desk has been silent for 6 min
        conn.execute("UPDATE app_session SET last_seen_at = now() - interval '6 min' WHERE kind = 'operator'")
        conn.commit()
    r = backup.post("/api/v1/auth/login", json={"name": "kim", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["takeoverAvailable"] is True
    r = backup.post("/api/v1/auth/takeover", json={"name": "kim", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["session"]["workstation"] == "Backup desk"
    assert primary.get("/api/v1/monitoring/live").json()["type"] == "/problems/session-ended"
    assert "took over the operator session of jo at Line desk" in audit(database, "auth.takeover")[0]["summary"]

    again = new_client(app, "10.0.0.6")  # the same workstation signing in again replaces its own session
    sign_in(again, "kim")
    assert backup.get("/api/v1/monitoring/live").status_code == 401
    assert again.get("/api/v1/monitoring/live").status_code == 200


def test_signing_out_ends_the_session_and_the_audit_log_names_who_changed_what(make_client, database):
    c = make_client(roles=None)
    add_account(c.app, database, ["MANAGER"], username="lou")
    sign_in(c, "lou")
    proposal = c.get("/api/v1/config/rules/proposal").json()
    assert c.post("/api/v1/config/versions", json={"expectedLatest": None, "settings": proposal["settings"], "rules": proposal["rules"],
                                                   "reason": "The Phase 0 proposal"}).status_code == 201
    entry = c.get("/api/v1/config/register").json()["audit"][0]
    assert (entry["action"], entry["user"]) == ("rules.version", "lou")
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 200 and 'centerline_session=""' in r.headers["set-cookie"]
    assert c.get("/api/v1/config/rules").status_code == 401
    assert [e["actor"] for e in audit(database, "auth.sign_out")] == ["lou"]
