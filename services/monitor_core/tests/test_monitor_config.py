"""What monitor-core judges by: the rules in effect, one rule per zone (ADR-0012, ADR-0027)."""

from __future__ import annotations

from monitor_helpers import REG, make_config, rule_rows
from centerline_monitor import config as config_mod
from centerline_monitor.machines import ZoneRule


def test_a_pinned_rule_survives_a_restart_and_one_pinned_before_adr_0027_still_loads():
    rule = make_config().zone_rule(REG.zones[0])
    assert ZoneRule.from_pinned(rule.pinned(), rule.versions) == rule
    older = {**rule.pinned(), "sku": "67890123", "sku_placeholder": True}  # what events pinned before carry
    assert ZoneRule.from_pinned(older, rule.versions) == rule


def test_targets_are_optional_and_limits_are_not():
    no_targets = make_config(rows=rule_rows(with_targets=False))
    assert no_targets.ready() and no_targets.zone_rule(REG.zones[0]).target is None  # judged on actual values only
    no_limits = make_config(rows=[r for r in rule_rows() if r["zone_id"] is not None])
    assert not no_limits.ready() and no_limits.zone_rule(REG.zones[0]) is None


def test_the_rules_in_effect_come_from_the_database(seeded, tmp_path):
    with seeded.connect() as conn:
        cfg = config_mod.load(conn, tmp_path)
    assert (cfg.rules_number, cfg.mapping_number) == (1, 1) and cfg.ready()
    assert all(cfg.zone_rule(z).target is not None for z in REG.zones)  # every zone's target
