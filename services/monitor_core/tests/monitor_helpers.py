"""A simulated line, a recording store and a configuration for driving the engine in tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from centerline_common import register as register_mod
from centerline_common import rules as rules_mod
from centerline_monitor.config import EngineConfig
from centerline_monitor.engine import Engine

REPO = Path(__file__).resolve().parents[3]
REGISTER = REPO / "tools" / "timebase-analysis" / "tests" / "parameter-register.json"
REG = register_mod.load(REGISTER)
BASE = "Unilever_Ph_Nutrition/Dressings_Halal/Filling/Volpak/Filler"
T0 = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
SIM_TARGETS = {"P02": [220, 215, 215, 220, 214, 214], "P03": [180, 180], "P04": [185, 185], "P06": [98, 98, 98], "P09": [1.3]}
PROPOSED = {"P02": (2, 1, 4, 2), "P03": (5, 5, 10, 10), "P04": (10, 9, 20, 18), "P06": (9, 9, 18, 18), "P09": (0.05, 0.05, 0.1, 0.1)}
DEFAULTS = {"mismatch_delay_s": 30, "warning_delay_s": 30, "critical_delay_s": 10, "recovery_delay_s": 15,
            "brief_change_mode": "lightweight", "warning_notifications": True}


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def targets() -> dict[str, float]:
    out = {}
    for z in REG.zones:
        same = [q.zone_id for q in REG.zones if q.parameter_id == z.parameter_id]
        values = SIM_TARGETS[z.parameter_id]
        out[z.channel] = values[same.index(z.zone_id) % len(values)]
    return out


def rule_row(**f) -> dict:
    return {"zone_id": None, **{k: None for k in rules_mod.FIELDS}, **f}


def rule_rows(with_targets: bool = True, extra: list[dict] | None = None) -> list[dict]:
    """The proposal's limits per parameter and, unless told not to, every zone's target (the simulator's setpoint)."""
    rows = [rule_row(parameter_id=p, warn_low=Decimal(str(a)), warn_high=Decimal(str(b)), crit_low=Decimal(str(c)),
                     crit_high=Decimal(str(d))) for p, (a, b, c, d) in PROPOSED.items()]
    if with_targets:
        rows += [rule_row(parameter_id=z.parameter_id, zone_id=z.zone_id, target=Decimal(str(targets()[z.channel])))
                 for z in REG.zones]
    return rows + (extra or [])


def make_config(rows=None, settings=None, rules_number=1) -> EngineConfig:
    rel = lambda t: t[len(REG.namespace) + 1:]  # noqa: E731
    tags = [rel(t) for z in REG.zones for t in (z.setpoint, z.actual)] + [rel(t) for t in REG.context.values()]
    cfg = EngineConfig(register=REG, register_version_id=uuid4(),
                       mapping={t: (f"{BASE}/{t.split('.', 1)[0]}", t.split(".", 1)[1]) for t in tags},
                       mapping_version_id=uuid4(), mapping_number=1,
                       settings=settings or {"pause_when_stopped": {"enabled": True, "long_stop_min": 10, "warmup_min": 30},
                                             "defaults": DEFAULTS},
                       rules=rule_rows() if rows is None else rows, config_version_id=uuid4(), rules_number=rules_number,
                       freshness_s={"SPC": 30, "Dosing_Parameters": 90})
    cfg.__post_init__()
    return cfg


class FakeStore:
    def __init__(self):
        self.fx: list = []

    def apply(self, fx, now):
        self.fx.extend(fx)

    def of(self, effect, **match) -> list:
        return [e for e in self.fx if isinstance(e, effect) and all(getattr(e, k) == v for k, v in match.items())]

    def clear(self):
        self.fx.clear()


class Line:
    """The machine as MQTT sees it: every tag's value, published one message per area."""

    def __init__(self):
        self.values: dict[str, float] = {}
        for z in REG.zones:
            t = targets()[z.channel]
            self.values[z.setpoint] = t
            self.values[z.actual] = t
        self.values[REG.context["machine_run"]] = 1
        self.values[REG.context["machine_speed"]] = 41
        self.silent: set[str] = set()
        self.clock_behind_s = 0.0  # the machine stamps _timestamp on its own clock (the plant's ran 114 s slow, ADR-0006)

    def set(self, channel: str, setpoint=None, actual=None, follow=True):
        z = next(z for z in REG.zones if z.channel == channel)
        if setpoint is not None:
            self.values[z.setpoint] = setpoint
            if follow and actual is None:
                self.values[z.actual] = setpoint
        if actual is not None:
            self.values[z.actual] = actual

    def run(self, value: int):
        self.values[REG.context["machine_run"]] = value

    def publish(self, engine: Engine, now: datetime) -> None:
        areas: dict[str, dict] = {}
        for tag, v in self.values.items():
            rel = tag[len(REG.namespace) + 1:]
            area, field = rel.split(".", 1)
            areas.setdefault(area, {})[field] = v
        for area, fields in areas.items():
            if area not in self.silent:
                stamp = round((now.timestamp() - self.clock_behind_s) * 1000)
                engine.on_message(f"{BASE}/{area}", json.dumps({"_timestamp": stamp, **fields}).encode(), False, now)


def start(line: Line | None = None, cfg: EngineConfig | None = None, t: float = 0) -> tuple[Engine, FakeStore, Line]:
    """An engine started a second before `t`, connected, with the line's first messages at `t`."""
    store, line = FakeStore(), line or Line()
    engine = Engine(cfg or make_config(), store, at(t - 1))
    engine.set_connected(True, at(t - 1))
    line.publish(engine, at(t))
    return engine, store, line


def advance(engine: Engine, line: Line, frm: float, to: float, every: float = 1.0) -> None:
    """Publish every `every` seconds and let timers fire, from `frm` (exclusive) to `to` (inclusive)."""
    t = frm
    while t < to:
        t = min(t + every, to)
        line.publish(engine, at(t))
        engine.tick(at(t))
