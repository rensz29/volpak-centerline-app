"""monitor-core as a service (ADR-0014): the broker's messages in, the engine's effects out.

One thread judges. The MQTT client's thread only queues messages with their arrival time.
Timers fire when due; acknowledgments, zones switched off and maintenance windows are read
every 2 s (ADR-0016, ADR-0017); a heartbeat is written every 2 s (§6.7, ADR-0015); and the
configuration is re-read when another version takes effect.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from centerline_common import roles
from centerline_common.db import REPO, DatabaseConfig
from centerline_common.isotime import iso

from .engine import Engine
from .mqtt import Subscriber, utcnow
from .storage import StorageGuard
from .store import FAILURES, Store

log = logging.getLogger("centerline.monitor")
MONITOR_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MonitorSettings:
    database: DatabaseConfig = field(default_factory=lambda: roles.app_database(DatabaseConfig()))  # ADR-0020
    config_dir: Path = REPO / "config"
    instance: str = field(default_factory=socket.gethostname)
    heartbeat_s: float = 2  # also carries the live values the Digital Centerline page shows; stale after 60 s (§6.7)
    reload_s: float = 5
    ack_s: float = 2  # acknowledgments and monitoring control (switches, maintenance windows)
    journal_dir: Path = REPO / "data" / "journal"  # the disk journal (RES-01): a protected folder, 0700
    journal_limit_s: float = 1800  # RES-01's 30 min: past it, judging pauses and nothing is dropped
    storage_s: float = 60  # how often the disks are measured (RES-02)
    storage_paths: tuple[Path, ...] = ()  # disks to watch beside the journal's, such as the backups' (ADR-0036)


def load_settings(path: str | Path | None = None) -> MonitorSettings:
    """From CENTERLINE_MONITOR_CONFIG or services/monitor_core/config.json, if either exists; else the dev defaults."""
    p = Path(path or os.environ.get("CENTERLINE_MONITOR_CONFIG") or MONITOR_DIR / "config.json")
    if not p.exists():
        return MonitorSettings()
    raw = json.loads(p.read_text(encoding="utf-8"))
    base = p.resolve().parent
    return MonitorSettings(
        database=DatabaseConfig.from_dict(raw["database"], base) if raw.get("database") else roles.app_database(DatabaseConfig()),
        config_dir=(base / raw["config_dir"]).resolve() if raw.get("config_dir") else REPO / "config",
        instance=raw.get("instance") or socket.gethostname(),
        journal_dir=(base / raw["journal_dir"]).resolve() if raw.get("journal_dir") else REPO / "data" / "journal",
        journal_limit_s=float(raw.get("journal_limit_s", 1800)),
        storage_paths=tuple((base / p).resolve() for p in raw.get("storage_paths") or ()))


class Latency:
    """How long each message waited from its arrival to the end of its judging, over the last minute: PER-01 gives
    rule evaluation 2 s. The health page shows the longest (ADR-0038)."""

    def __init__(self, window: timedelta = timedelta(minutes=1)):
        self.window = window
        self.samples: deque[tuple[datetime, float]] = deque()

    def add(self, arrived: datetime, judged: datetime) -> None:
        self.samples.append((judged, (judged - arrived).total_seconds() * 1000))

    def status(self, now: datetime) -> dict:
        while self.samples and now - self.samples[0][0] > self.window:
            self.samples.popleft()
        ms = [m for _, m in self.samples]
        return {"maxMs": round(max(ms)) if ms else None, "messages": len(ms), "windowS": int(self.window.total_seconds())}


class Service:
    def __init__(self, settings: MonitorSettings):
        self.settings = settings
        self.store = Store(settings.database, settings.config_dir, settings.instance,
                           journal_path=settings.journal_dir / f"{settings.instance}.jsonl")
        self.storage = StorageGuard([settings.journal_dir, *settings.storage_paths])
        self.latency = Latency()
        self.inbox: queue.Queue = queue.Queue()
        self.subscriber: Subscriber | None = None
        self.stopping = threading.Event()

    def _subscribe(self, broker: dict | None) -> None:
        if self.subscriber is not None:
            self.subscriber.stop()
            self.subscriber = None
        if broker and broker.get("host"):
            self.subscriber = Subscriber(broker, lambda t, p, r, at: self.inbox.put(("message", t, p, r, at)),
                                         lambda ok, at: self.inbox.put(("connection", ok, at)))
            self.subscriber.start()
        else:
            log.warning("no broker saved on the Configuration page: nothing to judge")

    def _start(self) -> tuple[Engine, tuple]:
        while not self.stopping.is_set():
            try:
                now = utcnow()
                self.store.start(now)
                cfg = self.store.config()
                engine = Engine(cfg, self.store, now)
                engine.restore(self.store.open_events(), now)
                engine.set_control(*self.store.control(), now)  # before any message is judged
                return engine, self.store.signature()
            except FAILURES as e:
                log.warning("waiting for the database: %s", e)
                self.store.conn = None
                self.stopping.wait(5)
        raise SystemExit(0)

    def run(self) -> None:
        engine, signature = self._start()
        started = utcnow()
        self._subscribe(engine.cfg.broker)
        broker = engine.cfg.broker
        next_beat = next_reload = next_ack = next_storage = started
        try:
            while not self.stopping.is_set():
                due = engine.next_due()
                wait = 1.0 if due is None else max(0.0, min(1.0, (due - utcnow()).total_seconds()))
                try:
                    item = self.inbox.get(timeout=wait)
                    while item is not None:
                        self._dispatch(engine, item)
                        item = self.inbox.get_nowait()
                except queue.Empty:
                    pass
                now = utcnow()
                engine.tick(now)
                if now >= next_storage:
                    # Before anything that needs the database: the alerts wait in the journal if it's away
                    next_storage = now + timedelta(seconds=self.settings.storage_s)
                    alerts = self.storage.check(now)
                    if self.storage.degraded != engine.storage_degraded:
                        engine.storage_degraded = self.storage.degraded
                        log.warning("storage %s%% full: protected degraded mode %s", self.storage.used_pct,
                                    "begins" if self.storage.degraded else "ends")
                    engine.emit(alerts, now)
                try:
                    if now >= next_beat:
                        # First the journal and the limit, which need no database; each schedule moves on before
                        # its database call, so a lost database is tried again only every few seconds
                        next_beat = now + timedelta(seconds=self.settings.heartbeat_s)
                        self.store.drain(now)
                        engine.set_degraded(self._degraded(now), now)
                        if self.store.reachable(now):
                            self.store.heartbeat(now, started, {**engine.status(), "storage": {
                                **self.storage.status(), "briefChangesSkipped": engine.briefs_skipped},
                                "evaluation": self.latency.status(now),
                                "journal": {"steps": self.store.journal.steps, "oldestAt": iso(self.store.journal.oldest)}})
                    if now >= next_ack and self.store.reachable(now):
                        next_ack = now + timedelta(seconds=self.settings.ack_s)
                        for ack in self.store.new_acks():
                            engine.acknowledge(ack, now)
                        engine.set_control(*self.store.control(), now)
                        self.store.workflow_tick(now, engine.zone_names())  # shift ends and overdue reasons (WF-03)
                    if now >= next_reload and self.store.reachable(now):
                        next_reload = now + timedelta(seconds=self.settings.reload_s)
                        latest = self.store.signature()
                        if latest != signature:
                            engine.configure(self.store.config(), now)
                            signature = latest
                            if engine.cfg.broker != broker:
                                broker = engine.cfg.broker
                                engine.set_connected(False, now)
                                self._subscribe(broker)
                            log.info("configuration reloaded: rules v%s, mapping v%s, register %s", engine.cfg.rules_number,
                                     engine.cfg.mapping_number, engine.cfg.register.version)
                except FAILURES as e:
                    self.store._lost(e, now)  # judging carries on; writes wait in the journal (RES-01)
        finally:
            if self.subscriber is not None:
                self.subscriber.stop()

    def _degraded(self, now) -> str | None:
        """Past the journal's limit nothing new is judged until the database is back: nothing is dropped
        (RES-01). A full disk is the storage guard's (RES-02, storage.py)."""
        age = self.store.journal.age_s(now) if self.store.journal.pending else 0.0
        if age <= self.settings.journal_limit_s:
            return None
        return (f"The database has been unreachable for {age / 60:.0f} min, longer than the journal's "
                f"{self.settings.journal_limit_s / 60:.0f} min: judging is paused until it's back; everything so far is kept")

    def _dispatch(self, engine: Engine, item: tuple) -> None:
        if item[0] == "message":
            _, topic, payload, retained, at = item
            engine.on_message(topic, payload, retained, at)
            self.latency.add(at, utcnow())
        else:
            _, ok, at = item
            engine.set_connected(ok, at)

    def stop(self) -> None:
        self.stopping.set()
