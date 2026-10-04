"""Configuration page API: connections (secrets write-only), tag browsing, versioned register edits."""

from __future__ import annotations

import ast
import json
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest

from .conftest import REPO

NS = "Unilever_Ph_Nutrition.Dressings_Halal.Filling.Volpak.Filler"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_connections_start_from_the_api_config_and_hide_nothing_secret(make_client, mock_timebase):
    body = make_client().get("/api/v1/config/connections").json()
    assert body["historian"]["baseUrl"] == mock_timebase[1] and body["historian"]["source"] == "api config file"
    assert body["mqtt"]["configured"] is False
    assert body["mqtt"]["subscriptions"] == [NS.replace(".", "/") + "/#"]
    assert body["mqtt"]["freshnessS"] == {"SPC": 30, "Dosing_Parameters": 90}


def audit_rows(database) -> list[dict]:
    with database.connect() as conn:
        return conn.execute("SELECT action, summary, reason, details::text AS details FROM audit_log ORDER BY seq").fetchall()


def test_saved_token_stays_on_disk_and_is_never_returned(make_client, mock_timebase, tmp_path, database):
    c = make_client()
    r = c.put("/api/v1/config/connections/historian",
              json={"baseUrl": mock_timebase[1], "dataset": "dressings", "authType": "bearer", "token": "s3cret-token"})
    assert r.status_code == 200, r.text
    assert r.json()["historian"]["tokenSet"] is True and "s3cret-token" not in r.text
    secret = tmp_path / "config" / "secrets" / "timebase-token"
    assert secret.read_text().strip() == "s3cret-token"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    assert "s3cret-token" not in (tmp_path / "config" / "connections.json").read_text()
    assert c.get("/api/v1/analytics/options").status_code == 200  # the api carries on with the new settings
    rows = audit_rows(database)
    assert "connections.historian" in [r["action"] for r in rows] and "s3cret-token" not in json.dumps(rows)


def nothing_saved(tmp_path: Path) -> bool:
    config = tmp_path / "config"
    return not (config / "connections.json").exists() and not (config / "secrets").exists()


def test_historian_test_reports_datasets_and_tags(make_client, mock_timebase, tmp_path):
    c = make_client()
    ok = c.post("/api/v1/config/connections/historian/test", json={"baseUrl": mock_timebase[1], "dataset": "dressings"}).json()
    assert ok["ok"] and ok["datasets"] == ["dressings"] and ok["tagsUnderNamespace"] > 20
    bad = c.post("/api/v1/config/connections/historian/test", json={"baseUrl": mock_timebase[1], "dataset": "nope"}).json()
    assert not bad["ok"] and "nope" in bad["error"]
    typed = c.post("/api/v1/config/connections/historian/test", json={
        "baseUrl": mock_timebase[1], "dataset": "dressings", "authType": "bearer", "token": "typed-token"}).json()
    assert typed["ok"] and nothing_saved(tmp_path)


def test_browse_shows_process_tags_and_who_uses_them(make_client):
    body = make_client().get("/api/v1/config/historian/tags", params={"q": "Vertical1"}).json()
    row = next(t for t in body["tags"] if t["tag"] == "SPC.SetPointTemperatureVertical1")
    assert "Vertical 1 setpoint" in row["usedBy"]
    assert not any(t["tag"].endswith("._timestamp") for t in make_client().get("/api/v1/config/historian/tags").json()["tags"])


def test_latest_values_skip_unknown_tags(make_client):
    body = make_client().post("/api/v1/config/historian/latest",
                              json={"tags": ["SPC.SetPointTemperatureVertical1", "SPC.Nope"]}).json()
    assert isinstance(body["values"]["SPC.SetPointTemperatureVertical1"]["value"], (int, float))
    assert body["missing"] == ["SPC.Nope"] and body["values"]["SPC.Nope"] is None


@pytest.fixture
def extra_tags(mock_timebase):
    mod, _ = mock_timebase
    added = {f"{NS}.SPC.SetPointTemperatureFrontTop2": [(mod.T0, 185)], f"{NS}.SPC.Actual_Temp_Front_Top_2": [(mod.T0, 184.9)]}
    mod.DATA.update(added)
    yield
    for k in added:
        mod.DATA.pop(k, None)


def p04(zones, version, status="active", reason="Top 2 jaws are in use"):
    return {"baseVersion": version, "status": status, "reason": reason, "zones": zones}


BASE_P04 = [{"id": "FRONT", "name": "Front top 1", "setpoint": "SPC.SetPointTemperatureFrontTop1", "actual": "SPC.Actual_Temp_Front_Top_1"},
            {"id": "REAR", "name": "Rear top 1", "setpoint": "SPC.SetPointTemperatureRearTop1", "actual": "SPC.Actual_Temp_Rear_Top_1"}]


def test_adding_a_zone_bumps_the_version_keeps_history_and_reaches_analytics(make_client, extra_tags, tmp_path, database):
    c = make_client()
    me = c.get("/api/v1/auth/session").json()["user"]["username"]
    before = c.get("/api/v1/config/register").json()["version"]
    register = tmp_path / "config" / "parameter-register.json"
    register.chmod(0o644)
    zones = BASE_P04 + [{"id": "front2", "name": "Front top 2", "setpoint": f"{NS}.SPC.SetPointTemperatureFrontTop2",
                         "actual": "SPC.Actual_Temp_Front_Top_2"}]
    r = c.put("/api/v1/config/register/parameters/P04", json=p04(zones, before))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] != before
    p = next(p for p in body["parameters"] if p["id"] == "P04")
    assert p["zones"][2] == {"id": "FRONT2", "name": "Front top 2", "setpoint": "SPC.SetPointTemperatureFrontTop2",
                             "actual": "SPC.Actual_Temp_Front_Top_2"}  # ID upper-cased, namespace stripped
    with database.connect() as conn:
        rows = [(r["number"], r["created_by"]) for r in conn.execute("SELECT number, created_by FROM register_version ORDER BY seq")]
    assert rows == [(before, None), (body["version"], me)]  # the file imported at start, then this save by its author
    exported = json.loads(register.read_text())
    assert exported["version"] == body["version"] and len(exported["parameters"][3]["zones"]) == 3  # for the tools
    assert stat.S_IMODE(register.stat().st_mode) == 0o644  # still readable by them
    assert body["audit"][0]["reason"] == "Top 2 jaws are in use" and body["audit"][0]["to"] == body["version"]
    channels = {v["channel"] for v in c.get("/api/v1/analytics/options").json()["variables"]}
    assert {"P04.FRONT2.actual", "P04.FRONT2.setpoint"} <= channels


def test_stale_version_is_refused(make_client):
    r = make_client().put("/api/v1/config/register/parameters/P04", json=p04(BASE_P04, "2000-01-01.1"))
    assert r.status_code == 409 and r.json()["currentVersion"]


def test_hand_edits_to_the_register_file_are_reported_and_kept(make_client, tmp_path):
    register = tmp_path / "config" / "parameter-register.json"
    c = make_client()
    v1 = c.get("/api/v1/config/register").json()["version"]
    register.write_text(register.read_text().replace('"Rear top 1"', '"Rear top one"'))  # edited by hand

    c = make_client()  # restarted: the database wins and the page says so
    view = c.get("/api/v1/config/register").json()
    assert view["version"] == v1 and "hand edits" in view["fileWarning"]
    assert next(p for p in view["parameters"] if p["id"] == "P04")["zones"][1]["name"] == "Rear top 1"

    r = c.put("/api/v1/config/register/parameters/P04", json=p04(BASE_P04, v1, reason="confirmed on the HMI"))
    assert r.status_code == 200 and r.json()["fileWarning"] is None
    kept = list((tmp_path / "config" / "history").glob("parameter-register.hand-edited.*.json"))
    assert len(kept) == 1 and '"Rear top one"' in kept[0].read_text()  # the hand edit isn't lost
    assert json.loads(register.read_text())["version"] == r.json()["version"]


@pytest.mark.parametrize("zones, status, reason, field", [
    ([*BASE_P04[:1], {"id": "X", "name": "Ghost", "setpoint": None, "actual": "SPC.Nope"}], "analytics_only", "ok reason", "zones[1].actual"),
    ([{"id": "X", "name": "Copy", "setpoint": None, "actual": "SPC.Actual_Temp_Vertical_1"}], "analytics_only", "ok reason", "zones[0].actual"),
    ([{"id": "X", "name": "Half", "setpoint": None, "actual": "SPC.Actual_Temp_Front_Top_1"}], "active", "ok reason", "status"),
    (BASE_P04, "active", "", "reason"),
])
def test_invalid_register_edits_are_refused_with_the_field(make_client, zones, status, reason, field):
    c = make_client()
    version = c.get("/api/v1/config/register").json()["version"]
    r = c.put("/api/v1/config/register/parameters/P04", json=p04(zones, version, status, reason))
    assert r.status_code == 422, r.text
    assert field in [e["field"] for e in r.json()["errors"]]


def test_saved_mqtt_password_is_write_only(make_client, tmp_path):
    r = make_client().put("/api/v1/config/connections/mqtt", json={
        "host": "broker.plant.local", "port": 8883, "username": "centerline", "password": "pw-123",
        "subscriptions": [NS.replace(".", "/") + "/#"], "freshnessS": {"SPC": 30, "Dosing_Parameters": 90}})
    assert r.status_code == 200, r.text
    m = r.json()["mqtt"]
    assert m["configured"] and m["passwordSet"] and m["host"] == "broker.plant.local" and "pw-123" not in r.text
    secret = tmp_path / "config" / "secrets" / "mqtt-password"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600


def test_mqtt_test_reports_an_unreachable_broker(make_client, tmp_path):
    r = make_client().post("/api/v1/config/connections/mqtt/test", json={
        "host": "127.0.0.1", "port": free_port(), "tlsEnabled": False, "username": "centerline", "password": "typed-pw",
        "subscriptions": ["#"], "seconds": 3})
    assert r.status_code == 200 and r.json()["connected"] is False and "Can't reach" in r.json()["error"]
    assert nothing_saved(tmp_path)


SENDS = {"publish", "will_set", "_send_publish"}  # paho's ways to put a message on the broker


def sends(*packages: Path) -> list[str]:
    """Every call in the packages that could publish, and every import of paho's publish helpers."""
    found = []
    for path in sorted(p for package in packages for p in package.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SENDS:
                found.append(f"{path.name}:{node.lineno} .{node.func.attr}()")
            elif isinstance(node, ast.ImportFrom) and (node.module == "paho.mqtt.publish" or (
                    node.module == "paho.mqtt" and any(a.name == "publish" for a in node.names))):
                found.append(f"{path.name}:{node.lineno} imports paho.mqtt.publish")
            elif isinstance(node, ast.Import) and any(a.name == "paho.mqtt.publish" for a in node.names):
                found.append(f"{path.name}:{node.lineno} imports paho.mqtt.publish")
    return found


def test_the_connection_test_can_never_publish_or_leave_a_last_will(make_client, monkeypatch):
    made = []

    class Recording(mqtt.Client):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

    monkeypatch.setattr(mqtt, "Client", Recording)
    r = make_client().post("/api/v1/config/connections/mqtt/test", json={
        "host": "127.0.0.1", "port": free_port(), "tlsEnabled": False, "subscriptions": ["#"], "seconds": 3})
    assert r.json()["connected"] is False and len(made) == 1
    with pytest.raises(RuntimeError, match="read-only"):
        made[0].publish("centerline/acl-test", b"x")  # ADR-0006 M6
    assert made[0]._will is False  # nothing the broker would publish for us when the connection drops


def test_no_code_in_the_api_publishes_or_sets_a_last_will():
    services = REPO / "services"
    assert sends(services / "api" / "centerline_api", services / "common" / "centerline_common") == []


@pytest.mark.skipif(shutil.which("mosquitto") is None, reason="needs the mosquitto broker")
def test_mqtt_test_finds_register_tags_on_a_local_broker(make_client, tmp_path):
    port = free_port()
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n")
    broker = subprocess.Popen(["mosquitto", "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sim = None
    try:
        time.sleep(0.5)
        sim = subprocess.Popen([sys.executable, str(REPO / "tools" / "mqtt-sim" / "mqtt_sim.py"), "--port", str(port),
                                "--rate", "2", "--seconds", "20"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        r = make_client().post("/api/v1/config/connections/mqtt/test", json={
            "host": "127.0.0.1", "port": port, "tlsEnabled": False, "protocol": "5",
            "subscriptions": [NS.replace(".", "/") + "/#"], "seconds": 3})
        body = r.json()
        assert body["connected"], body
        assert body["topicCount"] == 2 and all(t["format"] == "JSON object" for t in body["topics"])
        mapped = {m["tag"]: m for m in body["mapped"]}
        assert mapped["SPC.SetPointTemperatureVertical1"]["field"] == "SetPointTemperatureVertical1"
        assert any("TLS is off" in w for w in body["warnings"])
    finally:
        if sim:
            sim.terminate()
        broker.terminate()
