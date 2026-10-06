"""Mappings tab API (ADR-0013): import, versions, activation only when complete, CSV, discovery on a broker."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time

import psycopg
import pytest

from .conftest import REPO
from .test_config_api import NS, free_port

BASE = NS.replace(".", "/")


def topic_map(c, drop: str | None = None) -> str:
    """A probe topic-map.json for every tag the api says it needs (one topic per area, one field per tag)."""
    need = c.get("/api/v1/config/mappings").json()["required"]
    tags = {f"{NS}.{r['tag']}": {"topic": f"{BASE}/{r['tag'].split('.', 1)[0]}", "field": r["tag"].split(".", 1)[1]}
            for r in need if r["tag"] != drop}
    tags[f"{NS}.SPC.Feed"] = {"topic": f"{BASE}/SPC", "field": "Feed"}  # awaiting, not needed
    return json.dumps({"generated": "2026-09-30T01:51:00Z", "tags": tags, "not_seen": []})


def save(c, rows, expected, activate="no", **extra):
    return c.post("/api/v1/config/mappings/versions", json={"expectedLatest": expected, "rows": rows,
                                                           "source": "probe topic map", "reason": "From the probe run",
                                                           "activate": activate, **extra})


def test_import_save_and_activate_only_a_complete_mapping(make_client, database):
    c = make_client()
    me = c.get("/api/v1/auth/session").json()["user"]["username"]
    empty = c.get("/api/v1/config/mappings").json()
    assert empty["active"] is None and empty["latest"] is None and len(empty["required"]) == 30
    assert empty["subscriptions"] == [BASE + "/#"]

    partial = c.post("/api/v1/config/mappings/import",
                     json={"format": "topic-map", "content": topic_map(c, drop="SPC.Machine_Run")}).json()
    assert len(partial["rows"]) == 29 and partial["ignored"] == ["SPC.Feed"]
    r = save(c, partial["rows"], None)
    assert r.status_code == 201 and r.json()["versions"][0]["status"] == "saved"
    refused = c.post("/api/v1/config/mappings/versions/1/activate", json={"expectedActive": None, "reason": "Probe run done"})
    assert refused.status_code == 422 and any("Machine run" in e["message"] for e in refused.json()["errors"])
    assert save(c, partial["rows"], 1, activate="now").status_code == 422  # can't activate on save either

    full = c.post("/api/v1/config/mappings/import", json={"format": "topic-map", "content": topic_map(c)}).json()["rows"]
    r = save(c, full, 1, activate="now", basedOn=1)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["active"]["number"] == 2 and body["coverage"] == {"required": 30, "mapped": 30, "missing": []}
    assert body["active"]["by"] == me
    with database.connect() as conn:
        assert [r["created_by"] for r in conn.execute("SELECT created_by FROM mapping_version ORDER BY number")] == [me, me]
    v2 = c.get("/api/v1/config/mappings/versions/2").json()
    assert v2["intact"] and v2["basedOn"] == 1 and v2["warnings"] == [] and "sku" not in v2
    assert c.get("/api/v1/health").json()["database"]["activeMapping"] == 2

    csv_text = c.get("/api/v1/config/mappings/versions/2/export.csv").text
    assert csv_text.startswith("tag,topic,field\n") and "SPC.Machine_Run" in csv_text
    back = c.post("/api/v1/config/mappings/import", json={"format": "csv", "content": csv_text}).json()
    assert sorted(r["tag"] for r in back["rows"]) == sorted(r["tag"] for r in full) and back["problems"] == []

    stale = save(c, full, 1)
    assert stale.status_code == 409 and stale.json()["currentVersion"] == 2


def test_a_mapping_names_only_tags_and_the_database_refuses_a_sku(make_client, owner):
    c = make_client()
    full = c.post("/api/v1/config/mappings/import", json={"format": "topic-map", "content": topic_map(c)}).json()["rows"]
    assert save(c, full, None, skuPlaceholder="PLACEHOLDER").status_code == 422  # no such field any more (ADR-0027)
    assert save(c, full, None, sku={"topic": f"{BASE}/SPC", "field": "SKU_Code"}).status_code == 422
    with owner.connect() as conn, pytest.raises(psycopg.errors.CheckViolation):  # not even the owner records one now
        reg = conn.execute("SELECT id FROM register_version LIMIT 1").fetchone()["id"]
        conn.execute("""INSERT INTO mapping_version (id, number, register_version_id, legacy_sku_placeholder, source, sha256, reason)
                        VALUES (gen_random_uuid(), 99, %s, 'PLACEHOLDER', 'test', 'x', 'test')""", (reg,))


def test_check_reports_problems_and_coverage_without_saving(make_client):
    c = make_client()
    rows = c.post("/api/v1/config/mappings/import", json={"format": "topic-map", "content": topic_map(c)}).json()["rows"]
    rows[0] = {**rows[0], "topic": BASE + "/#"}
    r = c.post("/api/v1/config/mappings/versions/check", json={"expectedLatest": None, "rows": rows})
    body = r.json()
    assert [e["field"] for e in body["errors"]] == ["rows[0].topic"] and body["coverage"]["mapped"] == 30
    assert body["warnings"] == []
    assert c.get("/api/v1/config/mappings").json()["latest"] is None
    bad = c.post("/api/v1/config/mappings/import", json={"format": "topic-map", "content": "[]"})
    assert bad.status_code == 422


def test_discover_needs_a_saved_broker(make_client):
    body = make_client().post("/api/v1/config/mappings/discover", json={"seconds": 3}).json()
    assert body["connected"] is False and "Connections tab" in body["error"]


@pytest.mark.skipif(shutil.which("mosquitto") is None, reason="needs the mosquitto broker")
def test_discover_finds_every_tag_on_a_broker(make_client, tmp_path):
    port = free_port()
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n")
    broker = subprocess.Popen(["mosquitto", "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sim = None
    try:
        time.sleep(0.5)
        sim = subprocess.Popen([sys.executable, str(REPO / "tools" / "mqtt-sim" / "mqtt_sim.py"), "--port", str(port),
                                "--rate", "2", "--seconds", "20"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        c = make_client()
        saved = c.put("/api/v1/config/connections/mqtt", json={"host": "127.0.0.1", "port": port, "tlsEnabled": False,
                                                               "subscriptions": [BASE + "/#"]})
        assert saved.status_code == 200, saved.text
        time.sleep(1)
        body = c.post("/api/v1/config/mappings/discover", json={"seconds": 3}).json()
        assert body["connected"], body
        assert len(body["rows"]) == 30 and body["notSeen"] == [], body
        assert "SetPointTemperatureVertical1" in body["fields"][f"{BASE}/SPC"]  # for the editor's field suggestions
    finally:
        if sim:
            sim.terminate()
        broker.terminate()
