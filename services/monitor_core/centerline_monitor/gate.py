"""The snapshot gate (guide §6.2): judge only complete, fresh, valid data. Pure.

Evaluation runs only while the broker is connected, every mapped topic has sent a live
message within its area's freshness limit (ADR-0006), every mapped tag holds a number,
and the rules in effect give every zone its limits (OPC-03).
Retained messages never count as fresh. Once closed, the gate reopens only on a complete
fresh snapshot: a live message from every mapped topic since it closed (OPC-05).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

# The one reason Management is alerted for (OPC-08 as ADR-0027 amends it): the data is complete, the rules aren't
RULES_INCOMPLETE = "The rules in effect don't give every zone its Warning and Critical limits (Configuration → Rules)"


@dataclass
class GateInputs:
    connected: bool
    last_live: dict[str, datetime]  # topic → arrival of its last live message (our clock)
    values: dict[str, float | None]  # tag → its latest number; None when missing or not a number


def area(topic: str) -> str:
    return topic.rsplit("/", 1)[-1]


class Gate:
    def __init__(self, freshness: dict[str, float], tags: list[str], ready: Callable[[], bool],
                 blockers: list[str] | None = None):
        self.freshness = freshness  # mapped topic → seconds of silence it may have
        self.tags = tags
        self.ready = ready  # the rules in effect give every zone its limits
        self.blockers = blockers or []  # e.g. no rules or no mapping in effect
        self.open = False
        self.closed_since: datetime | None = None

    def reasons(self, now: datetime, inp: GateInputs) -> list[str]:
        """Why the gate must be closed now; empty when it may be open."""
        out = list(self.blockers)
        if not inp.connected:
            out.append("The broker connection is down")
        for topic, limit in self.freshness.items():
            t = inp.last_live.get(topic)
            if t is None:
                out.append(f"No live message from {area(topic)} yet")
            elif (now - t).total_seconds() > limit:
                out.append(f"{area(topic)} silent for {(now - t).total_seconds():.0f} s (limit {limit:.0f} s)")
            elif not self.open and self.closed_since is not None and t <= self.closed_since:
                out.append(f"Waiting for a fresh message from {area(topic)}")
        missing = [tag for tag in self.tags if inp.values.get(tag) is None]
        if missing:
            out.append(f"No valid value for {', '.join(missing[:3])}" + (f" and {len(missing) - 3} more" if len(missing) > 3 else ""))
        if not self.blockers and not self.ready():
            out.append(RULES_INCOMPLETE)
        return out
