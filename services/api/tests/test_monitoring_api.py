"""The Digital Centerline page's api (ADR-0015): monitor-core's live state, its events, and a Manager's
acknowledgment of a Critical (ADR-0016, ACT-04)."""

from __future__ import annotations

from centerline_common.db import uuid7
from psycopg.types.json import Jsonb


def versions(conn):
    rid = conn.execute("SELECT id FROM register_version ORDER BY seq DESC LIMIT 1").fetchone()["id"]
    cid, mid = uuid7(), uuid7()
    conn.execute("INSERT INTO config_version (id, number, register_version_id, settings, sha256, reason) VALUES (%s, 3, %s, '{}', 'x', 't')",
                 (cid, rid))
    conn.execute("INSERT INTO mapping_version (id, number, register_version_id, source, sha256, reason) VALUES (%s, 2, %s, 't', 'x', 't')",
                 (mid, rid))
    return cid, mid, rid


def event(conn, v, kind, pid, zid, state, severity=None, open_=True, hmi=None, actual=None):
    eid = uuid7()
    conn.execute("""INSERT INTO event (id, kind, parameter_id, zone_id, opened_at, severity, raw_target, raw_hmi, raw_actual,
                                       config_version_id, mapping_version_id, register_version_id, rule)
                    VALUES (%s, %s, %s, %s, now() - interval '5 min', %s, 180, %s, %s, %s, %s, %s, %s)""",
                 (eid, kind, pid, zid, severity, hmi, actual, *v, Jsonb({"rules_version": 3})))
    conn.execute("INSERT INTO event_state (event_id, state, severity, open, updated_at, closed_at) VALUES (%s, %s, %s, %s, now(), %s)",
                 (eid, state, severity, open_, None if open_ else "2026-10-01T00:00:00Z"))
    conn.execute("INSERT INTO event_transition (id, event_id, seq, at, state, inputs) VALUES (%s, %s, 1, now() - interval '5 min', %s, %s)",
                 (uuid7(), eid, severity or "OPEN", Jsonb({"hmi": str(hmi)})))
    return eid


def beat(conn, age_s=1, zones=None):
    conn.execute("""INSERT INTO monitor_heartbeat (instance, started_at, beat_at, status)
                    VALUES ('pc', now() - interval '1 hour', now() - make_interval(secs => %s), %s)
                    ON CONFLICT (instance) DO UPDATE SET beat_at = EXCLUDED.beat_at, status = EXCLUDED.status""",
                 (age_s, Jsonb({"judging": True, "reasons": [], "rulesVersion": 3, "zones": zones or {}})))


def test_without_monitor_core_every_zone_is_unknown(make_client):
    body = make_client().get("/api/v1/monitoring/live").json()
    assert body["monitor"] is None and body["counts"] == {"zones": 14, "hmiOpen": 0, "warning": 0, "critical": 0}
    zones = [z for p in body["parameters"] for z in p["zones"]]
    assert len(zones) == 14 and not any(z["known"] for z in zones)
    assert body["parameters"][0]["name"] == "Vertical Temperature" and body["parameters"][0]["zones"][0]["name"] == "Vertical 1"


def test_live_state_combines_the_heartbeat_with_the_open_events(make_client, database):
    c = make_client()
    with database.connect() as conn:
        v = versions(conn)
        critical = event(conn, v, "ACTUAL", "P03", "FRONT", "CRITICAL", "CRITICAL", hmi=180, actual=191.5)
        mismatch = event(conn, v, "HMI_MISMATCH", "P02", "V1", "OPEN", hmi=222)
        event(conn, v, "HMI_MISMATCH", "P02", "V2", "RESOLVED", open_=False, hmi=217)
        beat(conn, zones={"P03.FRONT": {"setpoint": "180", "actual": "191.5", "target": "180", "actualSeverity": "CRITICAL",
                                        "hmi": "AT_TARGET", "bands": {"warnLow": "175", "warnHigh": "185", "critLow": "170", "critHigh": "190"}}})
        conn.commit()
    body = c.get("/api/v1/monitoring/live").json()
    assert body["monitor"]["alive"] and body["monitor"]["judging"] and "sku" not in body["monitor"]
    assert body["counts"] == {"zones": 14, "hmiOpen": 1, "warning": 0, "critical": 1}
    front = next(z for p in body["parameters"] for z in p["zones"] if z["channel"] == "P03.FRONT")
    assert front["known"] and front["actual"] == "191.5" and front["actualSeverity"] == "CRITICAL" and front["events"] == [str(critical)]
    kinds = {e["id"]: (e["kind"], e["zoneName"], e["actual"] or e["hmi"]) for e in body["events"]}
    assert kinds == {str(critical): ("ACTUAL", "Front bottom", "191.5"), str(mismatch): ("HMI_MISMATCH", "Vertical 1", "222")}


def test_a_stale_heartbeat_means_nothing_is_known(make_client, database):
    c = make_client()
    with database.connect() as conn:
        beat(conn, age_s=120, zones={"P03.FRONT": {"actual": "180"}})
        conn.commit()
    body = c.get("/api/v1/monitoring/live").json()
    assert body["monitor"]["alive"] is False and body["monitor"]["ageS"] >= 120
    assert not any(z["known"] for p in body["parameters"] for z in p["zones"])


def test_event_lists_details_and_brief_changes(make_client, database):
    c = make_client()
    with database.connect() as conn:
        v = versions(conn)
        closed = event(conn, v, "HMI_MISMATCH", "P02", "V2", "RESOLVED", open_=False, hmi=217)
        event(conn, v, "ACTUAL", "P06", "N1", "WARNING", "WARNING", actual=108)
        conn.execute("""INSERT INTO notification (id, dedup_key, kind, event_id, created_at, payload) VALUES (%s, %s, 'initial', %s, now(), '{}')""",
                     (uuid7(), f"{closed}:initial", closed))
        conn.execute("""INSERT INTO lightweight_change (id, parameter_id, zone_id, mode, started_at, ended_at, raw_target, raw_hmi,
                                                        config_version_id, mapping_version_id)
                        VALUES (%s, 'P04', 'FRONT', 'lightweight', now() - interval '20 s', now(), 185, 187, %s, %s)""",
                     (uuid7(), v[0], v[1]))
        conn.commit()
    assert [e["kind"] for e in c.get("/api/v1/events", params={"open": "false"}).json()["events"]] == ["HMI_MISMATCH"]
    detail = c.get(f"/api/v1/events/{closed}").json()
    assert detail["versions"] == {"rules": 3, "mapping": 2, "register": detail["versions"]["register"]}
    assert [t["state"] for t in detail["transitions"]] == ["OPEN"] and detail["notifications"][0]["kind"] == "initial"
    assert (detail["notifications"][0]["status"], detail["notifications"][0]["deliveries"]) == ("pending", [])  # not routed yet
    assert c.get(f"/api/v1/events/{uuid7()}").status_code == 404
    (brief,) = c.get("/api/v1/monitoring/brief-changes").json()["briefChanges"]
    assert (brief["zoneName"], brief["hmi"], brief["seconds"]) == ("Front top 1", "187", 20.0)


def test_a_manager_acknowledges_an_open_critical_once_per_critical_period(make_client, database):
    manager, admin = make_client(roles=["MANAGER"]), make_client(roles=["ADMINISTRATOR"])
    me = manager.get("/api/v1/auth/session").json()["user"]["username"]
    with database.connect() as conn:
        v = versions(conn)
        critical = event(conn, v, "ACTUAL", "P06", "N1", "CRITICAL", "CRITICAL", hmi=98, actual=117)
        warning = event(conn, v, "ACTUAL", "P06", "N2", "WARNING", "WARNING", hmi=98, actual=108)
        mismatch = event(conn, v, "HMI_MISMATCH", "P02", "V1", "OPEN", hmi=222)
        closed = event(conn, v, "ACTUAL", "P06", "N3", "RESOLVED", "CRITICAL", open_=False, hmi=98, actual=98)
        conn.commit()
    assert admin.post(f"/api/v1/events/{critical}/acknowledge", json={}).status_code == 403  # a Manager's (ACT-04)
    for e, why in ((warning, "Only an open Critical"), (mismatch, "Only an open Critical"), (closed, "closed")):
        r = manager.post(f"/api/v1/events/{e}/acknowledge", json={})
        assert r.status_code == 409 and why in r.json()["detail"], e
    assert manager.get(f"/api/v1/events/{critical}").json()["acknowledgeable"] is True

    r = manager.post(f"/api/v1/events/{critical}/acknowledge", json={"note": "Nozzle cleaned"})
    assert r.status_code == 202 and (r.json()["acknowledgedBy"], r.json()["criticalPeriod"]) == (me, 1)
    assert manager.post(f"/api/v1/events/{critical}/acknowledge", json={}).status_code == 409  # once per period
    detail = manager.get(f"/api/v1/events/{critical}").json()
    assert [(a["by"], a["note"], a["criticalPeriod"]) for a in detail["acknowledgments"]] == [(me, "Nozzle cleaned", 1)]
    assert detail["acknowledgeable"] is False
    entry = manager.get("/api/v1/config/register").json()["audit"][0]
    assert (entry["action"], entry["user"], entry["reason"]) == ("event.acknowledge", me, "Nozzle cleaned")

    with database.connect() as conn:  # down to Warning and Critical again: a new period needs its own
        conn.execute("""INSERT INTO event_transition (id, event_id, seq, at, state, inputs)
                        VALUES (%s, %s, 2, now(), 'WARNING', '{}'), (%s, %s, 3, now(), 'CRITICAL', '{}')""",
                     (uuid7(), critical, uuid7(), critical))
        conn.commit()
    r = manager.post(f"/api/v1/events/{critical}/acknowledge", json={})
    assert r.status_code == 202 and r.json()["criticalPeriod"] == 2


def test_the_history_filters_pages_counts_and_exports(make_client, database):
    c = make_client()
    with database.connect() as conn:
        v = versions(conn)
        ids = [event(conn, v, "HMI_MISMATCH", "P02", f"V{n}", "RESOLVED", open_=False, hmi=217) for n in range(1, 6)]
        critical = event(conn, v, "ACTUAL", "P06", "N1", "CRITICAL", "CRITICAL", hmi=98, actual=117)
        event(conn, v, "ACTUAL", "P06", "N2", "WARNING", "WARNING", hmi=98, actual=108)
        conn.commit()
    first = c.get("/api/v1/events", params={"open": "false", "limit": 2}).json()
    second = c.get("/api/v1/events", params={"open": "false", "limit": 2, "before": first["next"]}).json()
    rest = c.get("/api/v1/events", params={"open": "false", "limit": 2, "before": second["next"]}).json()
    seen = [e["id"] for page in (first, second, rest) for e in page["events"]]
    assert sorted(seen) == sorted(str(i) for i in ids) and len(set(seen)) == 5 and rest["next"] is None
    assert [e["id"] for e in c.get("/api/v1/events", params={"kind": "ACTUAL", "severity": "CRITICAL"}).json()["events"]] == [str(critical)]
    assert [e["zoneId"] for e in c.get("/api/v1/events", params={"channel": "P02.V3"}).json()["events"]] == ["V3"]
    with database.connect() as conn:  # the Warning went Critical once and back: it still reached Critical
        warning = conn.execute("SELECT event_id FROM event_state WHERE severity = 'WARNING'").fetchone()["event_id"]
        conn.execute("INSERT INTO event_transition (id, event_id, seq, at, state, inputs) VALUES (%s, %s, 2, now(), 'CRITICAL', '{}')",
                     (uuid7(), warning))
        conn.commit()
    reached = c.get("/api/v1/events", params={"reached": "CRITICAL"}).json()["events"]
    assert {e["id"] for e in reached} == {str(critical), str(warning)}
    assert c.get("/api/v1/events", params={"before": "nonsense"}).status_code == 422
    # No heartbeat here, so no storage reading for the pages' banner (ADR-0036)
    assert c.get("/api/v1/events/counts").json() == {"open": 2, "hmi": 0, "warning": 1, "critical": 1, "unacknowledgedCritical": 1,
                                                     "storage": None}

    r = c.get("/api/v1/events/export.csv", params={"open": "false"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="centerline-events-')
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Opened (Manila),Closed (Manila),Kind") and len(lines) == 1 + 5
    assert "+08:00" in lines[1] and ",HMI mismatch," in lines[1]
    entry = c.get("/api/v1/config/register").json()["audit"][0]
    assert entry["action"] == "events.export" and entry["summary"] == "Events exported as CSV: 5 event(s)"
