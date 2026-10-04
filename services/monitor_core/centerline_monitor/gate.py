"""The snapshot gate (guide §6.2): judge only complete, fresh, valid data. Pure.

Evaluation runs only while the broker is connected, every mapped topic has sent a live
message within its area's freshness limit (ADR-0006), every mapped tag holds a number,
and the SKU field names a SKU the rules in effect are ready for (OPC-03, OPC-08). A placeholder
SKU stands in for the field while the machine publishes none, on actual values only (ADR-0022).
Retained messages never count as fresh. Once closed, the gate reopens only on a complete
fresh snapshot: a live message from every mapped topic since it closed (OPC-05).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass
class GateInputs:
    connected: bool
    last_live: dict[str, datetime]  # topic → arrival of its last live message (our clock)
    values: dict[str, float | None]  # tag → its latest number; None when missing or not a number
    sku: str | None


def area(topic: str) -> str:
    return topic.rsplit("/", 1)[-1]


class Gate:
    def __init__(self, freshness: dict[str, float], tags: list[str], sku_topic: str | None,
                 sku_ready: Callable[[str], bool], blockers: list[str] | None = None, placeholder: str | None = None):
        self.freshness = freshness  # mapped topic → seconds of silence it may have
        self.tags = tags
        self.sku_topic = sku_topic
        self.sku_ready = sku_ready
        self.placeholder = placeholder
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
        if self.sku_topic is None and self.placeholder is None:
            out.append("No SKU field is mapped yet (O-15)")
        elif not inp.sku:
            out.append("The SKU field is empty")
        elif not self.sku_ready(inp.sku):
            out.append(f"The rules in effect lack limits for the placeholder SKU {inp.sku}" if inp.sku == self.placeholder
                       else f"SKU {inp.sku} has no complete rules in effect")
        return out
