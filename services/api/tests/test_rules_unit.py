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


def row(parameter_id, zone_id=None, **fields):
    return {"parameter_id": parameter_id, "zone_id": zone_id, **{f: fields.get(f) for f in rules.FIELDS}}


def test_the_zones_row_wins_over_the_parameters_field_by_field():
    rs = [row("P02", warn_low=2, warn_high=1, crit_low=4, crit_high=2, mismatch_delay_s=45),
          row("P02", "V3", warn_low=3, target=182)]
    v3 = rules.resolve(rs, DEFAULTS, "P02", "V3")
    assert (v3["target"].value, v3["target"].layer) == (182, "zone")
    assert (v3["warn_low"].value, v3["warn_low"].layer) == (3, "zone")
    assert (v3["warn_high"].value, v3["warn_high"].layer) == (1, "parameter")
    assert (v3["mismatch_delay_s"].value, v3["mismatch_delay_s"].layer) == (45, "parameter")
    assert (v3["recovery_delay_s"].value, v3["recovery_delay_s"].layer) == (15, "default")
    v1 = rules.resolve(rs, DEFAULTS, "P02", "V1")  # no row of its own
    assert v1["target"].value is None and v1["warn_low"].value == 2 and v1["crit_low"].value == 4


def test_rows_saved_for_a_sku_before_adr_0027_judge_nothing_and_carry_over_to_the_zones():
    rs = [row("P02", warn_low=2, warn_high=1, crit_low=4, crit_high=2),
          {**row("P02", "V1", target=220), "sku": "12345"}, {**row("P02", "V2", target=215), "sku": "12345"}]
    assert rules.resolve(rs, DEFAULTS, "P02", "V1")["target"].value is None
    carried, sku = rules.carry_over(rs)
    assert sku == "12345" and all("sku" not in r for r in carried)
    assert {(r["zone_id"], r["target"]) for r in carried if r["zone_id"]} == {("V1", 220), ("V2", 215)}
    assert rules.carry_over([row("P02", warn_low=2)]) == ([row("P02", warn_low=2)], None)  # nothing to carry


def test_readiness_lists_what_each_zone_lacks_and_limits_alone_let_the_line_be_judged():
    rs = [row("P02", warn_low=2, warn_high=1, crit_low=4, crit_high=2), row("P02", "V1", target=220)]
    gaps = rules.readiness(rs, DEFAULTS, ZONES)
    by_zone = {(g["parameter_id"], g["zone_id"]): g["missing"] for g in gaps}
    assert ("P02", "V1") not in by_zone and by_zone[("P02", "V2")] == ["target"]  # judged, HMI not
    assert set(by_zone[("P04", "FRONT")]) == {"target", *rules.LIMITS}  # P04 has no limits yet: the line waits
    assert not rules.limits_complete(rs, DEFAULTS, ZONES)
    assert rules.limits_complete(rs + [row("P04", warn_low=10, warn_high=9, crit_low=20, crit_high=18)], DEFAULTS, ZONES)


def test_validation_names_the_row_and_field():
    rs = [row("P02", warn_low=2, warn_high=1, crit_low=4, crit_high=2),
          row("P02", "V1", warn_low=5),  # combined with the parameter's crit_low 4: Critical inside Warning
          row("P08", warn_low=1),  # analytics only, not monitored
          row("P04", "NOPE", warn_low=1),
          row("P02", warn_low=1)]  # repeats row 1's scope
    errors = {e["field"]: e["message"] for e in rules.validate(rs, DEFAULTS, ZONES)}
    assert "Critical below (4) must be at least Warning below (5)" in errors["rules[1].warnLow"]
    assert "isn't monitored" in errors["rules[2].parameterId"]
    assert "no monitored zone NOPE" in errors["rules[3].zoneId"]
    assert "repeats row 1" in errors["rules[4]"]


def test_the_hash_ignores_row_order_and_number_spelling():
    a = [row("P02", warn_low=2, crit_low=Decimal("4.0")), row("P04", target=185.5)]
    b = [row("P04", target=Decimal("185.50")), row("P02", warn_low=Decimal("2"), crit_low=4)]
    settings = {"defaults": DEFAULTS}
    assert rules.digest(settings, a) == rules.digest(settings, b)
    assert rules.digest(settings, a) != rules.digest(settings, [row("P02", warn_low=2, crit_low=5), row("P04", target=185.5)])
