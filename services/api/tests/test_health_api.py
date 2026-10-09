"""GET /api/v1/health (ADR-0038): the System health page's checks, from the parts as they are."""

from __future__ import annotations

from psycopg.types.json import Jsonb


def ids(body: dict) -> dict:
    return {c["id"]: c for c in body["checks"]}


def test_without_monitor_core_the_page_says_nothing_is_judged_and_the_rest_is_graded(make_client):
    body = make_client().get("/api/v1/health").json()
    c = ids(body)
    assert body["overall"] == "critical" and c["monitor"]["state"] == "critical"
    assert c["database"]["state"] == "ok" and c["audit"]["summary"] == "Intact"
    assert c["timebase"]["state"] == "ok"  # the mock Timebase answers
    assert c["scanner"]["state"] == "unknown" and c["backup"]["state"] == "unknown"  # a development setup
    assert c["outbox"]["summary"] == "Nothing waiting"


def test_monitor_cores_heartbeat_becomes_its_checks(make_client, database):
    status = {"judging": True, "connected": True, "rulesVersion": 1, "mappingVersion": 1, "reasons": [],
              "lastLive": {}, "clockSkewWarning": None, "evaluation": {"maxMs": 12, "messages": 40, "windowS": 60},
              "journal": {"steps": 0, "oldestAt": None}, "storage": {"state": "warning", "usedPct": 83.0, "error": None}}
    with database.connect() as conn:
        conn.execute("INSERT INTO monitor_heartbeat (instance, started_at, beat_at, status) VALUES ('test', now(), now(), %s)",
                     (Jsonb(status),))
        conn.commit()
    c = ids(make_client().get("/api/v1/health").json())
    assert (c["monitor"]["state"], c["judging"]["state"], c["broker"]["state"]) == ("ok", "ok", "ok")
    assert c["areas"]["summary"] == "No message from the machine yet"
    assert c["evaluation"]["summary"].startswith("At most 12 ms")
    assert c["disk"]["state"] == "warning" and c["disk"]["summary"].startswith("83.0 % used")


def test_only_administrators_see_it(make_client):
    assert make_client(roles=["MANAGER"]).get("/api/v1/health").status_code == 403
