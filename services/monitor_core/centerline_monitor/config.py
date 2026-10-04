"""What monitor-core judges against (ADR-0014): the register, tag mapping and rules in effect
from the database, and the broker and per-area freshness from config/connections.json.

Reloaded whenever another version takes effect; open events keep the rule they opened
under (OPC-07). Missing pieces don't stop the service: they keep the snapshot gate closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from centerline_common import connections, register as register_mod
from centerline_common import rules as rules_mod
from centerline_common.register import Register, Zone

from .effects import Versions, ZoneRef
from .machines import ZoneRule
from .rules import Limits

DEFAULT_FRESHNESS_S = 30  # for an area connections.json doesn't list (SPC is 30, Dosing_Parameters 90: ADR-0006)


def zone_ref(z: Zone) -> ZoneRef:
    return ZoneRef(z.parameter_id, z.parameter_name, z.zone_id, z.zone_name, z.unit)


@dataclass(eq=False)
class EngineConfig:
    register: Register
    register_version_id: UUID
    mapping: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # tag → (topic, field)
    sku_place: tuple[str, str] | None = None
    sku_placeholder: str | None = None  # stands in for the SKU field while the machine has none (ADR-0022)
    mapping_version_id: UUID | None = None
    mapping_number: int | None = None
    settings: dict | None = None  # the rules version's line-wide settings
    rules: list[dict] = field(default_factory=list)
    config_version_id: UUID | None = None
    rules_number: int | None = None
    skus: tuple[str, ...] = ()
    freshness_s: dict[str, int] = field(default_factory=dict)
    broker: dict | None = None  # ready to connect, password included; never logged

    def rel(self, tag: str) -> str:
        ns = self.register.namespace
        return tag[len(ns) + 1:] if tag.startswith(ns + ".") else tag

    def blockers(self) -> list[str]:
        out = []
        if self.config_version_id is None:
            out.append("No rules are in effect (Configuration → Rules)")
        if self.mapping_version_id is None:
            out.append("No tag mapping is in effect (Configuration → Mappings)")
        return out

    def versions(self) -> Versions:
        return Versions(self.config_version_id, self.mapping_version_id, self.register_version_id)

    def needed_tags(self) -> list[str]:
        """Every monitored zone's setpoint and actual, and the machine-state tags."""
        tags = [self.rel(t) for z in self.register.zones for t in (z.setpoint, z.actual)]
        tags += [self.rel(t) for t in self.register.context.values()]
        return list(dict.fromkeys(tags))

    def machine_run_tag(self) -> str | None:
        tag = self.register.context.get("machine_run")
        return self.rel(tag) if tag else None

    def topic_freshness(self) -> dict[str, float]:
        """Each mapped topic's freshness limit: the strictest of the areas of the tags on it."""
        out: dict[str, float] = {}
        for tag in self.needed_tags():
            place = self.mapping.get(tag)
            if place is None:
                continue
            limit = float(self.freshness_s.get(tag.split(".", 1)[0], DEFAULT_FRESHNESS_S))
            out[place[0]] = min(limit, out.get(place[0], limit))
        return out

    def sku_ready(self, sku: str) -> bool:
        return self._ready(sku)

    def zone_rule(self, zone: Zone, sku: str) -> ZoneRule | None:
        return self._zone_rule(zone.channel, sku)

    def __post_init__(self):
        # cached per config object: a reload builds a new one
        self._ready = lru_cache(maxsize=64)(self._compute_ready)
        self._zone_rule = lru_cache(maxsize=4096)(self._compute_zone_rule)

    def _compute_ready(self, sku: str) -> bool:
        if self.settings is None:
            return False
        gaps = rules_mod.readiness(self.rules, self.settings["defaults"], self.register.zones, [sku])[sku]
        if sku == self.sku_placeholder:  # every zone needs its limits; a target is optional (ADR-0022, amended 2026-10-02)
            return all(g["missing"] == ["target"] for g in gaps)
        return sku in self.skus and gaps == []

    def _compute_zone_rule(self, channel: str, sku: str) -> ZoneRule | None:
        if self.settings is None:
            return None
        zone = next(z for z in self.register.zones if z.channel == channel)
        eff = rules_mod.resolve(self.rules, self.settings["defaults"], zone.parameter_id, zone.zone_id, sku)
        # Under a placeholder a zone may have no target: then its HMI setpoint isn't judged (ADR-0022, amended 2026-10-02)
        placeholder = sku == self.sku_placeholder
        if any(eff[f].value is None for f in (rules_mod.LIMITS if placeholder else ("target", *rules_mod.LIMITS))):
            return None

        def d(f: str) -> Decimal:
            return Decimal(str(eff[f].value))

        return ZoneRule(sku=sku, target=None if eff["target"].value is None else d("target"), sku_placeholder=placeholder, limits=Limits(d("warn_low"), d("warn_high"), d("crit_low"), d("crit_high")),
                        mismatch_delay_s=int(eff["mismatch_delay_s"].value), warning_delay_s=int(eff["warning_delay_s"].value),
                        critical_delay_s=int(eff["critical_delay_s"].value), recovery_delay_s=int(eff["recovery_delay_s"].value),
                        brief_change_mode=eff["brief_change_mode"].value, warning_notifications=bool(eff["warning_notifications"].value),
                        match=zone.hmi_match, versions=self.versions(), rules_number=self.rules_number)


def load(conn, config_dir: Path) -> EngineConfig:
    reg = conn.execute("SELECT id, content FROM register_version ORDER BY seq DESC LIMIT 1").fetchone()
    if reg is None:
        raise RuntimeError("The register isn't in the database yet: start the api once so it imports it")
    cfg = EngineConfig(register=register_mod.parse(reg["content"]), register_version_id=reg["id"])

    m = conn.execute("""SELECT id, number, sku_topic, sku_field, sku_placeholder
                          FROM mapping_version WHERE id = active_mapping_version()""").fetchone()
    if m:
        cfg.mapping_version_id, cfg.mapping_number = m["id"], m["number"]
        cfg.mapping = {r["tag"]: (r["topic"], r["field"]) for r in
                       conn.execute("SELECT tag, topic, field FROM tag_mapping WHERE mapping_version_id = %s", (m["id"],))}
        cfg.sku_place = (m["sku_topic"], m["sku_field"]) if m["sku_topic"] else None
        cfg.sku_placeholder = None if m["sku_topic"] else m["sku_placeholder"]

    v = conn.execute("SELECT id, number, settings FROM config_version WHERE id = active_config_version()").fetchone()
    if v:
        cfg.config_version_id, cfg.rules_number, cfg.settings = v["id"], v["number"], v["settings"]
        cfg.rules = [{"sku": r["sku_code"], "parameter_id": r["parameter_id"], "zone_id": r["zone_id"],
                      **{f: r[f] for f in rules_mod.FIELDS}}
                     for r in conn.execute(f"SELECT sku_code, parameter_id, zone_id, {', '.join(rules_mod.FIELDS)} "
                                           "FROM sku_parameter_rule WHERE config_version_id = %s", (v["id"],))]
    cfg.skus = tuple(r["code"] for r in conn.execute("SELECT code FROM sku"))
    conn.commit()

    mqtt = connections.load(config_dir).get("mqtt") or {}
    cfg.freshness_s = {k: int(s) for k, s in (mqtt.get("freshness_s") or {}).items()}
    cfg.broker = connections.mqtt_client_config(config_dir)
    cfg.__post_init__()
    return cfg


def signature(conn, config_dir: Path) -> tuple:
    """Changes when anything monitor-core reads changes, so it knows to reload."""
    row = conn.execute("""SELECT (SELECT id FROM register_version ORDER BY seq DESC LIMIT 1) AS r,
                                 active_mapping_version() AS m, active_config_version() AS c,
                                 (SELECT count(*) FROM sku) AS s""").fetchone()
    conn.commit()
    path = config_dir / "connections.json"
    return (row["r"], row["m"], row["c"], row["s"], path.stat().st_mtime_ns if path.exists() else None)
