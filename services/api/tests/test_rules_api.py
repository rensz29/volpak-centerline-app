"""Rules tab API (ADR-0012, ADR-0027): versions, activation and rollback, what each zone lacks, and the database's absence."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from centerline_api.main import create_app
from centerline_common import rules as rules_mod
from centerline_common.db import DatabaseConfig, uuid7
from psycopg.types.json import Jsonb

from .conftest import make_settings, new_client


DEFAULTS = {"mismatch_delay_s": 30, "warning_delay_s": 30, "critical_delay_s": 10, "recovery_delay_s": 15,
            "brief_change_mode": "lightweight", "warning_notifications": True}


def later(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def first_version(c, activate="no", **extra) -> dict:
    prop = c.get("/api/v1/config/rules/proposal").json()
    body = {"expectedLatest": None, "settings": prop["settings"], "rules": prop["rules"],
            "reason": "Start from the Phase 0 proposal", "activate": activate, **extra}
    r = c.post("/api/v1/config/versions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def monitored_zones(c) -> list[tuple[str, str]]:
    reg = c.get("/api/v1/config/register").json()
    return [(p["id"], z["id"]) for p in reg["parameters"] if p["status"] == "active" for z in p["zones"]]


def audit_summaries(c) -> list[str]:
    return [e["summary"] for e in c.get("/api/v1/config/register").json()["audit"]]


def test_the_first_version_starts_from_the_proposal_and_waits_to_be_activated(make_client):
    c = make_client()
    empty = c.get("/api/v1/config/rules").json()
    assert empty["active"] is None and empty["latest"] is None and empty["versions"] == []
    prop = c.get("/api/v1/config/rules/proposal").json()
    assert prop["settings"]["defaults"]["mismatchDelayS"] == 30 and len(prop["rules"]) == 5

    body = first_version(c)
    assert body["created"] == 1 and body["active"] is None and body["versions"][0]["status"] == "saved"
    v1 = c.get("/api/v1/config/versions/1").json()
    assert v1["intact"] and v1["basedOn"] is None and v1["registerVersion"] == body["registerVersion"]
    p02 = next(r for r in v1["rules"] if r["parameterId"] == "P02")
    assert (p02["warnLow"], p02["warnHigh"], p02["critLow"], p02["critHigh"]) == (2, 1, 4, 2)
    assert v1["settings"]["pauseWhenStopped"] == {"enabled": True, "longStopMin": 10, "warmupMin": 30}
    assert "Rules v1 saved: 5 rule rows" in audit_summaries(c)


def test_activate_roll_back_schedule_and_cancel(make_client, database):
    c = make_client()
    me = c.get("/api/v1/auth/session").json()["user"]["username"]
    first_version(c, activate="now")
    rules_v2 = c.get("/api/v1/config/versions/1").json()["rules"]
    rules_v2[0]["mismatchDelayS"] = 60
    r = c.post("/api/v1/config/versions", json={"expectedLatest": 1, "basedOn": 1, "settings": c.get("/api/v1/config/versions/1").json()["settings"],
                                               "rules": rules_v2, "reason": "Longer mismatch delay for P02"})
    assert r.status_code == 201 and r.json()["active"]["number"] == 1

    assert c.post("/api/v1/config/versions/2/activate", json={"expectedActive": 1, "reason": "Trial"}).json()["active"]["number"] == 2
    stale = c.post("/api/v1/config/versions/1/activate", json={"expectedActive": 1, "reason": "Back"})
    assert stale.status_code == 409 and stale.json()["currentActive"] == 2
    back = c.post("/api/v1/config/versions/1/activate", json={"expectedActive": 2, "reason": "Back to the proposal"}).json()
    assert back["active"]["number"] == 1 and {v["number"]: v["status"] for v in back["versions"]} == {2: "previous", 1: "active"}
    assert back["active"]["by"] == me  # each activation names who made it
    assert any("Rules v1 activated (rollback), replacing v2" == s for s in audit_summaries(c))

    again = c.post("/api/v1/config/versions/1/activate", json={"expectedActive": 1, "reason": "again"})
    assert again.status_code == 422 and again.json()["errors"][0]["field"] == "at"
    past = c.post("/api/v1/config/versions/2/activate", json={"expectedActive": 1, "at": later(minutes=-5), "reason": "late"})
    assert past.status_code == 422 and past.json()["errors"][0]["field"] == "at"

    sched = c.post("/api/v1/config/versions/2/activate", json={"expectedActive": 1, "at": later(hours=1), "reason": "Next shift"}).json()
    assert sched["active"]["number"] == 1 and [s["number"] for s in sched["scheduled"]] == [2]
    assert next(v for v in sched["versions"] if v["number"] == 2)["status"] == "scheduled"
    aid = sched["scheduled"][0]["id"]
    done = c.post(f"/api/v1/config/activations/{aid}/cancel", json={"reason": "Not yet approved"}).json()
    assert done["scheduled"] == [] and done["activations"][0]["cancelReason"] == "Not yet approved"
    assert (sched["scheduled"][0]["by"], done["activations"][0]["cancelledBy"]) == (me, me)
    with database.connect() as conn:  # and so does each version
        assert [r["created_by"] for r in conn.execute("SELECT created_by FROM config_version ORDER BY number")] == [me, me]
    assert c.post(f"/api/v1/config/activations/{aid}/cancel", json={"reason": "twice"}).status_code == 409


def test_stale_and_invalid_versions_are_refused(make_client):
    c = make_client()
    first_version(c)
    prop = c.get("/api/v1/config/rules/proposal").json()
    stale = c.post("/api/v1/config/versions", json={"expectedLatest": None, "settings": prop["settings"], "rules": prop["rules"], "reason": "again"})
    assert stale.status_code == 409 and stale.json()["currentVersion"] == 1

    bad_rules = [{"parameterId": "P02", "warnLow": 5, "critLow": 4}, {"parameterId": "P04", "zoneId": "NOPE", "warnLow": 1}]
    r = c.post("/api/v1/config/versions", json={"expectedLatest": 1, "settings": prop["settings"], "rules": bad_rules,
                                               "reason": "", "activate": "at"})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"rules[0].critLow", "rules[1].zoneId", "reason", "activateAt"} <= fields
    with_sku = c.post("/api/v1/config/versions", json={"expectedLatest": 1, "settings": prop["settings"], "reason": "x y z",
                                                      "rules": [{"parameterId": "P02", "sku": "12345", "target": 180}]})
    assert with_sku.status_code == 422  # rules have no SKU (ADR-0027)
    negative = c.post("/api/v1/config/versions", json={"expectedLatest": 1, "settings": prop["settings"],
                                                      "rules": [{"parameterId": "P02", "warnLow": -1}], "reason": "x y z"})
    assert negative.status_code == 422 and negative.json()["errors"][0]["field"] == "rules[0].warnLow"
    assert c.get("/api/v1/config/rules").json()["latest"] == 1  # nothing saved


def test_each_zone_gets_its_target_and_the_gaps_say_what_is_still_missing(make_client):
    c = make_client()
    prop = c.get("/api/v1/config/rules/proposal").json()
    zones = monitored_zones(c)
    p02 = [{"parameterId": p, "zoneId": z, "target": 180 + i} for i, (p, z) in enumerate(zones) if p == "P02"]
    body = first_version(c, activate="now", rules=prop["rules"] + p02)
    gaps = body["gaps"]  # the proposal gives every zone its limits: only targets are missing, outside Vertical
    assert len(gaps) == len(zones) - len(p02) and all(g["missing"] == ["target"] for g in gaps)

    every = [{"parameterId": p, "zoneId": z, "target": 100 + i} for i, (p, z) in enumerate(zones)]
    check = c.post("/api/v1/config/versions/check", json={"expectedLatest": 1, "settings": prop["settings"],
                                                         "rules": prop["rules"] + every, "reason": ""}).json()
    assert check["errors"] == [] and check["gaps"] == []
    assert c.get("/api/v1/config/rules").json()["latest"] == 1  # checking saves nothing
    r = c.post("/api/v1/config/versions", json={"expectedLatest": 1, "basedOn": 1, "settings": prop["settings"],
                                               "rules": prop["rules"] + every, "reason": "Targets from the centerline sheet",
                                               "activate": "now"})
    assert r.status_code == 201 and r.json()["gaps"] == []
    assert c.get("/api/v1/config/versions/2").json()["carryOver"] is None


def test_a_version_saved_for_a_sku_before_adr_0027_offers_its_targets_as_the_zones(make_client, owner):
    c = make_client()
    prop = c.get("/api/v1/config/rules/proposal").json()
    zones = monitored_zones(c)
    with owner.connect() as conn:  # as the version was written before migration 0011 refused SKUs
        conn.execute("ALTER TABLE parameter_rule DROP CONSTRAINT parameter_rule_no_sku")
        settings = {"pause_when_stopped": {"enabled": True, "long_stop_min": 10, "warmup_min": 30}, "defaults": DEFAULTS}
        rows = [{"sku": None, "parameter_id": r["parameterId"], "zone_id": None, "warn_low": r["warnLow"], "warn_high": r["warnHigh"],
                 "crit_low": r["critLow"], "crit_high": r["critHigh"]} for r in prop["rules"]]
        rows += [{"sku": "12345", "parameter_id": p, "zone_id": z, "target": 200 + i} for i, (p, z) in enumerate(zones)]
        full = [{**{f: None for f in rules_mod.FIELDS}, **r} for r in rows]
        reg = conn.execute("SELECT id FROM register_version ORDER BY seq DESC LIMIT 1").fetchone()["id"]
        vid = uuid7()
        conn.execute("""INSERT INTO config_version (id, number, register_version_id, settings, sha256, reason)
                        VALUES (%s, 1, %s, %s, %s, 'test')""", (vid, reg, Jsonb(settings), rules_mod.digest(settings, full)))
        for r in full:
            conn.execute(f"""INSERT INTO parameter_rule (config_version_id, legacy_sku_code, parameter_id, zone_id, {', '.join(rules_mod.FIELDS)})
                             VALUES (%s, %s, %s, %s{', %s' * len(rules_mod.FIELDS)})""",
                         (vid, r["sku"], r["parameter_id"], r["zone_id"], *(r[f] for f in rules_mod.FIELDS)))
        conn.commit()
    v1 = c.get("/api/v1/config/versions/1").json()
    assert v1["intact"]  # its fingerprint still counts the SKU rows
    assert all("sku" not in r for r in v1["rules"]) and all(r["zoneId"] is None for r in v1["rules"])  # judged: limits only
    assert len(v1["gaps"]) == len(zones) and all(g["missing"] == ["target"] for g in v1["gaps"])
    assert v1["carryOver"]["from"] == "12345"
    carried = {(r["parameterId"], r["zoneId"]): r["target"] for r in v1["carryOver"]["rules"] if r["zoneId"]}
    assert carried == {(p, z): 200 + i for i, (p, z) in enumerate(zones)}


def test_a_tampered_version_reads_as_not_intact(make_client, owner):
    c = make_client()
    first_version(c)
    with owner.connect() as conn:  # only a superuser can switch the triggers off; the services' role can't (ADR-0020)
        conn.execute("SET session_replication_role = replica")
        conn.execute("UPDATE parameter_rule SET warn_low = 9 WHERE parameter_id = 'P02'")
        conn.commit()
    assert c.get("/api/v1/config/versions/1").json()["intact"] is False


def test_without_the_database_nobody_can_sign_in_and_nothing_is_saved(mock_timebase, tmp_path):
    # Sessions live in the database (DD-06, ADR-0016), so without it only the liveness check answers
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = make_settings(mock_timebase[1], tmp_path, replace(DatabaseConfig(), port=port, connect_timeout_s=1))
    c = new_client(create_app(settings))
    assert c.get("/api/v1/health/live").json() == {"status": "ok"}
    for method, path, body in (("post", "/api/v1/auth/login", {"name": "a", "password": "b"}),
                               ("get", "/api/v1/analytics/options", None), ("get", "/api/v1/config/rules", None),
                               ("put", "/api/v1/config/connections/mqtt", {"host": "broker", "subscriptions": ["#"]})):
        r = getattr(c, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 503 and "docker compose" in r.json()["detail"], path
    assert not (tmp_path / "config" / "connections.json").exists()


def test_the_old_change_history_is_imported_once(make_client, tmp_path):
    history = tmp_path / "config" / "history"
    history.mkdir(parents=True)
    old = [{"at": "2026-09-29T23:31:52Z", "user": None, "action": "connections.mqtt", "reason": None,
            "summary": "MQTT broker set to 10.0.0.1:1883 · TLS on · user a"},
           {"at": "2026-09-29T23:35:08Z", "user": None, "action": "connections.mqtt", "reason": None,
            "summary": "MQTT broker set to 10.0.0.1:1883 · TLS off · user a"}]
    (history / "audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in old))
    make_client()
    entries = make_client().get("/api/v1/config/register").json()["audit"]  # started twice: imported once
    assert [e["summary"] for e in entries].count(old[1]["summary"]) == 1
    imported = [e for e in entries if e["action"] == "connections.mqtt"]
    assert [e["at"] for e in imported] == ["2026-09-29T23:35:08Z", "2026-09-29T23:31:52Z"]
    assert any(e["action"] == "register.import" for e in entries)
    assert (history / "audit.jsonl").exists()  # left as it was


def test_health_shows_whether_monitor_core_is_alive_and_judging(make_client, database):
    c = make_client()
    assert c.get("/api/v1/health").json()["monitor"] is None  # never ran
    with database.connect() as conn:
        conn.execute("""INSERT INTO monitor_heartbeat (instance, started_at, beat_at, status)
                        VALUES ('pc', now(), now(), '{"judging": false, "reasons": ["No tag mapping is in effect (Configuration → Mappings)"]}')""")
        conn.commit()
    monitor = c.get("/api/v1/health").json()["monitor"]
    assert monitor["alive"] and monitor["judging"] is False and "No tag mapping" in monitor["reasons"][0]
