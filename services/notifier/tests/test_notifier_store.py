"""The notifier's database work (ADR-0023): routing once, the retry schedule, leases, recovery, the watcher."""

from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest
from psycopg.types.json import Jsonb

from centerline_common.channels import Outcome
from centerline_notifier import store

from .conftest import ALL_TYPES, later, notify, now, use_routing

EVERYONE = [{"name": "Management by email", "types": ALL_TYPES, "channel": "email", "targets": ["boss@plant.test", "lead@plant.test"]},
            {"name": "Management on Teams", "types": ALL_TYPES, "channel": "teams", "targets": ["Centerline alerts"]}]


def deliveries(conn) -> list[dict]:
    return conn.execute("SELECT * FROM notification_delivery ORDER BY channel, target").fetchall()


def test_without_routing_a_message_is_left_unrouted_and_never_sent_later(database):
    with database.connect() as conn:
        nid = notify(conn)
        assert store.route_pending(conn, now(), line="Volpak", app_url=None) == 1
        use_routing(conn, EVERYONE)  # routing arrives afterwards
        assert store.route_pending(conn, now(), line="Volpak", app_url=None) == 0
        route = conn.execute("SELECT outcome, routing_version FROM notification_route WHERE notification_id = %s", (nid,)).fetchone()
        assert (route["outcome"], route["routing_version"]) == ("unrouted", None) and deliveries(conn) == []


def test_a_message_is_routed_once_with_what_matched_frozen_and_a_delivery_per_channel_and_target(database):
    with database.connect() as conn:
        use_routing(conn, EVERYONE)
        nid = notify(conn, key="maintenance:w1:overdue")
        store.route_pending(conn, now(), line="Volpak", app_url="https://c")
        store.route_pending(conn, now(), line="Volpak", app_url="https://c")  # nothing twice
        route = conn.execute("SELECT * FROM notification_route WHERE notification_id = %s", (nid,)).fetchone()
        assert (route["type"], route["outcome"], route["routing_version"]) == ("system", "routed", 1)
        assert [r["name"] for r in route["matched"]] == ["Management by email", "Management on Teams"]
        ds = deliveries(conn)
        assert [(d["channel"], d["target"], d["status"]) for d in ds] == [
            ("email", "boss@plant.test", "PENDING"), ("email", "lead@plant.test", "PENDING"), ("teams", "Centerline alerts", "PENDING")]
        assert ds[0]["dedup_key"] == "maintenance:w1:overdue:email:boss@plant.test"
        assert ds[0]["content"]["subject"] == "Maintenance window overdue · Volpak" and ds[0]["content"]["link"] == "https://c/maintenance"
        assert ds[2]["content"]["teams"]["dedupKey"] == ds[2]["dedup_key"] and ds[2]["message_id"].endswith("@centerline>")


def test_a_message_over_24_hours_old_is_expired_not_sent(database):
    with database.connect() as conn:
        use_routing(conn, EVERYONE)
        notify(conn, at=now() - timedelta(hours=25))
        store.route_pending(conn, now(), line="Volpak", app_url=None)
        assert conn.execute("SELECT outcome FROM notification_route").fetchone()["outcome"] == "expired" and deliveries(conn) == []


def test_a_failing_delivery_is_retried_on_the_schedule_with_the_same_message_until_24_hours(database):
    t = now()
    with database.connect() as conn:
        use_routing(conn, [{"name": "Lead", "types": ALL_TYPES, "channel": "email", "targets": ["lead@plant.test"]}])
        notify(conn, at=t)
        store.route_pending(conn, t, line="Volpak", app_url=None)
        (first,) = deliveries(conn)
        at, waits = t, []
        for _ in range(4):
            (d,) = store.claim(conn, "email", at)
            assert d["message_id"] == first["message_id"] and d["content"] == first["content"]  # the same message every time
            assert store.claim(conn, "email", at) == []  # leased while it's attempted
            assert store.finish(conn, d, "email", Outcome(False, "421 try later"), at, at) == "RETRYING"
            nxt = conn.execute("SELECT next_attempt_at FROM notification_delivery").fetchone()["next_attempt_at"]
            waits.append(nxt - at)
            assert store.claim(conn, "email", nxt - timedelta(seconds=1)) == []  # not due yet
            at = nxt
        assert waits == [timedelta(seconds=30), timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15)]
        (d,) = store.claim(conn, "email", later(t, hours=23, minutes=50))
        assert store.finish(conn, d, "email", Outcome(False, "421 try later"), at, later(t, hours=23, minutes=50)) == "PERMANENT_FAILURE"
        attempts = conn.execute("SELECT attempt, outcome, response FROM delivery_attempt ORDER BY attempt").fetchall()
        assert [(a["attempt"], a["outcome"]) for a in attempts] == [(n, "failed") for n in range(1, 6)]
        assert conn.execute("SELECT last_error FROM notification_delivery").fetchone()["last_error"] == "421 try later"


def test_a_delivered_or_submitted_message_is_never_changed_or_sent_again(database, owner):
    t = now()
    with database.connect() as conn:
        use_routing(conn, [{"name": "Lead", "types": ALL_TYPES, "channel": "email", "targets": ["lead@plant.test"]}])
        notify(conn, at=t)
        store.route_pending(conn, t, line="Volpak", app_url=None)
        (d,) = store.claim(conn, "email", t)
        assert store.finish(conn, d, "email", Outcome(True, "250 2.0.0 queued as Q1"), t, t) == "SUBMITTED"
        assert store.claim(conn, "email", later(t, hours=1)) == []
    with owner.connect() as conn:  # the guard holds even for the database's owner (NOT-06)
        for sql in ("UPDATE notification_delivery SET status = 'RETRYING'", "UPDATE notification_delivery SET target = 'x@y.z'",
                    "DELETE FROM notification_delivery", "UPDATE delivery_attempt SET outcome = 'failed'",
                    "UPDATE notification SET payload = '{}'", "UPDATE notification_route SET outcome = 'unrouted'"):
            with pytest.raises(psycopg.errors.RestrictViolation):
                conn.execute(sql)
            conn.rollback()


def test_an_attempt_cut_short_is_tried_again_once_its_lease_runs_out(database):
    t = now()
    with database.connect() as conn:
        use_routing(conn, [{"name": "Alerts", "types": ALL_TYPES, "channel": "teams", "targets": ["Centerline alerts"]}])
        notify(conn, at=t)
        store.route_pending(conn, t, line="Volpak", app_url=None)
        (d,) = store.claim(conn, "teams", t)  # ... and the database went away before the outcome was written
        assert store.claim(conn, "teams", later(t, minutes=1)) == []
        (again,) = store.claim(conn, "teams", later(t, minutes=2))
        assert (again["attempt"], again["message_id"]) == (2, d["message_id"])
        assert conn.execute("SELECT attempt, outcome FROM delivery_attempt").fetchall() == [{"attempt": 1, "outcome": "interrupted"}]


def test_after_a_restart_deliveries_left_mid_attempt_are_due_at_once(database):
    t = now()
    with database.connect() as conn:
        use_routing(conn, [{"name": "Alerts", "types": ALL_TYPES, "channel": "teams", "targets": ["Centerline alerts"]}])
        notify(conn, at=t)
        store.route_pending(conn, t, line="Volpak", app_url=None)
        store.claim(conn, "teams", t)
        assert store.recover(conn, later(t, seconds=5)) == 1
        (d,) = store.claim(conn, "teams", later(t, seconds=5))
        assert d["attempt"] == 2
        assert conn.execute("SELECT outcome FROM delivery_attempt").fetchone()["outcome"] == "interrupted"


def beat(conn, at):
    conn.execute("""INSERT INTO monitor_heartbeat (instance, started_at, beat_at, status) VALUES ('pc', %s, %s, %s)
                    ON CONFLICT (instance) DO UPDATE SET beat_at = EXCLUDED.beat_at""", (at, at, Jsonb({})))
    conn.commit()


def test_monitor_core_going_silent_raises_one_critical_alert_and_one_notice_when_its_back(database):
    t = now()
    with database.connect() as conn:
        assert store.watch_monitor(conn, t, 60) is None  # never ran here: nothing to watch
        beat(conn, t)
        assert store.watch_monitor(conn, later(t, seconds=59), 60) is None
        silent = store.watch_monitor(conn, later(t, seconds=61), 60)
        assert silent and store.watch_monitor(conn, later(t, seconds=90), 60) is None  # once per silence
        beat(conn, later(t, seconds=120))
        back = store.watch_monitor(conn, later(t, seconds=121), 60)
        assert back == silent + ":back" and store.watch_monitor(conn, later(t, seconds=125), 60) is None
        rows = conn.execute("SELECT payload FROM notification ORDER BY created_at").fetchall()
        assert [r["payload"]["kind"] for r in rows] == ["monitor-core silent", "monitor-core back"]
        use_routing(conn, EVERYONE)
        store.route_pending(conn, later(t, seconds=125), line="Volpak", app_url=None)
        subjects = {d["content"]["subject"] for d in deliveries(conn)}
        assert subjects == {"Monitoring may be down: no heartbeat · Volpak", "Monitoring is back · Volpak"}
