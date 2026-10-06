"""AT-04: local accounts, roles, password policy, staged handover, workstation restriction and takeover.

URS v1.1 §5 (IAM-01…04, SES-01…04), as built in ADR-0016 and ADR-0025. SES-05, the operator's unsent text, is
shown in AT-05 with the requests it belongs to.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from .conftest import AT_THE_LINE, PASSWORD, add_account, new_client, sign_in

USERS = "/api/v1/users"
LIVE = "/api/v1/monitoring/live"  # any page that needs a session
MANILA = timezone(timedelta(hours=8))


def create(admin, **account):
    return admin.post(USERS, json={"displayName": account.get("username", "x").title(), **account})


def account_id(admin, username: str) -> str:
    return next(a["id"] for a in admin.get(USERS).json()["accounts"] if a["username"] == username)


def run_sql(database, sql: str, params: tuple = ()) -> None:
    with database.connect() as conn:
        conn.execute(sql, params)
        conn.commit()


@pytest.mark.urs("IAM-01", "IAM-02")
def test_an_administrator_makes_accounts_with_their_roles_and_each_signs_in_by_any_of_its_names(make_client, database):
    admin = make_client(roles=["ADMINISTRATOR"])
    # Operator, Manager and Administrator; several on one account, but an Operator's account is only that; no Auditor
    assert create(admin, username="auditor", roles=["AUDITOR"]).status_code == 422
    assert create(admin, username="mixed", roles=["OPERATOR", "MANAGER"]).status_code == 422
    made = create(admin, username="ana", displayName="Ana Cruz", email="Ana.Cruz@Plant.example", employeeId="E-1042",
                  roles=["MANAGER", "ADMINISTRATOR"], reason="New shift manager")
    assert made.status_code == 201
    temporary, expires = made.json()["temporaryPassword"], made.json()["temporaryExpiresAt"]
    left = datetime.fromisoformat(expires.replace("Z", "+00:00")) - datetime.now(timezone.utc)
    assert timedelta(hours=23, minutes=59) < left <= timedelta(hours=24)  # a 24-hour temporary password
    assert create(admin, username="olga", roles=["OPERATOR"]).status_code == 201

    for name in ("ANA", "ana.cruz@plant.EXAMPLE", "e-1042"):  # username, email or Employee ID, in any case
        assert sign_in(new_client(admin.app), name, temporary)["user"]["username"] == "ana"
    first = new_client(admin.app)
    assert sign_in(first, "ana", temporary)["user"]["mustChange"] is True
    assert first.get(LIVE).json()["type"] == "/problems/password-change-required"  # the change comes first
    assert first.post("/api/v1/auth/password", json={"current": temporary, "new": "Ana's own long passphrase"}).status_code == 200
    assert first.get(LIVE).status_code == 200

    issued = admin.post(f"{USERS}/{account_id(admin, 'ana')}/temporary-password", json={"reason": "Forgot it"}).json()
    run_sql(database, "UPDATE app_user SET temp_expires_at = now() - interval '1 min' WHERE username = 'ana'")
    r = new_client(admin.app).post("/api/v1/auth/login", json={"name": "ana", "password": issued["temporaryPassword"]})
    assert r.json()["type"] == "/problems/temporary-password-expired"  # after 24 h it no longer works


@pytest.mark.urs("IAM-03")
def test_passwords_are_long_not_known_breached_not_reused_and_five_failures_lock_for_15_minutes(make_client, database):
    c = make_client(roles=None)
    add_account(c.app, database, ["MANAGER"], username="ben")
    sign_in(c, "ben")
    for weak, why in (("short one", "at least 12"), ("password1234", "breaches")):
        r = c.post("/api/v1/auth/password", json={"current": PASSWORD, "new": weak})
        assert r.status_code == 422 and why in r.json()["detail"]
    current = PASSWORD
    for n in range(1, 6):
        new = f"ben's passphrase number {n}"
        assert c.post("/api/v1/auth/password", json={"current": current, "new": new}).status_code == 200
        current = new
    r = c.post("/api/v1/auth/password", json={"current": current, "new": "ben's passphrase number 1"})
    assert r.status_code == 422 and "last 5" in r.json()["detail"]  # five back can't be used again

    with database.connect() as conn:
        stored = conn.execute("SELECT password_hash FROM app_user WHERE username = 'ben'").fetchone()["password_hash"]
    assert stored.startswith("$argon2id$") and current not in stored  # a salted adaptive hash only

    door = new_client(c.app)
    for _ in range(4):
        assert door.post("/api/v1/auth/login", json={"name": "ben", "password": "not ben's password"}).status_code == 401
    assert door.post("/api/v1/auth/login", json={"name": "ben", "password": "not ben's password"}).status_code == 423
    assert door.post("/api/v1/auth/login", json={"name": "ben", "password": current}).status_code == 423  # even the right one
    with database.connect() as conn:
        left = conn.execute("SELECT locked_until - now() AS left FROM app_user WHERE username = 'ben'").fetchone()["left"]
    assert timedelta(minutes=14, seconds=50) < left <= timedelta(minutes=15)


@pytest.mark.urs("IAM-04")
def test_new_roles_disabling_or_a_password_reset_end_every_session_at_once(make_client, database):
    admin = make_client(roles=["ADMINISTRATOR"])
    name = add_account(admin.app, database, ["MANAGER"], username="cy")
    uid = account_id(admin, name)
    same = {"displayName": "Cy", "roles": ["MANAGER"], "active": True}

    def two_sessions():
        a, b = new_client(admin.app), new_client(admin.app)
        sign_in(a, name)
        sign_in(b, name)
        return a, b

    def signed_out(a, b) -> bool:
        return a.get(LIVE).status_code == 401 and b.get(LIVE).status_code == 401

    a, b = two_sessions()
    roles = {**same, "roles": ["MANAGER", "ADMINISTRATOR"]}
    assert admin.put(f"{USERS}/{uid}", json=roles).json()["signedOut"] == 2 and signed_out(a, b)
    a, b = two_sessions()
    assert admin.put(f"{USERS}/{uid}", json={**roles, "active": False}).json()["signedOut"] == 2 and signed_out(a, b)
    admin.put(f"{USERS}/{uid}", json=roles)
    a, b = two_sessions()
    assert admin.post(f"{USERS}/{uid}/temporary-password", json={"reason": "Locked out"}).status_code == 200
    assert signed_out(a, b)


@pytest.mark.urs("SES-01", "SES-02")
def test_one_operator_session_up_to_ten_others_and_only_theirs_time_out(make_client, database):
    app = make_client(roles=None, auth=AT_THE_LINE).app
    add_account(app, database, ["OPERATOR"], username="dee")
    add_account(app, database, ["OPERATOR"], username="eli")
    add_account(app, database, ["MANAGER", "ADMINISTRATOR"], username="fay")
    desk = new_client(app, "10.0.0.5")
    assert sign_in(desk, "dee")["session"]["idleLimitS"] is None  # an operator never times out
    r = new_client(app, "10.0.0.6").post("/api/v1/auth/login", json={"name": "eli", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["workstation"] == "Line desk"  # one operator session for the line

    privileged = [new_client(app) for _ in range(10)]
    for c in privileged:
        session = sign_in(c, "fay")["session"]
    assert (session["idleLimitS"], session["idleLimitS"] - session["idleWarningS"]) == (900, 120)  # 15 min, warned 2 min before
    r = new_client(app).post("/api/v1/auth/login", json={"name": "fay", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["type"] == "/problems/too-many-sessions"  # at most 10 together

    run_sql(database, "UPDATE app_session SET last_active_at = clock_timestamp() - interval '15 min 6 s'")
    assert privileged[0].get(LIVE).json()["type"] == "/problems/session-expired"
    assert desk.get(LIVE).status_code == 200  # the operator's, idle as long, carries on


@pytest.mark.urs("SES-03")
def test_the_operators_session_ends_with_its_shift_after_a_warning_and_the_next_operator_signs_in(make_client, database):
    app = make_client(roles=None, auth=AT_THE_LINE).app
    add_account(app, database, ["OPERATOR"], username="gus")
    add_account(app, database, ["OPERATOR"], username="hal")
    desk = new_client(app, "10.0.0.5")
    sign_in(desk, "gus")
    body = desk.get("/api/v1/auth/session").json()
    assert body["session"]["endsWithShift"] is True and body["session"]["shiftWarningS"] == 300  # warned 5 min before
    ends = datetime.fromisoformat(body["shift"]["endsAt"].replace("Z", "+00:00")).astimezone(MANILA)
    assert (ends.hour, ends.minute) in ((6, 0), (14, 0), (22, 0)) and body["shift"]["code"] in "ABC"

    run_sql(database, "UPDATE app_session SET created_at = created_at - interval '9 hours' WHERE kind = 'operator'")
    assert desk.get(LIVE).json()["type"] == "/problems/shift-over"  # the boundary ends it
    backup = new_client(app, "10.0.0.6")
    assert sign_in(backup, "hal")["session"]["workstation"] == "Backup desk"  # the next shift's operator, no takeover needed


@pytest.mark.urs("SES-04")
def test_operators_sign_in_only_at_the_line_desks_and_take_over_a_silent_session_after_5_minutes(make_client, database):
    app = make_client(roles=None, auth=AT_THE_LINE).app
    add_account(app, database, ["OPERATOR"], username="ivy")
    add_account(app, database, ["OPERATOR"], username="jo")
    r = new_client(app, "10.0.0.9").post("/api/v1/auth/login", json={"name": "ivy", "password": PASSWORD})
    assert r.json()["type"] == "/problems/not-an-operator-workstation"
    line_desk, backup_desk = new_client(app, "10.0.0.5"), new_client(app, "10.0.0.6")
    sign_in(line_desk, "ivy")
    assert backup_desk.post("/api/v1/auth/takeover", json={"name": "jo", "password": PASSWORD}).status_code == 409  # still alive

    # back at the same desk within 5 minutes: the session resumes there, nobody takes it
    again = new_client(app, "10.0.0.5")
    assert sign_in(again, "ivy")["session"]["workstation"] == "Line desk"

    run_sql(database, "UPDATE app_session SET last_seen_at = now() - interval '5 min 10 s' WHERE kind = 'operator'")
    r = backup_desk.post("/api/v1/auth/login", json={"name": "jo", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["takeoverAvailable"] is True
    r = backup_desk.post("/api/v1/auth/takeover", json={"name": "jo", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["session"]["workstation"] == "Backup desk"
    assert again.get(LIVE).json()["type"] == "/problems/session-ended"
