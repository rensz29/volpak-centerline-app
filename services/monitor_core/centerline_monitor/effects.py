"""What the state machines decide. The store writes one step's effects in one transaction
(invariant 6), so an event, its transition and its notification exist together or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from centerline_common.db import uuid7


@dataclass(frozen=True)
class Versions:
    """What an event is judged against (OPC-07): the rules, mapping and register in effect."""

    config_version_id: UUID
    mapping_version_id: UUID
    register_version_id: UUID


@dataclass(frozen=True)
class ZoneRef:
    parameter_id: str
    parameter_name: str
    zone_id: str
    zone_name: str
    unit: str | None = None

    @property
    def channel(self) -> str:
        return f"{self.parameter_id}.{self.zone_id}"


@dataclass(frozen=True)
class OpenEvent:
    event_id: UUID
    kind: str  # HMI_MISMATCH | ACTUAL
    zone: ZoneRef
    at: datetime
    versions: Versions
    rule: dict  # the resolved rule, pinned until the event closes
    raw_target: Decimal | None = None
    raw_hmi: Decimal | None = None
    raw_actual: Decimal | None = None
    severity: str | None = None
    supersedes: UUID | None = None


@dataclass(frozen=True)
class Transition:
    event_id: UUID
    state: str  # OPEN, WARNING, CRITICAL, RESOLVED, SUPERSEDED, CLOSED_MONITORING_DISABLED, ACKNOWLEDGED
    at: datetime
    inputs: dict = field(default_factory=dict)
    severity: str | None = None
    open: bool = True
    id: UUID = field(default_factory=uuid7)


@dataclass(frozen=True)
class BriefChange:
    """A setpoint back on target before the delay ended (HMI-05): recorded, never notified."""

    id: UUID
    zone: ZoneRef
    mode: str  # lightweight | cleared_before_trigger
    started_at: datetime
    ended_at: datetime
    versions: Versions
    raw_target: Decimal | None
    raw_hmi: Decimal | None
    evidence: dict | None = None


@dataclass(frozen=True)
class Notify:
    """An outbox row (NOT-03); the dedup key blocks a repeat after a restart (MNT-02)."""

    dedup_key: str
    kind: str
    at: datetime
    payload: dict
    event_id: UUID | None = None


@dataclass(frozen=True)
class StartTimer:
    key: str
    kind: str
    due: datetime
    event_id: UUID | None = None
    id: UUID = field(default_factory=uuid7)


@dataclass(frozen=True)
class CancelTimer:
    key: str


@dataclass(frozen=True)
class TimerDone:
    key: str
    at: datetime


@dataclass(frozen=True)
class PauseStarted:
    scope: str  # line (the snapshot gate) | actual (machine stopped, ADR-0010)
    at: datetime
    reasons: list[str]
    id: UUID = field(default_factory=uuid7)


@dataclass(frozen=True)
class PauseEnded:
    scope: str
    at: datetime
