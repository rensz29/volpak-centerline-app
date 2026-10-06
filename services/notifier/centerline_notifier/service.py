"""The notifier as a service (SDD §8, ADR-0023).

One thread per channel delivers, so a Teams outage never blocks email. The main thread routes
new messages every second, watches monitor-core's heartbeat, and writes its own every 2 s.
Each thread has its own database connection and carries on when the database comes back.
The channel settings are read from the Configuration page's files before each batch, so a
change there applies at once.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from centerline_common import connections, roles
from centerline_common.channels import Email, Outcome, Teams
from centerline_common.db import REPO, DatabaseConfig, DatabaseUnavailable
from centerline_common.isotime import iso

from . import store

log = logging.getLogger("centerline.notifier")
NOTIFIER_DIR = Path(__file__).resolve().parents[1]
FAILURES = (psycopg.OperationalError, psycopg.InterfaceError, DatabaseUnavailable)
CHANNELS = ("teams", "email")


@dataclass(frozen=True)
class NotifierSettings:
    database: DatabaseConfig = field(default_factory=lambda: roles.app_database(DatabaseConfig()))  # ADR-0020
    config_dir: Path = REPO / "config"
    instance: str = field(default_factory=socket.gethostname)
    poll_s: float = 1.0  # a new message is routed, and a due delivery tried, within about this long (NOT-04: 10 s)
    heartbeat_s: float = 2.0
    stale_s: float = 60.0  # monitor-core silent this long: a Critical system alert (SDD §8)
    batch: int = 10


def load_settings(path: str | Path | None = None) -> NotifierSettings:
    """From CENTERLINE_NOTIFIER_CONFIG or services/notifier/config.json, if either exists; else the dev defaults."""
    p = Path(path or os.environ.get("CENTERLINE_NOTIFIER_CONFIG") or NOTIFIER_DIR / "config.json")
    if not p.exists():
        return NotifierSettings()
    raw = json.loads(p.read_text(encoding="utf-8"))
    base = p.resolve().parent
    return NotifierSettings(
        database=DatabaseConfig.from_dict(raw["database"], base) if raw.get("database") else roles.app_database(DatabaseConfig()),
        config_dir=(base / raw["config_dir"]).resolve() if raw.get("config_dir") else REPO / "config",
        instance=raw.get("instance") or socket.gethostname(),
        stale_s=float(raw.get("stale_s", 60)))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Service:
    def __init__(self, settings: NotifierSettings, clock=utcnow):
        self.settings = settings
        self.clock = clock
        self.stopping = threading.Event()
        self.started = clock()
        self.lock = threading.Lock()
        self.lanes = {name: {"lastOk": None, "lastError": None} for name in CHANNELS}

    def stop(self) -> None:
        self.stopping.set()

    # -- channels -------------------------------------------------------------------------

    def _channel(self, name: str):
        cfg = connections.notifications_config(self.settings.config_dir)
        if name == "teams":
            return Teams(cfg["teams"]["url"], cfg["teams"]["timeout_s"]) if cfg["teams"] else None
        return Email(cfg["email"]) if cfg["email"] else None

    @staticmethod
    def _send(name: str, channel, d: dict) -> Outcome:
        if channel is None:
            return Outcome(False, f"{'Teams' if name == 'teams' else 'Email'} isn't set up on Configuration → Connections")
        c = d["content"]
        if name == "teams":
            return channel.send(c["teams"])
        return channel.send(d["target"], c["subject"], c["body"], d["message_id"])

    def _lane(self, name: str) -> None:
        conn = None
        while not self.stopping.is_set():
            try:
                conn = conn or self.settings.database.connect()
                due = store.claim(conn, name, self.clock(), self.settings.batch)
                if due:
                    channel = self._channel(name)
                    for d in due:
                        started = self.clock()
                        outcome = self._send(name, channel, d)
                        status = store.finish(conn, d, name, outcome, started, self.clock())
                        with self.lock:
                            self.lanes[name]["lastOk" if outcome.ok else "lastError"] = (
                                iso(started) if outcome.ok else {"at": iso(started), "error": outcome.response})
                        log.info("%s to %s, attempt %d: %s (%s)", name, d["target"], d["attempt"], status, outcome.response)
                    continue  # more may be due
            except FAILURES as e:
                log.warning("%s lane: the database is unavailable (%s); trying again", name, e)
                conn = self._close(conn)
            self.stopping.wait(self.settings.poll_s)
        self._close(conn)

    # -- routing, watching, the heartbeat -----------------------------------------------------

    @staticmethod
    def _close(conn):
        if conn is not None:
            try:
                conn.close()
            except psycopg.Error:
                pass
        return None

    def run(self) -> None:
        lanes = [threading.Thread(target=self._lane, args=(name,), name=f"notifier-{name}", daemon=True) for name in CHANNELS]
        conn, next_beat, recovered = None, 0.0, False
        for t in lanes:
            t.start()
        log.info("notifier %s started", self.settings.instance)
        while not self.stopping.is_set():
            try:
                conn = conn or self.settings.database.connect()
                now = self.clock()
                if not recovered:
                    if n := store.recover(conn, now):
                        log.warning("%d deliveries were cut short by the last stop: trying them again", n)
                    recovered = True
                cfg = connections.notifications_config(self.settings.config_dir)
                while store.route_pending(conn, now, line=cfg["line"], app_url=cfg["app_url"]) == store.ROUTE_BATCH:
                    now = self.clock()
                if now.timestamp() >= next_beat:
                    if raised := store.watch_monitor(conn, now, self.settings.stale_s):
                        log.warning("monitor-core heartbeat: %s", raised)
                    with self.lock:
                        lanes_status = {name: {"configured": cfg[name] is not None, **self.lanes[name]} for name in CHANNELS}
                    store.beat(conn, self.settings.instance, self.started, now,
                               {"lanes": lanes_status, "backlog": store.backlog(conn), "appUrl": cfg["app_url"]})
                    next_beat = now.timestamp() + self.settings.heartbeat_s
            except FAILURES as e:
                log.warning("the database is unavailable (%s); trying again", e)
                conn = self._close(conn)
            self.stopping.wait(self.settings.poll_s)
        for t in lanes:
            t.join(30)
        self._close(conn)
        log.info("notifier stopped")
