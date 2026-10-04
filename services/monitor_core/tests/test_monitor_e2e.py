"""monitor-core end to end (G1 on the simulator): a local Mosquitto, tools/mqtt-sim, the service loop, PostgreSQL."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import pytest

from centerline_monitor.service import MonitorSettings, Service
from conftest import SKU, seed, use_placeholder
from monitor_helpers import BASE, REPO


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def running(database, tmp_path, *sim_args: str):
    """A local Mosquitto, tools/mqtt-sim with these arguments, and the service loop, while the block runs."""
    port = free_port()
    (tmp_path / "mosquitto.conf").write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "connections.json").write_text(json.dumps({"mqtt": {
        "host": "127.0.0.1", "port": port, "protocol": "5", "tls": {"enabled": False}, "username": "", "keepalive_s": 5,
        "subscriptions": [BASE + "/#"], "freshness_s": {"SPC": 30, "Dosing_Parameters": 90}}}))
    broker = subprocess.Popen(["mosquitto", "-c", str(tmp_path / "mosquitto.conf")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sim = service = thread = None
    try:
        time.sleep(0.5)
        sim = subprocess.Popen([sys.executable, str(REPO / "tools" / "mqtt-sim" / "mqtt_sim.py"), "--port", str(port), "--rate", "2",
                                "--seconds", "60", *sim_args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        service = Service(MonitorSettings(database=database, config_dir=config_dir, instance="e2e", heartbeat_s=1, reload_s=1,
                                          journal_dir=config_dir / "journal"))
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        yield
    finally:
        if service:
            service.stop()
        if thread:
            thread.join(10)
        if sim:
            sim.terminate()
        broker.terminate()


def heartbeat(conn) -> dict | None:
    beat = conn.execute("SELECT status FROM monitor_heartbeat WHERE instance = 'e2e'").fetchone()
    conn.commit()
    return beat["status"] if beat else None


@pytest.mark.skipif(shutil.which("mosquitto") is None, reason="needs the mosquitto broker")
def test_monitor_core_judges_the_simulator(database, tmp_path):
    with database.connect() as conn:
        seed(conn, delays={"mismatch_delay_s": 3})  # the simulator's brief changes last 5–40 s: long enough
    with running(database, tmp_path, "--brief-every", "3", "--sku-field", "SPC.SKU_Code", "--sku", SKU), database.connect() as conn:
        deadline = time.time() + 45
        while time.time() < deadline:
            events = conn.execute("SELECT count(*) AS n FROM event WHERE kind = 'HMI_MISMATCH'").fetchone()["n"]
            conn.commit()
            if events >= 2:
                break
            time.sleep(1)
        beat = heartbeat(conn)
        first_pause = conn.execute("SELECT ended_at, reasons FROM pause_period ORDER BY started_at LIMIT 1").fetchone()
        notes = conn.execute("SELECT count(*) AS n FROM notification WHERE kind = 'initial'").fetchone()["n"]
    assert events >= 2, "no HMI events from the simulator's setpoint changes"
    assert beat and beat["judging"] is True and beat["sku"] == SKU
    assert first_pause["ended_at"] is not None and "Starting" in first_pause["reasons"][0]  # judged only once complete
    assert notes >= 2


@pytest.mark.skipif(shutil.which("mosquitto") is None, reason="needs the mosquitto broker")
def test_without_a_sku_field_the_simulator_is_judged_under_the_placeholder(database, tmp_path):
    with database.connect() as conn:
        seed(conn, delays={"mismatch_delay_s": 3})
        use_placeholder(conn)  # ADR-0022
    with running(database, tmp_path, "--brief-every", "3"), database.connect() as conn:  # no SKU field, like the machine today
        deadline = time.time() + 30
        while time.time() < deadline and not (heartbeat(conn) or {}).get("judging"):
            time.sleep(1)
        time.sleep(10)  # brief setpoint changes would have opened mismatches by now, were HMI judged
        beat = heartbeat(conn)
        mismatches = conn.execute("SELECT count(*) AS n FROM event WHERE kind = 'HMI_MISMATCH'").fetchone()["n"]
    assert beat and beat["judging"] is True and (beat["sku"], beat["skuPlaceholder"]) == ("PLACEHOLDER", "PLACEHOLDER")
    assert {z["hmi"] for z in beat["zones"].values()} == {"NO_TARGET"} and mismatches == 0
    assert all(z["bands"] for z in beat["zones"].values() if z["setpoint"] is not None)  # actual values are judged


@pytest.mark.skipif(shutil.which("mosquitto") is None, reason="needs the mosquitto broker")
def test_the_simulators_drift_raises_an_actual_warning_and_its_stops_pause_the_actual_rules(database, tmp_path):
    with database.connect() as conn:
        seed(conn, delays={"warning_delay_s": 2, "critical_delay_s": 1})
    with running(database, tmp_path, "--drift-every", "1", "--machine-stop-every", "8", "--machine-stop-for", "3",
                 "--sku-field", "SPC.SKU_Code", "--sku", SKU), database.connect() as conn:
        deadline = time.time() + 30
        while time.time() < deadline:
            warnings = conn.execute("SELECT count(*) AS n FROM event WHERE kind = 'ACTUAL' AND severity = 'WARNING'").fetchone()["n"]
            stops = conn.execute("SELECT count(*) AS n FROM pause_period WHERE scope = 'actual'").fetchone()["n"]
            conn.commit()
            if warnings and stops:
                break
            time.sleep(1)
    assert warnings >= 1, "no Actual Warning from the simulator's drift"
    assert stops >= 1, "no Actual pause from the simulator's machine stop"
