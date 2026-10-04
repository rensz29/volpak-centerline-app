"""Actual rules pause while the machine is stopped, and for a warm-up after long stops (ADR-0010). Pure.

HMI mismatch monitoring isn't affected. A stop that was already going on when monitor-core
started is treated as long, since its length is unknown.
"""

from __future__ import annotations

from datetime import datetime, timedelta


class StopPause:
    def __init__(self, enabled: bool = True, long_stop_min: int = 10, warmup_min: int = 30):
        self.configure(enabled, long_stop_min, warmup_min)
        self.state = "unknown"  # unknown | running | stopped | warmup
        self.stopped_since: datetime | None = None
        self.warmup_until: datetime | None = None

    def configure(self, enabled: bool, long_stop_min: int, warmup_min: int) -> None:
        self.enabled = enabled
        self.long_stop = timedelta(minutes=long_stop_min)
        self.warmup = timedelta(minutes=warmup_min)

    @property
    def paused(self) -> bool:
        return self.enabled and self.state in ("stopped", "warmup")

    def update(self, now: datetime, machine_run: float | None) -> str | None:
        """'pause', 'warmup' (still paused until warmup_until) or 'resume' when Actual rules change; else None."""
        if not self.enabled:
            was = self.paused_raw()
            self.state = "running"
            return "resume" if was else None
        if machine_run is None:
            return None
        if machine_run < 0.5:
            if self.state != "stopped":
                self.stopped_since = None if self.state == "unknown" else now
                self.state = "stopped"
                return "pause"
            return None
        if self.state == "stopped":
            long = self.stopped_since is None or now - self.stopped_since >= self.long_stop
            if long and self.warmup > timedelta(0):
                self.state, self.warmup_until = "warmup", now + self.warmup
                return "warmup"
            self.state = "running"
            return "resume"
        if self.state == "unknown":
            self.state = "running"
        return None

    def warmup_done(self, now: datetime) -> bool:
        if self.state == "warmup" and self.warmup_until is not None and now >= self.warmup_until:
            self.state, self.warmup_until = "running", None
            return True
        return False

    def paused_raw(self) -> bool:
        return self.state in ("stopped", "warmup")
