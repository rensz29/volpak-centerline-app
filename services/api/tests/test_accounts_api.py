"""Accounts, managed by an Administrator (ADR-0016, IAM-01…04)."""

from __future__ import annotations

import json
import re
import stat
from datetime import datetime, timedelta, timezone

from .conftest import PASSWORD, add_account, new_client, sign_in

TEMPORARY = re.compile(r"^[a-z2-9]{4}(-[a-z2-9]{4}){3}$")


def create(c, **fields):
    return c.post("/api/v1/users", json={"displayName": fields.pop("displayName", "Test Person"), **fields})


def test_a_new_account_gets_a_24_hour_temporary_password_shown_once(make_client):
    c = make_client()
    r = create(c, username="Maria.Santos", displayName="Maria Santos", email="maria@plant.example", employeeId="E-7",
               roles=["MANAGER"], reason="New shift manager")
    assert r.status_code == 201
    body = r.json()
    assert TEMPORARY.match(body["temporaryPassword"])
    until = datetime.fromisoformat(body["temporaryExpiresAt"].replace("Z", "+00:00"))
    assert timedelta(hours=23, minutes=59) < until - datetime.now(timezone.utc) <= timedelta(hours=24)
    account = body["account"]
    assert (account["username"], account["roles"], account["mustChange"], account["sessions"]) == (
        "maria.santos", ["MANAGER"], True, 0)
    listed = {a["username"]: a for a in c.get("/api/v1/users").json()["accounts"]}
    assert "temporaryPassword" not in listed["maria.santos"] and "passwordHash" not in str(listed)
    entry = c.get("/api/v1/config/register").json()["audit"][0]
    assert entry["action"] == "account.create" and body["temporaryPassword"] not in str(entry)


def test_an_operator_account_has_only_that_role_and_names_are_unique_across_kinds(make_client):
    c = make_client()
    r = create(c, username="op1", roles=["OPERATOR", "MANAGER"])
    assert r.status_code == 422 and "only that role" in r.json()["detail"]
    assert create(c, username="op1", roles=["OPERATOR"], email="op1@plant.example", employeeId="E-100").status_code == 201
    # A name signs in to one account only, whichever kind of name it is on each
    r = create(c, username="someone", roles=["MANAGER"], employeeId="OP1")
    assert r.status_code == 409 and r.json()["errors"] == [{"field": "employeeId", "message": "Already used by another account"}]
    r = create(c, username="someone", roles=["MANAGER"], email="OP1@Plant.Example")
    assert r.status_code == 409 and r.json()["errors"][0]["field"] == "email"
    r = create(c, username="e-100", roles=["MANAGER"])
    assert r.status_code == 409 and r.json()["errors"][0]["field"] == "username"
    assert create(c, username="bad name!", roles=["MANAGER"]).status_code == 422
    assert create(c, username="someone", roles=["MANAGER"], email="not an email").status_code == 422


def test_new_roles_or_disabling_sign_the_account_out_at_once(make_client, database):
    admin = make_client()
    user = new_client(admin.app)
    name = add_account(admin.app, database, ["MANAGER"])
    sign_in(user, name)
    uid = next(a["id"] for a in admin.get("/api/v1/users").json()["accounts"] if a["username"] == name)
    same = {"displayName": "Changed Name", "roles": ["MANAGER"], "active": True}
    r = admin.put(f"/api/v1/users/{uid}", json=same)
    assert r.json()["signedOut"] == 0 and user.get("/api/v1/config/rules").status_code == 200  # a new name alone doesn't

    r = admin.put(f"/api/v1/users/{uid}", json={**same, "roles": ["MANAGER", "ADMINISTRATOR"], "reason": "Covers IT"})
    assert r.json()["signedOut"] == 1
    assert user.get("/api/v1/config/rules").json()["type"] == "/problems/session-ended"
    assert sign_in(user, name)["user"]["roles"] == ["ADMINISTRATOR", "MANAGER"]

    admin.put(f"/api/v1/users/{uid}", json={**same, "roles": ["MANAGER", "ADMINISTRATOR"], "active": False})
    assert user.get("/api/v1/config/rules").status_code == 401
    r = new_client(admin.app).post("/api/v1/auth/login", json={"name": name, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["type"] == "/problems/account-disabled"
    entries = [e for e in admin.get("/api/v1/config/register").json()["audit"] if e["action"] == "account.update"]
    assert entries[0]["summary"] == f"Account {name}: disabled; 1 session(s) signed out"
    assert entries[1]["summary"] == f"Account {name}: roles Manager → Manager and Administrator; 1 session(s) signed out"
    assert entries[1]["reason"] == "Covers IT"


def test_the_last_administrator_cant_be_disabled_or_lose_the_role(make_client):
    c = make_client(roles=["ADMINISTRATOR"])
    me = c.get("/api/v1/auth/session").json()["user"]
    r = c.put(f"/api/v1/users/{me['id']}", json={"displayName": "Me", "roles": ["MANAGER"], "active": True})
    assert r.status_code == 409 and r.json()["type"] == "/problems/last-administrator"
    r = c.put(f"/api/v1/users/{me['id']}", json={"displayName": "Me", "roles": ["ADMINISTRATOR"], "active": False})
    assert r.status_code == 409
    other = create(c, username="second", roles=["ADMINISTRATOR"]).json()["account"]
    r = c.put(f"/api/v1/users/{me['id']}", json={"displayName": "Me", "roles": ["MANAGER"], "active": True})
    assert r.status_code == 200 and r.json()["you"] is True
    assert c.get("/api/v1/users").status_code == 401  # changing your own roles signs you out too
    assert other["roles"] == ["ADMINISTRATOR"]


def test_a_temporary_password_unlocks_the_account_and_ends_its_sessions(make_client, database):
    admin = make_client()
    name = add_account(admin.app, database, ["MANAGER"])
    user = new_client(admin.app)
    sign_in(user, name)
    for _ in range(5):
        new_client(admin.app).post("/api/v1/auth/login", json={"name": name, "password": "wrong password here"})
    uid = next(a["id"] for a in admin.get("/api/v1/users").json()["accounts"] if a["username"] == name)
    assert next(a for a in admin.get("/api/v1/users").json()["accounts"] if a["id"] == uid)["lockedUntil"]
    r = admin.post(f"/api/v1/users/{uid}/temporary-password", json={"reason": "Locked out"})
    body = r.json()
    assert r.status_code == 200 and body["account"]["lockedUntil"] is None and body["account"]["mustChange"] is True
    assert user.get("/api/v1/config/rules").status_code == 401
    assert sign_in(new_client(admin.app), name, body["temporaryPassword"])["user"]["mustChange"] is True


def test_the_username_never_changes_and_only_an_administrator_manages_accounts(make_client, database):
    admin = make_client()
    uid = create(admin, username="stays", roles=["MANAGER"]).json()["account"]["id"]
    r = admin.put(f"/api/v1/users/{uid}", json={"username": "moved", "displayName": "X", "roles": ["MANAGER"],
                                                "active": True})
    assert r.status_code == 422  # not a field that can be sent
    with database.connect() as conn:
        try:
            conn.execute("UPDATE app_user SET username = 'moved' WHERE id = %s", (uid,))
            raise AssertionError("the database let a username change")
        except Exception as e:  # noqa: BLE001
            assert "never changes" in str(e)
    assert make_client(roles=["MANAGER"]).get("/api/v1/users").status_code == 403


def test_the_command_line_creates_an_administrator_and_issues_a_temporary_password(database, tmp_path, monkeypatch, capsys):
    """As the server is set up (ADR-0020): the services' role writes the accounts, the owner migrates."""
    from centerline_api.auth.__main__ import main

    config = tmp_path / "api.json"
    config.write_text(json.dumps({
        "timebase": {"base_url": "http://127.0.0.1:9", "dataset": "x", "auth": {"type": "none"}},
        "database": {"dbname": database.dbname, "user": database.user, "password_file": str(database.password_file)},
        "migrate_database": {"dbname": database.dbname}}))
    monkeypatch.setenv("CENTERLINE_API_CONFIG", str(config))
    out = tmp_path / "first-admin-password"
    assert main(["create-admin", "--username", "cli.admin", "--name", "CLI Admin", "--out", str(out)]) == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o600 and len(out.read_text().strip()) >= 12
    assert out.read_text().strip() not in capsys.readouterr().out  # written to the file, not the screen
    with database.connect() as conn:
        row = conn.execute("SELECT roles, must_change FROM app_user WHERE username = 'cli.admin'").fetchone()
    assert (sorted(row["roles"]), row["must_change"]) == (["ADMINISTRATOR", "MANAGER"], True)
    again = tmp_path / "way-back-in"
    assert main(["temporary-password", "--username", "cli.admin", "--out", str(again)]) == 0
    assert again.read_text() != out.read_text()
    assert main(["temporary-password", "--username", "nobody", "--out", str(again)]) == 1
