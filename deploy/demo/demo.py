#!/usr/bin/env python3
"""Centerline working end to end on the simulator, apart from the real data.

    services/.venv/bin/python deploy/demo/demo.py start    # then open http://localhost:5174
    services/.venv/bin/python deploy/demo/demo.py status
    services/.venv/bin/python deploy/demo/demo.py stop
    services/.venv/bin/python deploy/demo/demo.py reset    # stop, and delete the demo's database and files

Everything runs on this PC: a Mosquitto broker on 127.0.0.1:18833 fed by tools/mqtt-sim, monitor-core,
the notifier with tools/notify-sink in place of Teams and email, an api on 127.0.0.1:8010 over its own
database `centerline_demo`, and the web app on :5174. Nothing reaches the plant broker, Timebase,
Teams or email, and nothing is written to the `centerline` database.

The first start sets the demo up the way an Administrator would on the Configuration page: the broker,
a tag mapping found on it, a SKU with targets, the Phase 0 rules proposal, and a routing. It creates the
account `demo` (Manager and Administrator) and keeps its password in deploy/demo/state/demo-password
(0600); it's never printed.

With --plant (ADR-0024) it shows the real machine instead, read-only: monitor-core subscribes to the
plant broker saved on the real Configuration page, with the real mapping and the placeholder SKU, so the
actual values are judged and HMI mismatch isn't. It has its own database `centerline_plant_trial`, an api
on 127.0.0.1:8011 and the web app on :5175, and no notifier. Nothing is published to the broker, and
nothing is written to the `centerline` database. It needs the laptop on the plant network.

    services/.venv/bin/python deploy/demo/demo.py start --plant    # then open http://localhost:5175
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SERVICES = REPO / "services"
PYTHON = SERVICES / ".venv" / "bin" / "python"
PLANT = "--plant" in sys.argv[2:]  # the real machine, read-only (ADR-0024), instead of the simulator
STATE = HERE / ("plant-state" if PLANT else "state")
CONFIG = STATE / "config"
LOGS = STATE / "logs"
PIDS = STATE / "pids.json"
PASSWORD = STATE / "demo-password"
OPERATOR_PASSWORD = STATE / "operator-password"
DB = "centerline_plant_trial" if PLANT else "centerline_demo"
BROKER, TEAMS, SMTP = 18833, 8025, 2525
API, WEB = (8011, 5175) if PLANT else (8010, 5174)
WHAT = "the plant trial" if PLANT else "the demo"
PLACEHOLDER = "PLACEHOLDER"  # the trial's SKU while the machine publishes none (ADR-0022)
SKU = "SIM-SKU-1"
SIM = ["--brief-every", "45", "--mismatch-every", "300", "--mismatch-for", "600", "--drift-every", "150",
       "--machine-stop-every", "900", "--machine-stop-for", "120",
       "--sku-field", "SPC.SKU_Code", "--sku", SKU]

sys.path.insert(0, str(SERVICES / "common"))
from centerline_common import roles  # noqa: E402
from centerline_common.db import DatabaseConfig  # noqa: E402


def busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def pids() -> dict[str, int]:
    return json.loads(PIDS.read_text()) if PIDS.exists() else {}


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def spawn(name: str, cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    """A detached process with its own log, so it keeps running after this script ends."""
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"{name}.log", "ab")
    p = subprocess.Popen(cmd, cwd=cwd, env={**os.environ, **(env or {})}, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    PIDS.write_text(json.dumps({**pids(), name: p.pid}))
    print(f"  {name:<12} started (log: {(LOGS / f'{name}.log').relative_to(REPO)})")


def wait_for(port: int, what: str, seconds: float = 40) -> None:
    deadline = time.time() + seconds
    while not busy(port):
        if time.time() > deadline:
            sys.exit(f"{what} didn't start on port {port}: see {LOGS.relative_to(REPO)}")
        time.sleep(0.3)


class Api:
    """The demo api as the demo account: the session cookie by hand, the CSRF header on every change."""

    def __init__(self):
        self.cookie = None

    def call(self, method: str, path: str, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{API}/api/v1{path}", method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Centerline-CSRF": "1",
                                              **({"Cookie": self.cookie} if self.cookie else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                for header in r.headers.get_all("Set-Cookie") or []:
                    if header.startswith("centerline_session="):
                        self.cookie = header.split(";", 1)[0]
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            problem = json.loads(e.read() or b"{}")
            sys.exit(f"{method} {path}: {e.code} {problem.get('title')}: {problem.get('detail')} {problem.get('errors') or ''}")


def configs() -> None:
    owner = DatabaseConfig(dbname=DB)
    app = roles.app_database(owner)
    database = {"dbname": DB, "user": app.user, "password_file": str(app.password_file)}
    CONFIG.mkdir(parents=True, exist_ok=True)
    register = CONFIG / "parameter-register.json"
    if not register.exists():
        shutil.copy(REPO / "config" / "parameter-register.json", register)
    timebase = {"base_url": "http://127.0.0.1:9", "dataset": "demo", "auth": {"type": "none"}, "timeout_s": 2}
    if PLANT:
        timebase = json.loads((SERVICES / "api" / "config.json").read_text())["timebase"]  # the real one, read-only
        plant_broker(write=True)
    (STATE / "api.json").write_text(json.dumps({
        "timebase": timebase,
        "register": str(register), "config_dir": str(CONFIG), "audit_log": str(STATE / "audit.jsonl"),
        "database": database, "migrate_database": {"dbname": DB},
        # a plain-http demo on this PC, which is also its operator workstation (Vite's proxy connects from 127.0.0.1)
        "auth": {"secure_cookie": False, "operator_workstations": [{"name": "This PC", "ip": "127.0.0.1"}]}}, indent=2))
    (STATE / "monitor.json").write_text(json.dumps({"database": database, "config_dir": str(CONFIG), "instance": "demo",
                                                    "journal_dir": str(STATE / "journal")}, indent=2))
    (STATE / "notifier.json").write_text(json.dumps({"database": database, "config_dir": str(CONFIG), "instance": "demo"},
                                                    indent=2))
    (STATE / "mosquitto.conf").write_text(f"listener {BROKER} 127.0.0.1\nallow_anonymous true\n")


def plant_broker(write: bool = False) -> dict:
    """The plant broker as the real Configuration page saved it, for monitor-core to subscribe to, read-only.

    The shared account's password stays in config/secrets: the trial points at that file, never a copy. A
    client ID of its own keeps the trial from taking over anyone else's connection."""
    real = REPO / "config"
    stored = json.loads((real / "connections.json").read_text())["mqtt"]
    if stored.get("password_file", "").startswith("secrets/"):
        stored["password_file"] = str(real / stored["password_file"])
    stored["client_id"] = f"centerline-trial-{socket.gethostname()}"[:64]
    if write:
        CONFIG.mkdir(parents=True, exist_ok=True)
        (CONFIG / "connections.json").write_text(json.dumps({"mqtt": stored}, indent=2))
    return stored


def reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=4):
            return True
    except OSError:
        return False


def ensure_database() -> None:
    with DatabaseConfig().connect(autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,)).fetchone():
            c.execute(f'CREATE DATABASE "{DB}"')
            print(f"  database {DB} created")


def account(api: Api) -> None:
    """The demo account, made once with the server's command line; its password stays in a 0600 file."""
    env = {**os.environ, "CENTERLINE_API_CONFIG": str(STATE / "api.json"), "PYTHONPATH": "common:api"}
    if not PASSWORD.exists():
        temp = STATE / "demo-temporary"
        subprocess.run([str(PYTHON), "-m", "centerline_api.auth", "create-admin", "--username", "demo", "--name", "Demo",
                        "--reason", f"Signing in to {WHAT}", "--out", str(temp)], cwd=SERVICES, env=env, check=True,
                       stdout=subprocess.DEVNULL)
        temporary = temp.read_text().strip()
        api.call("POST", "/auth/login", {"name": "demo", "password": temporary})
        password = "Demo-" + secrets.token_urlsafe(12)
        api.call("POST", "/auth/password", {"current": temporary, "new": password})
        fd = os.open(PASSWORD, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(password + "\n")
        temp.unlink()
        print("  account demo created")
    api.call("POST", "/auth/login", {"name": "demo", "password": PASSWORD.read_text().strip()})
    if not OPERATOR_PASSWORD.exists():  # an operator, to give the reasons (ADR-0025)
        made = api.call("POST", "/users", {"username": "operator", "displayName": "Line operator", "roles": ["OPERATOR"],
                                           "reason": f"Giving the reasons in {WHAT}"})
        op = Api()
        op.call("POST", "/auth/login", {"name": "operator", "password": made["temporaryPassword"]})
        password = "Operator-" + secrets.token_urlsafe(12)
        op.call("POST", "/auth/password", {"current": made["temporaryPassword"], "new": password})
        op.call("POST", "/auth/logout", {})
        fd = os.open(OPERATOR_PASSWORD, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(password + "\n")
        print("  account operator created")


def targets() -> dict[str, float]:
    """The simulator's setpoints, which the demo SKU takes as its targets."""
    sys.path.insert(0, str(REPO / "tools" / "mqtt-sim"))
    import mqtt_sim  # noqa: E402
    reg = json.loads((CONFIG / "parameter-register.json").read_text())
    out = {}
    for p in (p for p in reg["parameters"] if p.get("status") == "active"):  # the monitored ones
        values = mqtt_sim.TARGETS.get(p["id"], [100])
        for i, z in enumerate(p.get("zones") or []):
            out[f"{p['id']}.{z['id']}"] = values[i % len(values)]
    return out


def set_up(api: Api) -> None:
    """What an Administrator and a Manager would do on the Configuration page, done once."""
    rules = api.call("GET", "/config/rules")
    if rules["active"] is not None:
        return
    namespace = api.call("GET", "/config/connections")["mqtt"]["subscriptions"][0]
    api.call("PUT", "/config/connections/mqtt", {
        "host": "127.0.0.1", "port": BROKER, "protocol": "5", "tlsEnabled": False, "verifyHostname": True, "username": "",
        "clientId": "centerline-demo", "keepaliveS": 5, "subscriptions": [namespace],
        "freshnessS": {"SPC": 30, "Dosing_Parameters": 90}, "reason": "The demo's local broker, fed by the simulator"})
    api.call("PUT", "/config/connections/notifications", {
        "appUrl": f"http://localhost:{WEB}", "teamsUrl": f"http://127.0.0.1:{TEAMS}/flow?sig=demo", "smtpHost": "127.0.0.1",
        "smtpPort": SMTP, "smtpSecurity": "none", "emailSender": "centerline-demo@plant.test", "reason": "tools/notify-sink"})
    found = api.call("POST", "/config/mappings/discover", {"seconds": 8})
    if not found.get("connected"):
        sys.exit(f"the demo broker didn't answer: {found.get('error')}")
    sku = next((c for c in found["skuCandidates"] if c["field"] == "SKU_Code"), None)
    api.call("POST", "/config/mappings/versions", {
        "expectedLatest": None, "rows": found["rows"], "sku": {"topic": sku["topic"], "field": sku["field"]} if sku else None,
        "source": "the demo broker", "reason": "Found on the demo broker", "activate": "now"})
    api.call("POST", "/config/skus", {"code": SKU, "name": "Simulator SKU"})
    proposal = api.call("GET", "/config/rules/proposal")
    rows = proposal["rules"] + [{"sku": SKU, "parameterId": ch.split(".")[0], "zoneId": ch.split(".")[1], "target": t}
                                for ch, t in targets().items()]
    api.call("POST", "/config/versions", {"expectedLatest": None, "basedOn": None, "settings": proposal["settings"],
                                          "rules": rows, "reason": "The Phase 0 proposal, with the simulator's SKU", "activate": "now"})
    print("  configured: broker, mapping v1, SKU and rules v1, channels")


def routing(api: Api) -> None:
    """The proposal's routing to the sink's recipients; when the proposal has a kind of message the routing in
    effect doesn't send (a newer Centerline), a new version adds it, as an Administrator would."""
    rules = api.call("GET", "/config/routing/proposal")["rules"]
    for r in rules:
        r["targets"] = ["Centerline alerts"] if r["channel"] == "teams" else ["shift.lead@plant.test"]
    now = api.call("GET", "/config/routing")
    sent = {t for r in now["rules"] or [] for t in r["types"]}
    if now["active"] is not None and sent >= {t for r in rules for t in r["types"]}:
        return
    made = api.call("POST", "/config/routing/versions", {
        "expectedLatest": now["latest"], "basedOn": now["active"] and now["active"]["number"], "rules": rules,
        "reason": "The demo's recipients" if now["latest"] is None else "The demo's recipients, with every kind of message",
        "activate": "now"})
    print(f"  routing v{made['created']} in effect")


def set_up_plant(api: Api) -> None:
    """The real mapping with the placeholder SKU (ADR-0022), and the Phase 0 rules proposal: done once."""
    if api.call("GET", "/config/rules")["active"] is not None:
        return
    with roles.app_database(DatabaseConfig()).connect() as c:  # the real database, read only
        rows = [dict(r) for r in c.execute("""SELECT tag, topic, field FROM tag_mapping
                                              WHERE mapping_version_id = active_mapping_version() ORDER BY tag""")]
    if not rows:
        sys.exit("No tag mapping is in effect on the real Configuration page, so the trial can't read the machine")
    api.call("POST", "/config/mappings/versions", {
        "expectedLatest": None, "rows": rows, "sku": None, "skuPlaceholder": PLACEHOLDER,
        "source": "the real mapping in effect", "reason": "The real mapping, with the placeholder SKU (ADR-0022)", "activate": "now"})
    proposal = api.call("GET", "/config/rules/proposal")
    api.call("POST", "/config/versions", {"expectedLatest": None, "basedOn": None, "settings": proposal["settings"],
                                          "rules": proposal["rules"], "reason": "The Phase 0 proposal: accepted delays, proposed limits",
                                          "activate": "now"})
    print(f"  configured: the real mapping ({len(rows)} tags) with the placeholder SKU, and the rules proposal")


def plant_targets(api: Api) -> None:
    """The placeholder's targets, given once: each zone's HMI setpoint as monitor-core first sees it, as a new rules
    version (the owner, 2026-10-02: show and judge them, ADR-0022). Change them on Configuration → Rules."""
    rules = api.call("GET", "/config/rules")
    if rules["active"] is None:
        return
    version = api.call("GET", f"/config/versions/{rules['active']['number']}")
    if any(r["sku"] == PLACEHOLDER and r["target"] is not None for r in version["rules"]):
        return  # given already; a Manager may have changed them since
    print("  waiting for the machine's HMI setpoints, to give the placeholder its targets…")
    zones: dict = {}
    for _ in range(45):
        live = api.call("GET", "/monitoring/live")
        zones = {z["channel"]: z for p in live["parameters"] for z in p["zones"]}
        if zones and all(z["known"] and z.get("setpoint") is not None for z in zones.values()):
            break
        time.sleep(2)
    else:
        print("  not every setpoint arrived within 90 s, so no targets yet: start the trial again, or give them on "
              "Configuration → Rules (Fill empty targets from current HMI setpoints)")
        return
    if PLACEHOLDER not in {s["code"] for s in rules["skus"]}:
        api.call("POST", "/config/skus", {"code": PLACEHOLDER, "name": "Placeholder: the machine doesn't publish its SKU yet"})
    at = time.strftime("%d %b %H:%M", time.gmtime(time.time() + 8 * 3600))  # Manila
    rows = version["rules"] + [{"sku": PLACEHOLDER, "parameterId": z["channel"].split(".")[0], "zoneId": z["channel"].split(".")[1],
                                "target": z["setpoint"]} for z in sorted(zones.values(), key=lambda z: z["channel"])]
    made = api.call("POST", "/config/versions", {
        "expectedLatest": rules["latest"], "basedOn": rules["active"]["number"], "settings": version["settings"], "rules": rows,
        "reason": f"The placeholder's targets: the machine's HMI setpoints at {at} Manila (owner, 2026-10-02)", "activate": "now"})
    print(f"  rules v{made['created']} in effect: the placeholder's {len(zones)} targets are the HMI setpoints at {at} Manila")


def start_plant() -> None:
    broker = plant_broker()
    if not reachable(broker["host"], int(broker.get("port") or 1883)):
        sys.exit("The plant broker doesn't answer from this laptop. Connect it to the plant network (the one the probe "
                 "used on 30 Sep), then run this again.")
    for port, what in ((API, "the trial api"), (WEB, "the trial web app")):
        if busy(port):
            sys.exit(f"port {port} ({what}) is taken by something else")
    print("Starting the plant trial: the real machine, read-only")
    PIDS.unlink(missing_ok=True)
    configs()
    ensure_database()
    spawn("api", [str(PYTHON), "-m", "uvicorn", "centerline_api.main:create_app", "--factory", "--host", "127.0.0.1",
                  "--port", str(API), "--log-level", "warning"], SERVICES,
          {"CENTERLINE_API_CONFIG": str(STATE / "api.json"), "PYTHONPATH": "common:api"})
    wait_for(API, "the trial api")
    api = Api()
    account(api)
    set_up_plant(api)
    spawn("monitor-core", [str(PYTHON), "-m", "centerline_monitor"], SERVICES,
          {"CENTERLINE_MONITOR_CONFIG": str(STATE / "monitor.json"), "PYTHONPATH": "common:monitor_core"})
    plant_targets(api)
    spawn("web", ["npx", "vite", "--port", str(WEB), "--strictPort"], REPO / "client", {"CENTERLINE_API": f"http://127.0.0.1:{API}"})
    wait_for(WEB, "the trial web app", 60)
    print(f"\nOpen http://localhost:{WEB} and sign in as demo; the password is in {PASSWORD.relative_to(REPO)}.\n"
          "It only subscribes to the plant broker. Stop it with: demo.py stop --plant")


def start() -> None:
    running = {n: p for n, p in pids().items() if alive(p)}
    if running:
        sys.exit(f"{WHAT} is already running ({', '.join(running)}): open http://localhost:{WEB}")
    if PLANT:
        return start_plant()
    for port, what in ((BROKER, "the demo broker"), (API, "the demo api"), (WEB, "the demo web app"), (TEAMS, "notify-sink"),
                       (SMTP, "notify-sink")):
        if busy(port):
            sys.exit(f"port {port} ({what}) is taken by something else")
    if not shutil.which("mosquitto"):
        sys.exit("needs the mosquitto broker: sudo apt install mosquitto")
    print("Starting the Centerline demo:")
    PIDS.unlink(missing_ok=True)
    configs()
    ensure_database()
    spawn("broker", ["mosquitto", "-c", str(STATE / "mosquitto.conf")], STATE)
    spawn("notify-sink", [str(PYTHON), str(REPO / "tools" / "notify-sink" / "notify_sink.py"), "--out", str(STATE / "sink"),
                          "--http-port", str(TEAMS), "--smtp-port", str(SMTP)], REPO)
    wait_for(BROKER, "the demo broker")
    spawn("simulator", [str(PYTHON), str(REPO / "tools" / "mqtt-sim" / "mqtt_sim.py"), "--port", str(BROKER), *SIM], REPO)
    spawn("api", [str(PYTHON), "-m", "uvicorn", "centerline_api.main:create_app", "--factory", "--host", "127.0.0.1",
                  "--port", str(API), "--log-level", "warning"], SERVICES,
          {"CENTERLINE_API_CONFIG": str(STATE / "api.json"), "PYTHONPATH": "common:api"})
    wait_for(API, "the demo api")
    api = Api()
    account(api)
    set_up(api)
    routing(api)
    spawn("monitor-core", [str(PYTHON), "-m", "centerline_monitor"], SERVICES,
          {"CENTERLINE_MONITOR_CONFIG": str(STATE / "monitor.json"), "PYTHONPATH": "common:monitor_core"})
    spawn("notifier", [str(PYTHON), "-m", "centerline_notifier"], SERVICES,
          {"CENTERLINE_NOTIFIER_CONFIG": str(STATE / "notifier.json"), "PYTHONPATH": "common:notifier"})
    spawn("web", ["npx", "vite", "--port", str(WEB), "--strictPort"], REPO / "client", {"CENTERLINE_API": f"http://127.0.0.1:{API}"})
    wait_for(WEB, "the demo web app", 60)
    print(f"\nOpen http://localhost:{WEB} and sign in as demo (Manager and Administrator), password in "
          f"{PASSWORD.relative_to(REPO)},\nor as operator, password in {OPERATOR_PASSWORD.relative_to(REPO)}.\n"
          f"Messages to Teams and email land in {(STATE / 'sink').relative_to(REPO)}. Stop it with: demo.py stop")


def stop() -> None:
    known = pids()
    for name, pid in reversed(list(known.items())):
        if alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
    deadline = time.time() + 15
    while any(alive(p) for p in known.values()) and time.time() < deadline:
        time.sleep(0.3)
    for pid in known.values():
        if alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    PIDS.unlink(missing_ok=True)
    print(f"{WHAT.capitalize()} is stopped." if known else f"{WHAT.capitalize()} wasn't running.")


def status() -> None:
    known = pids()
    if not known:
        print(f"{WHAT.capitalize()} isn't running.")
    for name, pid in known.items():
        print(f"  {name:<12} {'running' if alive(pid) else 'stopped'}")


def reset() -> None:
    stop()
    with DatabaseConfig().connect(autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
    shutil.rmtree(STATE, ignore_errors=True)
    print(f"The database {DB} and the files of {WHAT} are gone; the next start sets it up again.")


if __name__ == "__main__":
    commands = {"start": start, "stop": stop, "status": status, "reset": reset}
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in commands or sys.argv[2:] not in ([], ["--plant"]):
        sys.exit(__doc__)
    commands[sys.argv[1]]()
