"""Storage (RES-02, ADR-0036): how full the disk under the journal and the database is, and what that means.

    normal ──80 %──▶ warning ──90 %──▶ cleanup ──still 90 % after 10 min──▶ degraded
       ◀──below 78 %──      ◀──below 90 %──                ◀──below 85 %── (to warning or normal)

At 90 % the backup agent runs the eligible cleanup: backup sets past their policy and expired idempotency keys,
nothing protected. If that doesn't bring it under 90 % within ten minutes, the system enters protected degraded mode
(O-12): monitoring, events, the reason workflow, notifications and backups carry on; brief-change records, the
Analytics query log and new uploads stop. An alert goes to the routing's system recipients on entering each state,
every hour while degraded, and when degraded mode ends. Nothing is ever deleted here.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from centerline_common.isotime import iso

from .effects import Notify

WARN_PCT = 80.0
WARN_CLEAR_PCT = 78.0
CLEANUP_PCT = 90.0
DEGRADED_CLEAR_PCT = 85.0  # the owner's choice (O-12, 2026-10-07): degraded mode ends below 85 %
CLEANUP_WAIT = timedelta(minutes=10)
REPEAT = timedelta(hours=1)
LABELS = {
    "warning": "Storage nearly full (RES-02)",
    "cleanup": "Storage at the cleanup limit (RES-02)",
    "degraded": "Protected degraded mode: storage full (RES-02)",
    "recovered": "Storage back under its limits (RES-02)",
}


def disk_used_pct(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return 100.0 * usage.used / usage.total if usage.total else 0.0


@dataclass
class StorageGuard:
    """The disks to watch: the journal's folder, on the same disk as the database's volume, and any others the
    settings name. The fullest one counts."""

    paths: list[Path]
    measure: Callable[[Path], float] = disk_used_pct
    state: str = "normal"
    since: datetime | None = None
    used_pct: float | None = None
    path: str | None = None
    alerts: int = 0  # alerts sent in this degraded period, for the hourly repeat's key
    error: str | None = None
    _cleanup_from: datetime | None = field(default=None, repr=False)

    @property
    def degraded(self) -> bool:
        return self.state == "degraded"

    def check(self, now: datetime) -> list[Notify]:
        """Measure, move between states, and return the alerts to send."""
        readings, errors = [], []
        for p in self.paths:
            try:
                readings.append((self.measure(p), str(p)))
            except OSError as e:
                errors.append(f"{p}: {e}")
        # An unreadable disk is reported even while the others are read
        self.error = "; ".join(errors) or None
        if not readings:
            return []  # nothing measurable: keep the last state, and say so in the status
        self.used_pct, self.path = max(readings)
        pct = self.used_pct
        before = self.state
        if self.state == "degraded":
            if pct < DEGRADED_CLEAR_PCT:
                self._enter("warning" if pct >= WARN_PCT else "normal", now)
        elif pct >= CLEANUP_PCT:
            if self.state != "cleanup":
                self._enter("cleanup", now)
                self._cleanup_from = now
            elif now - self._cleanup_from >= CLEANUP_WAIT:
                self._enter("degraded", now)
        elif pct >= WARN_PCT:
            if self.state in ("normal", "cleanup"):
                self._enter("warning", now)
        elif self.state != "normal" and (pct < WARN_CLEAR_PCT or self.state == "cleanup"):
            self._enter("normal", now)
        return self._alerts(before, now)

    def _enter(self, state: str, now: datetime) -> None:
        self.state, self.since = state, now
        if state != "degraded":
            self.alerts = 0

    def _alerts(self, before: str, now: datetime) -> list[Notify]:
        def notify(key: str, label: str) -> Notify:
            return Notify(f"storage:{key}", "system", now, {
                "kind": label, "usedPct": round(self.used_pct or 0, 1), "disk": self.path, "state": self.state,
                "since": iso(self.since)})

        since = iso(self.since) or ""
        if self.state == "degraded":
            due = before != "degraded" or now - self.since >= REPEAT * self.alerts
            if due:
                self.alerts += 1
                return [notify(f"degraded:{since}:{self.alerts}", LABELS["degraded"])]
            return []
        if before == "degraded":
            return [notify(f"recovered:{since}", LABELS["recovered"])]
        if self.state != before and self.state in ("warning", "cleanup"):
            return [notify(f"{self.state}:{since}", LABELS[self.state])]
        return []

    def status(self) -> dict:
        """What the heartbeat carries: the api refuses uploads and every page shows a banner from it."""
        return {"state": self.state, "usedPct": None if self.used_pct is None else round(self.used_pct, 1),
                "disk": self.path, "since": iso(self.since), "error": self.error,
                "limits": {"warn": WARN_PCT, "cleanup": CLEANUP_PCT, "degradedUntilBelow": DEGRADED_CLEAR_PCT}}
