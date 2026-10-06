"""The parameter register (ADR-0007): config/parameter-register.json, or a version from the database.

Parameters keep their URS IDs. Each active parameter has one or more zones,
and each zone is a setpoint/actual tag pair monitored on its own; the zone's
channel ID is "<parameter>.<zone>", e.g. "P02.V3".

In Analytics every zone offers its actual value and, where it has one, its
setpoint (ADR-0009); their channel IDs are "<parameter>.<zone>.actual" and
"<parameter>.<zone>.setpoint". Parameters whose status is "analytics_only"
have an actual tag but no setpoint yet, which rules out HMI monitoring but
not correlation (ADR-0008).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_PATH = REPO / "config" / "parameter-register.json"
ANALYTICS_STATUSES = ("active", "analytics_only")


@dataclass(frozen=True)
class HmiMatch:
    """How setpoint and target are compared (HMI-01 default: truncate to whole numbers)."""

    method: str = "truncate"  # 'truncate' | 'round'
    decimals: int = 0

    def key(self, value: float) -> int:
        # Decimal(repr(...)) avoids float artefacts such as 0.29 * 100 = 28.999…
        scaled = Decimal(repr(float(value))).scaleb(self.decimals)
        mode = ROUND_DOWN if self.method == "truncate" else ROUND_HALF_UP
        return int(scaled.to_integral_value(rounding=mode))

    def describe(self) -> str:
        return f"{self.method} to {self.decimals} decimal{'s' if self.decimals != 1 else ''}"


@dataclass(frozen=True)
class Zone:
    """A monitored setpoint/actual pair."""

    parameter_id: str
    parameter_name: str
    zone_id: str
    zone_name: str
    unit: str | None
    setpoint: str  # full tag name
    actual: str  # full tag name
    hmi_match: HmiMatch

    @property
    def channel(self) -> str:
        return f"{self.parameter_id}.{self.zone_id}"


KINDS = ("actual", "setpoint")


@dataclass(frozen=True)
class AnalyticsVariable:
    """A zone's actual value or setpoint that may be X or Y in Analytics (ANA-04, ADR-0009)."""

    parameter_id: str
    parameter_name: str
    zone_id: str
    zone_name: str
    unit: str | None
    kind: str  # 'actual' | 'setpoint'
    tag: str  # full tag name
    area: str  # machine area, e.g. "SPC"

    @property
    def zone_channel(self) -> str:
        return f"{self.parameter_id}.{self.zone_id}"

    @property
    def channel(self) -> str:
        return f"{self.zone_channel}.{self.kind}"

    @property
    def label(self) -> str:
        """What people see: "Vertical 1 · Setpoint". No parameter IDs (ADR-0009)."""
        return f"{self.zone_name} · {self.kind.capitalize()}"


@dataclass
class Register:
    path: Path | None  # the file it came from; None when it came from the database (ADR-0012)
    version: str
    namespace: str
    context: dict[str, str]
    parameters: list[dict]
    zones: list[Zone] = field(default_factory=list)
    analytics: list[AnalyticsVariable] = field(default_factory=list)

    def full(self, rel: str) -> str:
        return f"{self.namespace}.{rel}"

    def monitored_tags(self) -> list[str]:
        return [t for z in self.zones for t in (z.setpoint, z.actual)]

    def candidate_tags(self) -> list[tuple[str, str]]:
        """(label, full tag) for tags named in the register but not yet monitored."""
        out = []
        for p in self.parameters:
            for rel in p.get("candidate_tags", []):
                out.append((f"{p['id']} {p['name']} (awaiting)", self.full(rel)))
        return out

    def group_of(self, tag: str) -> str:
        """Machine area the tag belongs to, e.g. 'SPC' or 'Dosing_Parameters'."""
        rest = tag[len(self.namespace) + 1:] if tag.startswith(self.namespace + ".") else tag
        return rest.split(".", 1)[0]

    def groups(self) -> list[str]:
        return sorted({self.group_of(t) for t in self.monitored_tags() + list(self.context.values())})

    def heartbeat_tag(self, area: str) -> str:
        """Every message from a machine area carries `_timestamp`; its samples are the arrivals."""
        return f"{self.namespace}.{area}._timestamp"

    def variable(self, channel: str) -> AnalyticsVariable | None:
        hit = next((v for v in self.analytics if v.channel == channel), None)
        if hit is None:  # a bare zone channel ("P02.V1", used before ADR-0009) means its actual value
            hit = next((v for v in self.analytics if v.zone_channel == channel and v.kind == "actual"), None)
        return hit

    def units(self) -> dict[str, str | None]:
        return {p["id"]: p.get("unit") for p in self.parameters}


def load(path: str | Path | None = None) -> Register:
    p = Path(path) if path else DEFAULT_PATH
    return parse(json.loads(p.read_text(encoding="utf-8")), p)


def parse(raw: dict, path: Path | None = None) -> Register:
    ns = raw["namespace"]
    default = HmiMatch(raw["hmi_match_default"]["method"], int(raw["hmi_match_default"]["decimals"]))
    reg = Register(
        path=path,
        version=raw.get("version", ""),
        namespace=ns,
        context={k: f"{ns}.{v}" for k, v in (raw.get("context_tags") or {}).items()},
        parameters=raw["parameters"],
    )
    for par in raw["parameters"]:
        status = par.get("status")
        m = par.get("hmi_match")
        match = HmiMatch(m["method"], int(m["decimals"])) if m else default
        for z in par.get("zones", []):
            if status in ANALYTICS_STATUSES:
                for kind in KINDS:
                    if z.get(kind):
                        tag = f"{ns}.{z[kind]}"
                        reg.analytics.append(AnalyticsVariable(par["id"], par["name"], z["id"], z["name"],
                                                               par.get("unit"), kind, tag, reg.group_of(tag)))
            if status == "active" and z.get("setpoint") and z.get("actual"):
                reg.zones.append(Zone(par["id"], par["name"], z["id"], z["name"], par.get("unit"),
                                      f"{ns}.{z['setpoint']}", f"{ns}.{z['actual']}", match))
    return reg
