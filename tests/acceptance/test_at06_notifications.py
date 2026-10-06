"""AT-06: Teams Flow bot channel and SMTP delivery, retry, deduplication and Administrator re-drive.

URS v1.1 §8 (NOT-01…07), as built in ADR-0023. monitor-core raises the alarm on the simulated line and writes the
outbox; the notifier delivers it by the routing an Administrator activated, to the channels saved on the
Connections tab. Here those are stand-ins on this PC. AT-06's sign-off runs it once more against the real flow and
relay, when IT gives them (O-05).

Teams messages are posted to the channel by the flow, as Flow bot (NOT-02). Centerline's part, shown here, is the
POST to the flow's signed HTTP trigger.
"""

from __future__ import annotations

import email
import email.policy
from datetime import datetime, timedelta, timezone

import pytest
from centerline_monitor.effects import Notify
from centerline_notifier.schedule import GIVE_UP, next_attempt
from .conftest import configure, wait_for

DELIVERIES = """SELECT d.id, d.channel, d.target, d.status, d.message_id, n.kind, n.dedup_key, n.created_at,
                       (SELECT min(a.started_at) FROM delivery_attempt a WHERE a.delivery_id = d.id) AS first_attempt
                  FROM notification_delivery d JOIN notification n ON n.id = d.notification_id ORDER BY n.created_at, d.channel"""
EVERYTHING = ["hmi_mismatch", "actual_warning", "actual_critical", "critical_repeat", "critical_escalation", "recovery",
              "reason_overdue", "system"]


def connect_channels(admin, teams, smtp) -> None:
    """What an Administrator saves on Connections → Notifications: the flow's URL and the relay."""
    r = admin.put("/api/v1/config/connections/notifications", json={
        "appUrl": "https://centerline.plant.local", "teamsUrl": teams.url, "smtpHost": "127.0.0.1", "smtpPort": smtp.port,
        "smtpSecurity": "none", "emailSender": "centerline@plant.test", "reason": "The plant's flow and relay"})
    assert r.status_code == 200, r.text


def route(admin, rules: list[dict]) -> None:
    r = admin.post("/api/v1/config/routing/versions", json={"expectedLatest": admin.get("/api/v1/config/routing").json()["latest"],
                                                            "rules": rules, "reason": "Management's channels", "activate": "now"})
    assert r.status_code == 201, r.text


MANAGEMENT = [{"name": "Management on Teams", "types": EVERYTHING, "channel": "teams", "targets": ["Centerline alerts"]},
              {"name": "Management by email", "types": EVERYTHING, "channel": "email", "targets": ["boss@plant.test"]}]


def critical_on_rear_bottom(owner, plant):
    """The line judged by monitor-core, and Rear bottom's actual leaving its band: 6 °C over its setpoint for 30 s
    (Warning, the proposal's band being 5 °C), then 15 °C over for 10 s (Critical, past 10 °C)."""
    configure(owner)
    p = plant()
    p.line.set("P03.REAR", actual=186)
    p.run(31)
    p.line.set("P03.REAR", actual=195)
    p.run(45)
    return p


def statuses(rows) -> list[tuple]:
    return [(r["kind"], r["channel"], r["status"]) for r in rows]


@pytest.mark.urs("NOT-01", "NOT-02", "NOT-03", "NOT-04", "NOT-06")
def test_an_alarm_reaches_teams_through_the_flow_and_email_through_the_relay(make_client, plant, database, tmp_path, teams,
                                                                             smtp, run_notifier):
    owner = make_client()
    connect_channels(owner, teams, smtp)
    route(owner, MANAGEMENT)
    p = critical_on_rear_bottom(owner, plant)
    with database.connect() as conn:  # the outbox row was written with its event, in the same step (NOT-03)
        rows = conn.execute("""SELECT n.kind, n.event_id, e.kind AS event_kind FROM notification n
                                 JOIN event e ON e.id = n.event_id ORDER BY n.created_at""").fetchall()
    assert [(r["kind"], r["event_kind"]) for r in rows] == [("initial", "ACTUAL"), ("escalated", "ACTUAL")]

    started = datetime.now(timezone.utc)  # the rows are waiting: the notifier sees them as soon as it runs
    run_notifier(tmp_path / "config")
    rows = wait_for(database, DELIVERIES, lambda rs: len(rs) == 4 and all(r["status"] in ("DELIVERED", "SUBMITTED") for r in rs))
    assert statuses(rows) == [("initial", "email", "SUBMITTED"), ("initial", "teams", "DELIVERED"),
                              ("escalated", "email", "SUBMITTED"), ("escalated", "teams", "DELIVERED")]
    assert all(r["first_attempt"] - started < timedelta(seconds=10) for r in rows)  # each tried within 10 s (NOT-04)

    posted = teams.received
    assert len(posted) == 2 and all("sig=" in m["path"] for m in posted)  # to the flow's signed HTTP trigger
    assert posted[1]["json"]["severity"] == "CRITICAL" and posted[1]["json"]["dedupKey"].endswith(":teams:Centerline alerts")
    mails = [email.message_from_bytes(m["data"], policy=email.policy.default) for m in smtp.messages]
    assert [m["Subject"] for m in mails] == ["Actual Warning · Bottom Temperature · Rear bottom · Volpak",
                                             "Actual Critical · Bottom Temperature · Rear bottom · Volpak"]
    assert {m["To"] for m in mails} == {"boss@plant.test"} and mails[1]["Message-ID"] == rows[2]["message_id"]


@pytest.mark.urs("NOT-03", "NOT-06")
def test_a_teams_outage_doesnt_hold_up_email_and_nothing_is_sent_twice(make_client, plant, database, tmp_path, teams, smtp,
                                                                        run_notifier):
    owner = make_client()
    connect_channels(owner, teams, smtp)
    route(owner, MANAGEMENT)
    teams.status = 500  # the flow is failing
    p = critical_on_rear_bottom(owner, plant)
    run_notifier(tmp_path / "config")
    rows = wait_for(database, DELIVERIES, lambda rs: [r["status"] for r in rs if r["channel"] == "email"] == ["SUBMITTED"] * 2
                    and all(r["status"] == "RETRYING" for r in rs if r["channel"] == "teams"))
    assert statuses(rows) == [("initial", "email", "SUBMITTED"), ("initial", "teams", "RETRYING"),
                              ("escalated", "email", "SUBMITTED"), ("escalated", "teams", "RETRYING")]

    # monitor-core writing the same step again (a replay after a restart): its dedup key keeps it one message
    with database.connect() as conn:
        first = conn.execute("SELECT dedup_key, kind, event_id, payload FROM notification ORDER BY created_at LIMIT 1").fetchone()
    p.store.apply([Notify(first["dedup_key"], first["kind"], p.at(45), first["payload"], first["event_id"])], p.at(45))
    with database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM notification").fetchone()["n"] == 2
    p.run(60)  # and the notifier keeps running: what the relay accepted is never sent again
    assert len(smtp.messages) == 2


@pytest.mark.urs("NOT-04", "NOT-05")
def test_retries_for_24_hours_then_a_permanent_failure_only_an_administrator_re_drives_with_a_reason(make_client, plant, database,
                                                                                                     tmp_path, teams, smtp,
                                                                                                     run_notifier):
    created = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
    waits = []
    for failed in range(1, 6):
        due = next_attempt(created, failed, created)
        waits.append(due - created if due else None)
    assert waits[:4] == [timedelta(seconds=30), timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15)]
    assert next_attempt(created, 40, created + GIVE_UP) is None and GIVE_UP == timedelta(hours=24)

    owner = make_client()  # Manager and Administrator
    manager = make_client(roles=["MANAGER"])
    connect_channels(owner, teams, smtp)
    route(owner, MANAGEMENT[:1])  # Teams only
    teams.status = 500
    critical_on_rear_bottom(owner, plant)
    n = run_notifier(tmp_path / "config")
    wait_for(database, DELIVERIES, lambda rs: rs and all(r["status"] == "RETRYING" for r in rs))
    n.offset = GIVE_UP + timedelta(minutes=1)  # a day of failures later
    rows = wait_for(database, DELIVERIES, lambda rs: rs and all(r["status"] == "PERMANENT_FAILURE" for r in rs))
    assert {r["status"] for r in rows} == {"PERMANENT_FAILURE"}

    did = rows[0]["id"]
    assert manager.post(f"/api/v1/deliveries/{did}/redrive", json={"reason": "Flow fixed"}).status_code == 403
    assert owner.post(f"/api/v1/deliveries/{did}/redrive", json={"reason": ""}).status_code == 422
    teams.status = 202
    assert owner.post(f"/api/v1/deliveries/{did}/redrive", json={"reason": "IT fixed the flow's connection"}).status_code == 200
    rows = wait_for(database, DELIVERIES, lambda rs: any(r["status"] == "DELIVERED" for r in rs))
    assert [r["status"] for r in rows if r["id"] == did] == ["REDRIVEN"]
    assert len([r for r in rows if r["status"] == "DELIVERED"]) == 1


@pytest.mark.urs("NOT-07")
def test_routing_by_type_and_severity_per_channel_and_only_administrators_send_test_messages(make_client, plant, database,
                                                                                            tmp_path, teams, smtp, run_notifier):
    owner = make_client()
    manager = make_client(roles=["MANAGER"])
    connect_channels(owner, teams, smtp)
    route(owner, [{"name": "Criticals on Teams", "types": ["actual_critical", "critical_repeat", "critical_escalation"],
                   "channel": "teams", "targets": ["Centerline alerts"]},
                  {"name": "Everything by email", "types": EVERYTHING, "channel": "email", "targets": ["lead@plant.test"]}])
    critical_on_rear_bottom(owner, plant)  # a Warning, then a Critical
    run_notifier(tmp_path / "config")
    rows = wait_for(database, DELIVERIES, lambda rs: len(rs) == 3 and all(r["status"] in ("DELIVERED", "SUBMITTED") for r in rs))
    assert statuses(rows) == [("initial", "email", "SUBMITTED"), ("escalated", "email", "SUBMITTED"),
                              ("escalated", "teams", "DELIVERED")]  # the Warning by email only

    test = {"channel": "email", "target": "lead@plant.test", "note": "Checking the relay"}
    assert manager.post("/api/v1/notifications/test", json=test).status_code == 403
    assert owner.post("/api/v1/notifications/test", json=test).status_code == 201
    wait_for(database, DELIVERIES, lambda rs: len(rs) == 4 and rs[-1]["status"] == "SUBMITTED")
    subjects = [email.message_from_bytes(m["data"], policy=email.policy.default)["Subject"] for m in smtp.messages]
    assert subjects[-1] == "TEST - NO PRODUCTION EVENT"
