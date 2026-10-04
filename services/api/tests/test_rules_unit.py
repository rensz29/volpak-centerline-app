"""Rule layers, validation, readiness and the content hash (centerline_common.rules), without a database."""

from __future__ import annotations

from decimal import Decimal

from centerline_common import register as register_mod
from centerline_common import rules

from .conftest import REGISTER

REG = register_mod.load(REGISTER)
ZONES = [z for z in REG.zones if z.parameter_id in ("P02", "P04")]
DEFAULTS = {"mismatch_delay_s": 30, "warning_delay_s": 30, "critical_delay_s": 10, "recovery_delay_s": 15,
            "brief_change_mode": "lightweight", "warning_notifications": True}


def row(parameter_id, zone_id=None, sku=None, **fields):
    return {"sku": sku, "parameter_id": parameter_id, "zone_id": zone_id, **{f: fields.get(f) for f in rules.FIELDS}}


def test_the_most_specific_row_wins_field_by_field():
    rs = [row("P02", warn_low=2, warn_high=1, crit_low=4, crit_high=2, mismatch_delay_s=45),
          row("P02", "V3", warn_low=3),
          row("P02", sku="A", target=180, crit_low=6),
          row("P02", "V3", sku="A", target=182)]
    v3 = rules.resolve(rs, DEFAULTS, "P02", "V3", "A")
    assert (v3["target"].value, v3["target"].layer) == (182, "sku_zone")
    assert (v3["crit_low"].value, v3["crit_low"].layer) == (6, "sku")
    assert (v3["warn_low"].value, v3["warn_low"].layer) == (3, "zone")
    assert (v3["warn_high"].value, v3["warn_high"].layer) == (1, "parameter")
    assert (v3["mismatch_delay_s"].value, v3["mismatch_delay_s"].layer) == (45, "parameter")
    assert (v3["recovery_delay_s"].value, v3["recovery_delay_s"].layer) == (15, "default")
    other = rules.resolve(rs, DEFAULTS, "P02", "V1", "B")  # an SKU without rows of its own
    assert other["target"].value is None and other["warn_low"].value == 2 and other["crit_low"].value == 4


def test_readiness_lists_zones_without_a_target_or_limits():
    rs = [row("P02", warn_low=2, warn_high=1, crit_low=4, crit_high=2), row("P02", sku="A", target=180)]
    ready = rules.readiness(rs, DEFAULTS, ZONES, ["A", "B"])
    assert {g["zone_id"] for g in ready["A"]} == {"FRONT", "REAR"}  # P04 has no limits or targets yet
    assert all(set(g["missing"]) == {"target", *rules.LIMITS} for g in ready["A"])
    assert len(ready["B"]) == len(ZONES) and ready["B"][0]["missing"] == ["target"]  # P02 limits apply to every SKU


def test_validation_names_the_row_and_field():
    rs = [row("P02", warn_low=2, warn_high=1, crit_low=4, crit_high=2),
          row("P02", sku="A", warn_low=5),  # combined with the parameter's crit_low 4: Critical inside Warning
          row("P08", warn_low=1),  # analytics only, not monitored
          row("P04", "NOPE", warn_low=1),
          row("P02", sku="ZZZ", target=1),
          row("P02", warn_low=1)]  # repeats row 1's scope
    errors = {e["field"]: e["message"] for e in rules.validate(rs, DEFAULTS, ZONES, {"A"})}
    assert "Critical below (4) must be at least Warning below (5)" in errors["rules[1].warnLow"]
    assert "isn't monitored" in errors["rules[2].parameterId"]
    assert "no monitored zone NOPE" in errors["rules[3].zoneId"]
    assert "ZZZ" in errors["rules[4].sku"]
    assert "repeats row 1" in errors["rules[5]"]


def test_the_hash_ignores_row_order_and_number_spelling():
    a = [row("P02", warn_low=2, crit_low=Decimal("4.0")), row("P04", target=185.5)]
    b = [row("P04", target=Decimal("185.50")), row("P02", warn_low=Decimal("2"), crit_low=4)]
    settings = {"defaults": DEFAULTS}
    assert rules.digest(settings, a) == rules.digest(settings, b)
    assert rules.digest(settings, a) != rules.digest(settings, [row("P02", warn_low=2, crit_low=5), row("P04", target=185.5)])
