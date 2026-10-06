"""The acceptance suites the phase gates run (URS v1.1 §13): AT-04…06 for G2, AT-08's deterministic part for G3,
AT-ANA-01…10 for G4.

They run with the services' tests (`cd services && .venv/bin/python -m pytest`; pyproject.toml lists this folder),
or alone (`… -m pytest ../tests/acceptance`), and need the development database as those do.

As black-box as the system allows:
- the api in-process, called as the web app calls it: the CSRF header, an Idempotency-Key on every POST;
- monitor-core's engine and its database writer, on a simulated line. Its clock starts at the real time, so it
  agrees with the api's shifts, and moves only when a test says so;
- the notifier, against stand-ins for the Teams flow and the SMTP relay;
- Analytics, against a stand-in Timebase serving tests/fixtures/analytics (timebase_stub.py).

Each test names the URS requirements it shows with `@pytest.mark.urs(...)`. The run ends with which passed.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from centerline_common import shifts
from centerline_monitor.engine import Engine
from centerline_monitor.store import Store
from centerline_notifier.service import NotifierSettings, Service

SERVICES = Path(__file__).resolve().parents[2] / "services"


def _load(name: str, path: Path):
    """A test module of a service by its file, under its own name, so the suites' fixtures don't collide."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


api = _load("acceptance_api", SERVICES / "api" / "tests" / "conftest.py")
notifier = _load("acceptance_notifier", SERVICES / "notifier" / "tests" / "conftest.py")
machine = _load("acceptance_machine", SERVICES / "monitor_core" / "tests" / "monitor_helpers.py")

# The api suite's fixtures: a migrated database per test, as the services' role, and signed-in clients
mock_timebase, db_server, database, owner, make_client = api.mock_timebase, api.db_server, api.database, api.owner, api.make_client
# The notifier suite's stand-ins for the Teams flow and the SMTP relay
teams, smtp = notifier.teams, notifier.smtp

PASSWORD, add_account, new_client, sign_in = api.PASSWORD, api.add_account, api.new_client, api.sign_in
DESKS = (("Line desk", "10.0.0.5"), ("Backup desk", "10.0.0.6"))
AT_THE_LINE = replace(api.FAST_AUTH, operator_workstations=DESKS)
REG, BASE = machine.REG, machine.BASE


# -- URS coverage -------------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _urs(request):
    marker = request.node.get_closest_marker("urs")
    request.node.user_properties.append(("urs", marker.args if marker else ()))


def pytest_terminal_summary(terminalreporter):
    shown: dict[str, set[str]] = {}
    for outcome in ("passed", "failed", "error", "skipped"):
        for report in terminalreporter.stats.get(outcome, []):  # only this folder's tests carry "urs"
            for name, ids in getattr(report, "user_properties", []):
                for urs_id in ids if name == "urs" else ():
                    shown.setdefault(urs_id, set()).add(outcome)
    if not shown:
        return
    verdicts = {i: "failed" if o & {"failed", "error"} else "passed" if "passed" in o else "skipped" for i, o in shown.items()}
    terminalreporter.section("URS requirements shown by the acceptance suites")
    for verdict in ("failed", "skipped", "passed"):
        ids = sorted(i for i, v in verdicts.items() if v == verdict)
        if ids:
            terminalreporter.write_line(f"{verdict:8} {' '.join(ids)}")


# -- the line, configured through the api, and monitor-core on it -------------------------------------------------

def configure(client, pause_when_stopped: bool = True) -> None:
    """What the owner does on the Configuration page: mapping v1, every tag where the line publishes it, and rules v1,
    the Phase 0 proposal with each zone's target. Both activated now."""
    mapping = client.get("/api/v1/config/mappings").json()
    rows = [{"tag": r["tag"], "topic": f"{BASE}/{r['tag'].split('.', 1)[0]}", "field": r["tag"].split(".", 1)[1]}
            for r in mapping["required"]]
    r = client.post("/api/v1/config/mappings/versions", json={"expectedLatest": None, "rows": rows, "source": "acceptance",
                                                              "reason": "The line as it publishes", "activate": "now"})
    assert r.status_code == 201, r.text
    proposal = client.get("/api/v1/config/rules/proposal").json()
    settings = proposal["settings"]
    settings["pauseWhenStopped"]["enabled"] = pause_when_stopped
    targets = [{"parameterId": z.parameter_id, "zoneId": z.zone_id, "target": machine.targets()[z.channel]} for z in REG.zones]
    r = client.post("/api/v1/config/versions", json={"expectedLatest": None, "settings": settings,
                                                     "rules": proposal["rules"] + targets,
                                                     "reason": "The Phase 0 proposal, with the centerline sheet's targets",
                                                     "activate": "now"})
    assert r.status_code == 201, r.text


def clock_start(room: timedelta = timedelta(minutes=17), now: datetime | None = None) -> datetime:
    """Where the simulated clock starts: just before now, and with `room` left in this shift, since the api's shifts
    are the real ones."""
    now = now or datetime.now(timezone.utc)
    shift = shifts.shift_at(now)
    return max(min(now - timedelta(seconds=35), shift.ends_at - room), shift.starts_at + timedelta(seconds=1))


@dataclass
class Plant:
    """The Volpak and monitor-core: the engine and its database writer, judging a simulated line."""

    engine: Engine
    store: Store
    line: machine.Line
    start: datetime
    t: float = 0.0
    names: dict = field(default_factory=dict)

    def at(self, seconds: float) -> datetime:
        return self.start + timedelta(seconds=seconds)

    def run(self, until: float, every: float = 1.0) -> None:
        """The line publishes every `every` s and timers fire, up to `until` s after the start. Shift ends and overdue
        reasons are checked each step, as monitor-core's loop does (WF-03)."""
        while self.t < until:
            self.t = min(self.t + every, until)
            now = self.at(self.t)
            self.line.publish(self.engine, now)
            self.engine.tick(now)
            self.store.workflow_tick(now, self.names)


@pytest.fixture
def plant(database, tmp_path):
    """monitor-core started on the database: call it once the line is configured, with the clock's start."""

    def _start(start: datetime | None = None) -> Plant:
        start = start or clock_start()
        store = Store(database, tmp_path / "monitor-core", "acceptance", journal_path=tmp_path / "monitor-core" / "journal.jsonl")
        store.start(start - timedelta(seconds=1))
        engine = Engine(store.config(), store, start - timedelta(seconds=1))
        engine.restore(store.open_events(), start - timedelta(seconds=1))
        engine.set_connected(True, start - timedelta(seconds=1))
        line = machine.Line()
        line.publish(engine, start)
        return Plant(engine, store, line, start, names=engine.zone_names())

    return _start


# -- the notifier ---------------------------------------------------------------------------------------------------

@dataclass
class Notifier:
    """The notifier's service and its thread. `offset` moves its clock: 24 h of retries in a moment."""

    offset: timedelta = timedelta()
    service: Service | None = None
    thread: threading.Thread | None = None

    def clock(self) -> datetime:
        return datetime.now(timezone.utc) + self.offset

    def stop(self) -> None:
        self.service.stop()
        self.thread.join(10)


@pytest.fixture
def run_notifier(database):
    """The notifier on the database, delivering by the channels the api saved in `config_dir`."""
    running: list[Notifier] = []

    def _run(config_dir: Path) -> Notifier:
        n = Notifier()
        n.service = Service(NotifierSettings(database=database, config_dir=config_dir, instance="acceptance", poll_s=0.1,
                                             heartbeat_s=0.3), clock=n.clock)
        n.thread = threading.Thread(target=n.service.run, daemon=True)
        n.thread.start()
        running.append(n)
        return n

    yield _run
    for n in running:
        n.stop()


def wait_for(database, sql: str, until, params: tuple = (), timeout: float = 15) -> list[dict]:
    """The rows of `sql` once `until(rows)` holds (or what they are when the time is up)."""
    deadline = time.time() + timeout
    with database.connect() as conn:
        while True:
            rows = conn.execute(sql, params).fetchall()
            conn.commit()
            if until(rows) or time.time() > deadline:
                return rows
            time.sleep(0.1)
