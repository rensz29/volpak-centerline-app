"""AT-07: offline core operation, buffer replay, storage degraded mode and restart recovery.

URS v1.1 §2 (DEP-02, DEP-03, DEP-05), §9 (RES-01, RES-02) and §12 (MNT-02), as built in ADR-0014, ADR-0018 and
ADR-0036. monitor-core's engine and its database writer judge the simulated line; the api answers as the web app
calls it. The backups (BKP-01/02) have their own tests (services/backup_agent/tests) and a restore drill
(deploy/README.md); DEP-05, starting without anyone signed in, needs the control-room PC (G0b).
"""

from __future__ import annotations

import base64
import json
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from centerline_api.main import create_app
from centerline_monitor.engine import Engine
from centerline_monitor.service import Service
from centerline_monitor.storage import StorageGuard
from centerline_monitor.store import Store
from .conftest import AT_THE_LINE, SERVICES, Plant, _load, add_account, api, configure, new_client, sign_in

samples = _load("acceptance_ocap_samples_at07", SERVICES / "api" / "tests" / "ocap_samples.py")
REQUESTS = "/api/v1/workflow/requests"
OCAPS = "/api/v1/ocaps"
QUERY = {"from": "2026-09-01T18:00:00Z", "to": "2026-09-02T06:00:00Z", "x": "P02.V1.actual", "y": "P02.V2.actual"}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def rows(database, sql: str, params: tuple = ()) -> list[dict]:
    with database.connect() as conn:
        return conn.execute(sql, params).fetchall()


def operator(make_client):
    return make_client(roles=["OPERATOR"], address="10.0.0.5", auth=AT_THE_LINE)


def upload(client, code: str):
    return client.post(OCAPS, json={"code": code, "title": "Bottom sealing temperature", "language": "en", "source": f"{code}.docx",
                                    "contentBase64": b64(samples.bottom_docx()), "reason": "From the quality binder"})


def mismatch(p, channel: str = "P02.V1", setpoint: float = 222, offline: bool = False) -> None:
    p.line.set(channel, setpoint=setpoint)
    (judge if offline else Plant.run)(p, p.t + 31)


def judge(p, until: float) -> None:
    """monitor-core's loop while the database is away: the line publishes and timers fire. The workflow's tick needs
    the database, so the loop leaves it until it's back, as here."""
    while p.t < until:
        p.t = min(p.t + 1.0, until)
        p.line.publish(p.engine, p.at(p.t))
        p.engine.tick(p.at(p.t))


# -- Offline core operation ----------------------------------------------------------------------------------------

@pytest.mark.urs("DEP-02", "DEP-03")
def test_without_internet_the_core_judges_signs_in_runs_the_reason_workflow_audits_and_reads_ocaps(
        mock_timebase, tmp_path, database, make_client, plant):
    # The plant LAN only: Timebase out of reach, no notifier running, no AI. Only Teams and email need the WAN (A-10)
    offline = new_client(create_app(api.make_settings(f"http://127.0.0.1:{closed_port()}", tmp_path, database)))
    sign_in(offline, add_account(offline.app, database, ["MANAGER", "ADMINISTRATOR"]))
    configure(offline)
    manager = offline
    assert upload(manager, "OCAP-030").status_code == 201  # the OCAP library is local

    p = plant()
    mismatch(p)  # monitor-core judges with no api call and no delivery worker (DEP-03)
    (event,) = offline.get("/api/v1/events?open=true").json()["events"]
    assert event["kind"] == "HMI_MISMATCH"
    queued = rows(database, "SELECT n.kind FROM notification n WHERE n.event_id = %s", (event["id"],))
    assert [r["kind"] for r in queued] == ["initial"]  # waiting in the outbox for the WAN; nothing else waits for it

    op = operator(make_client)  # a local account at the line desk (IAM-01)
    (req,) = op.get(REQUESTS).json()["requests"]
    op.post(f"{REQUESTS}/{req['id']}/reason", json={"text": "New film roll"})
    req = op.post(f"{REQUESTS}/{req['id']}/answers", json={"answers": ["Raised it by 2 °C", "No"]}).json()
    if req["next"] == "ocap":
        req = op.post(f"{REQUESTS}/{req['id']}/ocap", json={"sectionId": None}).json()  # the draft isn't Active
    assert manager.post(f"{REQUESTS}/{req['id']}/guidance", json={"text": "Back to 220 °C"}).json()["next"] == "acknowledgment"
    assert op.post(f"{REQUESTS}/{req['id']}/acknowledge").json()["status"] == "done"
    assert op.get(f"{OCAPS}?q=bottom").status_code == 200  # local OCAP access

    assert rows(database, "SELECT audit_log_verify() AS broken")[0]["broken"] is None  # the audit chain holds
    analytics = offline.post("/api/v1/analytics/query", json=QUERY)
    assert analytics.status_code >= 500 and "Timebase" in analytics.text  # history waits for Timebase; nothing else does


# -- Buffer replay -----------------------------------------------------------------------------------------------------

def cut_off(store) -> None:
    """The database goes away: nothing answers on its port."""
    store.database = replace(store.database, port=closed_port(), connect_timeout_s=1)
    if store.conn is not None:
        store.conn.close()


@pytest.mark.urs("RES-01")
def test_a_database_outage_is_journalled_to_protected_disk_and_replayed_in_order_once(make_client, plant, database):
    configure(make_client())
    p = plant()
    real = p.store.database
    cut_off(p.store)
    mismatch(p, "P02.V3", 217, offline=True)  # opens while nothing can be written
    p.line.set("P02.V3", setpoint=215)
    judge(p, p.t + 16)  # and resolves, still in the dark
    journal = p.store.journal.path
    assert p.store.journal.steps >= 2 and not rows(database, "SELECT 1 FROM event")
    assert (journal.stat().st_mode & 0o777, journal.parent.stat().st_mode & 0o777) == (0o600, 0o700)

    saved = journal.read_bytes()
    p.store.database = real
    assert p.store.drain(p.at(p.t), force=True)
    states = [r["state"] for r in rows(database, "SELECT state FROM event_transition ORDER BY seq")]
    assert states == ["OPEN", "RESOLVED"]  # in the order they were judged

    # A replay cut short by a crash runs again from the start: still one event, one transition each, one message each
    journal.write_bytes(saved)
    p.store.journal = type(p.store.journal)(journal)
    assert p.store.drain(p.at(p.t + 1), force=True)
    assert len(rows(database, "SELECT 1 FROM event")) == 1
    assert [r["state"] for r in rows(database, "SELECT state FROM event_transition ORDER BY seq")] == ["OPEN", "RESOLVED"]
    kinds = [r["kind"] for r in rows(database, "SELECT kind FROM notification ORDER BY created_at")]
    assert len(kinds) == len(set(kinds))


@pytest.mark.urs("RES-01")
def test_past_the_journals_30_minutes_judging_pauses_and_nothing_judged_is_dropped(make_client, plant, database):
    configure(make_client())
    p = plant()
    real = p.store.database
    cut_off(p.store)
    mismatch(p, "P02.V3", 217, offline=True)  # judged and journalled
    loop = SimpleNamespace(store=p.store, settings=SimpleNamespace(journal_limit_s=1800))
    assert Service._degraded(loop, p.at(p.t + 60)) is None
    reason = Service._degraded(loop, p.at(p.t + 1801))
    assert "longer than the journal's 30 min" in reason
    p.engine.set_degraded(reason, p.at(p.t + 1801))
    assert not p.engine.status()["judging"] and p.engine.status()["reasons"][0] == reason
    p.store.database = real
    assert p.store.drain(p.at(p.t + 1802), force=True)
    assert len(rows(database, "SELECT 1 FROM event")) == 1  # what was judged before the pause is all there


# -- Storage degraded mode ---------------------------------------------------------------------------------------------

class Disk:
    def __init__(self, pct: float):
        self.pct = pct

    def __call__(self, _path: Path) -> float:
        return self.pct


@pytest.mark.urs("RES-02")
def test_storage_degraded_mode_stops_uploads_brief_changes_and_the_query_log_and_everything_else_carries_on(
        make_client, plant, database, tmp_path):
    owner = make_client()  # Manager and Administrator
    configure(owner)
    p = plant()
    disk = Disk(95)
    guard = StorageGuard([tmp_path], measure=disk)

    def beat(seconds: float) -> dict:
        """monitor-core's minute: measure, alert, set the mode, and the heartbeat every page reads."""
        now = p.at(seconds)
        alerts = guard.check(now)
        p.engine.storage_degraded = guard.degraded
        p.engine.emit(alerts, now)
        p.store.heartbeat(datetime.now(timezone.utc), p.start, {**p.engine.status(), "storage": guard.status()})
        return owner.get("/api/v1/events/counts").json()["storage"]

    # 90 %: the cleanup's ten minutes; nothing is refused yet
    assert beat(0)["state"] == "cleanup"  # the guard's own clock moves on, a minute at a time, as monitor-core's loop
    assert upload(owner, "OCAP-031").status_code == 201

    # Still 90 % after ten minutes: protected degraded mode (O-12)
    assert beat(600)["state"] == "degraded"
    refused = upload(owner, "OCAP-032")
    assert (refused.status_code, refused.json()["type"]) == (507, "/problems/storage-full")
    file = {"name": "plan.docx", "contentBase64": b64(samples.bottom_docx())}
    guided = owner.post(f"{REQUESTS}/{uuid4()}/guidance", json={"text": "Back to target", "attachment": file})
    assert guided.status_code == 507  # a guidance file too; its text alone isn't an upload
    logged = (tmp_path / "audit.jsonl").read_text().count("\n") if (tmp_path / "audit.jsonl").exists() else 0
    assert owner.post("/api/v1/analytics/query", json=QUERY).status_code == 200  # Analytics answers…
    after = (tmp_path / "audit.jsonl").read_text().count("\n") if (tmp_path / "audit.jsonl").exists() else 0
    assert after == logged  # …without the query log

    p.line.set("P03.FRONT", setpoint=182)  # a brief change: back before its delay
    p.run(p.t + 12)
    p.line.set("P03.FRONT", setpoint=180)
    p.run(p.t + 30)
    assert not rows(database, "SELECT 1 FROM lightweight_change") and p.engine.briefs_skipped == 1
    mismatch(p)  # monitoring, events and notifications carry on
    assert [r["kind"] for r in rows(database, "SELECT kind FROM event WHERE kind = 'HMI_MISMATCH'")] == ["HMI_MISMATCH"]
    alerts = [r["payload"]["kind"] for r in rows(database, "SELECT payload FROM notification WHERE kind = 'system' ORDER BY created_at")]
    assert alerts == ["Storage at the cleanup limit (RES-02)", "Protected degraded mode: storage full (RES-02)"]

    # Freed below 85 %: degraded mode ends, said so, and uploads are kept again
    disk.pct = 84
    assert beat(700)["state"] == "warning"
    assert upload(owner, "OCAP-032").status_code == 201
    assert rows(database, "SELECT payload FROM notification WHERE kind = 'system' ORDER BY created_at")[-1]["payload"]["kind"] \
        == "Storage back under its limits (RES-02)"
    assert rows(database, "SELECT audit_log_verify() AS broken")[0]["broken"] is None  # nothing protected touched


# -- Restart recovery --------------------------------------------------------------------------------------------------

@pytest.mark.urs("MNT-02")
def restart(p: Plant, database, folder: Path, after_s: float) -> Plant:
    """monitor-core stops and starts again `after_s` later, as the service does: its open events from the database, its
    timers from zero. The machine's values are as they were: it didn't stop with monitor-core."""
    start = p.at(p.t + after_s)
    store = Store(database, folder, "acceptance", journal_path=folder / "journal.jsonl")
    store.start(start - timedelta(seconds=1))
    engine = Engine(store.config(), store, start - timedelta(seconds=1))
    engine.restore(store.open_events(), start - timedelta(seconds=1))
    engine.set_connected(True, start - timedelta(seconds=1))
    p.line.publish(engine, start)
    return Plant(engine, store, p.line, start, names=engine.zone_names())


@pytest.mark.urs("MNT-02")
def test_after_a_restart_open_events_carry_on_delays_start_from_zero_and_no_first_notice_is_sent_twice(make_client, plant, database, tmp_path):
    configure(make_client())
    p = plant()
    mismatch(p, "P02.V1", 222)  # an open event, its first notice sent
    p.line.set("P02.V2", setpoint=212)
    p.run(p.t + 20)  # a second zone 20 s into its 30 s delay
    (first,) = rows(database, "SELECT id FROM event")

    q = restart(p, database, tmp_path / "monitor-core", after_s=5)
    q.run(20)
    assert [r["id"] for r in rows(database, "SELECT id FROM event")] == [first["id"]]  # the old 20 s don't count
    q.run(31)
    events = rows(database, "SELECT e.id, s.open FROM event e JOIN event_state s ON s.event_id = e.id ORDER BY e.opened_at")
    assert len(events) == 2 and all(e["open"] for e in events)  # the restored event is still open
    initial = rows(database, "SELECT event_id FROM notification WHERE kind = 'initial'")
    assert sorted(str(r["event_id"]) for r in initial) == sorted(str(e["id"]) for e in events)  # one first notice each


@pytest.mark.urs("DEP-05")
def test_services_start_after_a_windows_restart_without_anyone_signed_in():
    pytest.skip("Needs the control-room PC: the host test and its boot test (deploy/host-check, gate G0b). Docker Desktop on "
                "this laptop needs a Windows session (deploy/README.md)")
