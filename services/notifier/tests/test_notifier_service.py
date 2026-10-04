"""The notifier end to end (ADR-0023, AT-06): its lanes against a fake Power Automate flow and a fake SMTP relay."""

from __future__ import annotations

import email
import email.policy
import threading
import time
from datetime import timedelta

from centerline_notifier.service import NotifierSettings, Service, utcnow

from .conftest import ALL_TYPES, SIG, notify, use_routing, write_channels

ROUTING = [{"name": "Management on Teams", "types": ALL_TYPES, "channel": "teams", "targets": ["Centerline alerts"]},
           {"name": "Management by email", "types": ALL_TYPES, "channel": "email", "targets": ["boss@plant.test"]}]
CRITICAL = {"kind": "Actual Critical", "parameter": "P03", "parameterName": "Bottom Temperature", "zone": "REAR",
            "zoneName": "Rear", "unit": "°C", "sku": "67890123", "actual": "191", "hmi": "180"}


class Clock:
    """The notifier's clock, which a test can move on to skip a retry's wait."""

    def __init__(self):
        self.offset = timedelta()

    def __call__(self):
        return utcnow() + self.offset


def parse(data: bytes):
    return email.message_from_bytes(data, policy=email.policy.default)


def running(database, config_dir, clock=None):
    service = Service(NotifierSettings(database=database, config_dir=config_dir, instance="test", poll_s=0.1, heartbeat_s=0.3),
                      clock=clock or utcnow)
    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    return service, thread


def wait_for(conn, sql: str, until, timeout: float = 10):
    deadline = time.time() + timeout
    while True:
        rows = conn.execute(sql).fetchall()
        conn.commit()
        if until(rows) or time.time() > deadline:
            return rows
        time.sleep(0.1)


STATUSES = "SELECT channel, status, last_error, message_id FROM notification_delivery ORDER BY channel"


def test_a_message_reaches_teams_and_email_and_each_attempt_is_kept(database, tmp_path, teams, smtp):
    write_channels(tmp_path, teams_url=teams.url, smtp_port=smtp.port)
    with database.connect() as conn:
        use_routing(conn, ROUTING)
        notify(conn, "initial", CRITICAL, key="e1:initial")
        service, thread = running(database, tmp_path)
        try:
            rows = wait_for(conn, STATUSES, lambda r: [x["status"] for x in r] == ["SUBMITTED", "DELIVERED"])
            beat = wait_for(conn, "SELECT status FROM notifier_heartbeat", lambda r: r and r[0]["status"]["lanes"]["email"]["lastOk"])
        finally:
            service.stop()
            thread.join(10)
        assert [x["status"] for x in rows] == ["SUBMITTED", "DELIVERED"]
        (posted,) = teams.received
        assert posted["json"]["dedupKey"] == "e1:initial:teams:Centerline alerts" and posted["json"]["severity"] == "CRITICAL"
        assert posted["json"]["card"]["body"][0]["text"] == "Actual Critical · Bottom Temperature · Rear · Volpak"
        (sent,) = smtp.messages
        mail = parse(sent["data"])
        assert (sent["to"], mail["Message-ID"], mail["Subject"]) == ("boss@plant.test", rows[0]["message_id"],
                                                                     "Actual Critical · Bottom Temperature · Rear · Volpak")
        assert "ref e1:initial" in mail.get_content()
        attempts = conn.execute("SELECT outcome, response FROM delivery_attempt ORDER BY outcome").fetchall()
        assert [a["outcome"] for a in attempts] == ["delivered", "submitted"] and "queued as Q1" in attempts[1]["response"]
        assert beat[0]["status"]["lanes"]["teams"]["configured"]
        assert beat[0]["status"]["backlog"] == {"email": {"waiting": 0, "failed": 0}, "teams": {"waiting": 0, "failed": 0}}


def test_a_teams_outage_doesnt_hold_up_email_and_never_shows_the_flows_signature(database, tmp_path, teams, smtp):
    teams.status = 500
    write_channels(tmp_path, teams_url=teams.url, smtp_port=smtp.port)
    with database.connect() as conn:
        use_routing(conn, ROUTING)
        notify(conn, "initial", CRITICAL, key="e1:initial")
        service, thread = running(database, tmp_path)
        try:
            rows = wait_for(conn, STATUSES, lambda r: [x["status"] for x in r] == ["SUBMITTED", "RETRYING"])
        finally:
            service.stop()
            thread.join(10)
        assert [x["status"] for x in rows] == ["SUBMITTED", "RETRYING"]
        assert rows[1]["last_error"].startswith("HTTP 500") and "127.0.0.1" in rows[1]["last_error"]
        kept = " ".join(r["response"] for r in conn.execute("SELECT response FROM delivery_attempt"))
        assert SIG not in kept + rows[1]["last_error"] and "triggers" not in kept  # no path, no signature


def test_a_relay_that_drops_before_its_250_gets_the_same_message_again(database, tmp_path, smtp):
    smtp.drops = 1
    write_channels(tmp_path, smtp_port=smtp.port)
    clock = Clock()
    with database.connect() as conn:
        use_routing(conn, [ROUTING[1]])
        notify(conn, "initial", CRITICAL, key="e1:initial")
        service, thread = running(database, tmp_path, clock)
        try:
            wait_for(conn, STATUSES, lambda r: r and r[0]["status"] == "RETRYING")
            clock.offset = timedelta(seconds=31)  # the 30 s wait has passed
            rows = wait_for(conn, STATUSES, lambda r: r and r[0]["status"] == "SUBMITTED")
        finally:
            service.stop()
            thread.join(10)
        assert rows[0]["status"] == "SUBMITTED"
        (dropped,), (sent,) = smtp.dropped, smtp.messages
        assert parse(dropped)["Message-ID"] == parse(sent["data"])["Message-ID"] == rows[0]["message_id"]
        assert [a["outcome"] for a in conn.execute("SELECT outcome FROM delivery_attempt ORDER BY attempt")] == ["failed", "submitted"]


def test_a_channel_not_set_up_waits_and_says_so(database, tmp_path):
    write_channels(tmp_path)
    with database.connect() as conn:
        use_routing(conn, [ROUTING[0]])
        notify(conn)
        service, thread = running(database, tmp_path)
        try:
            rows = wait_for(conn, STATUSES, lambda r: r and r[0]["status"] == "RETRYING")
        finally:
            service.stop()
            thread.join(10)
        assert rows[0]["last_error"] == "Teams isn't set up on Configuration → Connections"
