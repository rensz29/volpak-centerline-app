"""Notifications (ADR-0023): routing versions, the channel settings, the log, TEST messages and re-drives."""

from __future__ import annotations

import stat

from centerline_common import routing as routing_mod

from .test_config_api import free_port

ALL = list(routing_mod.TYPES)
URL = ("https://prod-01.westeurope.logic.azure.com/workflows/abc/triggers/manual/paths/invoke"
       "?api-version=2016-06-01&sig=NOT-A-REAL-SIGNATURE")


def audit(c, action: str) -> list[dict]:
    return [e for e in c.get("/api/v1/config/register").json()["audit"] if e["action"] == action]


def me(c) -> str:
    return c.get("/api/v1/auth/session").json()["user"]["username"]


def test_routing_starts_from_the_proposal_and_a_version_leaving_criticals_unsent_cant_be_activated(make_client):
    c = make_client()
    empty = c.get("/api/v1/config/routing").json()
    assert empty["active"] is None and empty["rules"] is None and [t["id"] for t in empty["types"]] == ALL
    proposal = c.get("/api/v1/config/routing/proposal").json()
    assert [r["channel"] for r in proposal["rules"]] == ["teams", "email"]
    assert any(w.startswith("Placeholder addresses") for w in proposal["warnings"])

    bad = c.post("/api/v1/config/routing/versions", json={"expectedLatest": None, "rules": [
        {"name": "", "types": [], "channel": "email", "targets": ["nope"]}], "reason": ""})
    assert bad.status_code == 422
    assert {e["field"] for e in bad.json()["errors"]} == {"rules[0].name", "rules[0].types", "rules[0].targets", "reason"}

    quiet = [{"name": "Recoveries only", "types": ["recovery"], "channel": "email", "targets": ["lead@plant.test"]}]
    check = c.post("/api/v1/config/routing/versions/check", json={"expectedLatest": None, "rules": quiet}).json()
    assert check["errors"] == [] and any("ACT-03" in w for w in check["warnings"])
    now = c.post("/api/v1/config/routing/versions", json={"expectedLatest": None, "rules": quiet, "reason": "Trying", "activate": "now"})
    assert now.status_code == 422 and now.json()["errors"][0]["message"].startswith("Critical alerts must reach someone (ACT-03)")
    assert c.post("/api/v1/config/routing/versions", json={"expectedLatest": None, "rules": quiet, "reason": "Trying"}).status_code == 201
    refused = c.post("/api/v1/config/routing/versions/1/activate", json={"expectedActive": None, "reason": "Go"})
    assert refused.status_code == 422  # saved, but it can't take effect

    r = c.post("/api/v1/config/routing/versions", json={"expectedLatest": 1, "basedOn": 1, "rules": proposal["rules"],
                                                        "reason": "The Phase 2 proposal", "activate": "now"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["active"]["number"], body["active"]["by"], body["rules"]) == (2, me(c), proposal["rules"])
    assert [v["status"] for v in body["versions"]] == ["active", "saved"]
    assert c.get("/api/v1/config/routing/versions/2").json()["intact"]
    assert [e["summary"] for e in audit(c, "routing.version")] == ["Routing v2 saved from v1: 2 rules, 2 recipients",
                                                                   "Routing v1 saved: 1 rule, 1 recipient"]
    assert make_client(roles=["MANAGER"]).post("/api/v1/config/routing/versions", json={
        "expectedLatest": 2, "rules": proposal["rules"], "reason": "x"}).status_code == 403


def test_the_flow_url_and_the_relay_password_are_write_only(make_client, tmp_path):
    c = make_client()
    secrets = tmp_path / "config" / "secrets"
    r = c.put("/api/v1/config/connections/notifications", json={"appUrl": "ftp://x", "teamsUrl": "http://not-https/x",
                                                               "smtpHost": "relay.plant.test", "emailSender": "", "reason": "x"})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} == {"appUrl", "teamsUrl", "emailSender"}
    assert not (secrets / "teams-flow-url").exists()  # nothing is written from a form that isn't valid

    form = {"appUrl": "https://centerline.plant.test/", "teamsUrl": URL, "smtpHost": "relay.plant.test", "smtpPort": 587,
            "smtpSecurity": "starttls", "smtpUsername": "centerline", "smtpPassword": "pw-123",
            "emailSender": "centerline@plant.test", "reason": "From IT"}
    r = c.put("/api/v1/config/connections/notifications", json=form)
    assert r.status_code == 200, r.text
    assert r.json()["notifications"] == {
        "appUrl": "https://centerline.plant.test", "line": "Volpak",
        "teams": {"configured": True, "where": "https://prod-01.westeurope.logic.azure.com"},
        "email": {"configured": True, "host": "relay.plant.test", "port": 587, "security": "starttls", "username": "centerline",
                  "passwordSet": True, "sender": "centerline@plant.test"}}
    assert "NOT-A-REAL-SIGNATURE" not in r.text and "pw-123" not in r.text
    for name in ("teams-flow-url", "smtp-password"):
        assert stat.S_IMODE((secrets / name).stat().st_mode) == 0o600
    again = c.put("/api/v1/config/connections/notifications", json={**form, "teamsUrl": "", "smtpPassword": "", "smtpPort": 25})
    n = again.json()["notifications"]
    assert n["teams"]["configured"] and n["email"]["passwordSet"] and n["email"]["port"] == 25  # not typed again: kept
    summaries = [e["summary"] for e in audit(c, "connections.notifications")]
    assert summaries[0] == "Notifications: Teams set · email via relay.plant.test:25 from centerline@plant.test · links to https://centerline.plant.test"
    assert not any("NOT-A-REAL-SIGNATURE" in s or "pw-123" in s for s in summaries)

    port = free_port()
    test = c.post("/api/v1/config/connections/notifications/email-test", json={**form, "smtpHost": "127.0.0.1", "smtpPort": port,
                                                                               "smtpSecurity": "none"}).json()
    assert test["ok"] is False and f"127.0.0.1:{port}" in test["response"]


def test_a_test_message_goes_to_the_one_recipient_named_and_is_audited(make_client):
    c = make_client()
    assert c.post("/api/v1/notifications/test", json={"channel": "email", "target": "nope"}).status_code == 422
    r = c.post("/api/v1/notifications/test", json={"channel": "email", "target": "lead@plant.test", "note": "Checking the relay"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["kind"], t["type"], t["subject"], t["outcome"]) == ("test", "test", "TEST - NO PRODUCTION EVENT", "test")
    (d,) = t["deliveries"]
    assert (d["channel"], d["target"], d["status"], d["rule"]) == ("email", "lead@plant.test", "PENDING", None)
    assert d["content"]["body"].startswith(f"A test message from Centerline, sent by {me(c)}. There is no production event.")
    assert "Note: Checking the relay" in d["content"]["body"]
    log = c.get("/api/v1/notifications", params={"state": "test"}).json()
    assert [n["id"] for n in log["notifications"]] == [t["id"]] and log["counts"] == {"waiting": 1, "failed": 0}
    assert c.get("/api/v1/notifications", params={"state": "failed"}).json()["notifications"] == []
    assert [e["summary"] for e in audit(c, "notifications.test")] == ["TEST message to lead@plant.test on Email"]
    assert make_client(roles=["MANAGER"]).post("/api/v1/notifications/test", json={"channel": "email",
                                                                                  "target": "a@b.co"}).status_code == 403


def test_only_a_permanent_failure_is_re_driven_and_only_with_a_reason(make_client, database):
    c = make_client()
    t = c.post("/api/v1/notifications/test", json={"channel": "teams", "target": "Centerline alerts"}).json()
    did = t["deliveries"][0]["id"]
    assert c.post(f"/api/v1/deliveries/{did}/redrive", json={"reason": "Flow fixed"}).status_code == 409  # still on its way
    with database.connect() as conn:  # as the notifier leaves it after 24 h of failures
        conn.execute("""UPDATE notification_delivery SET status = 'PERMANENT_FAILURE', finished_at = now(), last_error = 'HTTP 401'
                         WHERE id = %s""", (did,))
        conn.commit()
    assert [n["id"] for n in c.get("/api/v1/notifications", params={"state": "failed"}).json()["notifications"]] == [t["id"]]
    assert c.post(f"/api/v1/deliveries/{did}/redrive", json={"reason": ""}).status_code == 422
    assert make_client(roles=["MANAGER"]).post(f"/api/v1/deliveries/{did}/redrive", json={"reason": "x y z"}).status_code == 403

    r = c.post(f"/api/v1/deliveries/{did}/redrive", json={"reason": "The flow's owner renewed it"})
    assert r.status_code == 200, r.text
    old, new = r.json()["deliveries"]
    assert (old["status"], new["status"], new["redriveOf"], new["redrivenBy"], new["redriveReason"]) == (
        "REDRIVEN", "PENDING", did, me(c), "The flow's owner renewed it")
    assert new["messageId"] != old["messageId"] and new["dedupKey"].startswith(old["dedupKey"] + ":redrive:")
    assert new["content"]["subject"] == old["content"]["subject"] == "TEST - NO PRODUCTION EVENT"
    assert c.post(f"/api/v1/deliveries/{did}/redrive", json={"reason": "Once more"}).status_code == 409
    (entry,) = audit(c, "notifications.redrive")
    assert entry["summary"] == "Re-drove the Teams delivery to Centerline alerts, which failed for good"
    detail = c.get(f"/api/v1/notifications/{t['id']}").json()
    assert detail["route"]["outcome"] == "test" and detail["deliveries"][0]["attemptLog"] == []
