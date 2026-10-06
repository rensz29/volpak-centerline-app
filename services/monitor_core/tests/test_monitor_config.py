"""A placeholder SKU (ADR-0022): while the machine publishes no SKU, the line is judged on actual values, and its
HMI setpoints wherever the Rules tab gives the placeholder a target (amended by the owner on 2026-10-02)."""

from __future__ import annotations

from conftest import use_placeholder
from monitor_helpers import REG, Line, advance, at, make_config, rule_rows, start
from centerline_monitor import config as config_mod
from centerline_monitor.effects import Notify, OpenEvent, Transition
from centerline_monitor.machines import ZoneRule


def placeholder_config(**kw):
    """The Phase 0 proposal as it stands: limits for every zone, no SKUs, no targets, and no SKU field mapped."""
    return make_config(skus=(), sku_place=None, sku_placeholder="PLACEHOLDER", **kw)


def test_a_placeholder_sku_judges_actual_values_but_not_the_hmi_setpoints():
    engine, store, line = start(Line(sku=None), placeholder_config())
    assert engine.gate.open and engine.sku == "PLACEHOLDER"
    line.set("P02.V1", setpoint=230)  # far from any standard: not judged, there's no target
    line.set("P03.REAR", actual=186)  # 6 above its setpoint: Warning
    advance(engine, line, 0, 40)
    (event,) = store.of(OpenEvent)
    assert (event.kind, event.severity, event.sku, event.zone.channel) == ("ACTUAL", "WARNING", "PLACEHOLDER", "P03.REAR")
    assert event.rule["sku_placeholder"] is True and event.rule["target"] is None and event.raw_target is None
    status = engine.status()
    assert status["judging"] and status["skuPlaceholder"] == "PLACEHOLDER"
    assert (status["zones"]["P02.V1"]["hmi"], status["zones"]["P02.V1"]["target"]) == ("NO_TARGET", None)
    assert status["zones"]["P03.REAR"]["bands"] == {"warnLow": "175", "warnHigh": "185", "critLow": "170", "critHigh": "190"}


def test_the_placeholders_targets_judge_the_hmi_setpoint_of_their_zones_and_only_theirs():
    # The proposal's limits, and targets for the placeholder on Vertical's zones only, as a Manager would type them
    rows = rule_rows(skus=()) + [r for r in rule_rows(skus=("PLACEHOLDER",)) if r["sku"] == "PLACEHOLDER" and r["parameter_id"] == "P02"]
    cfg = placeholder_config(rows=rows)
    assert cfg.sku_ready("PLACEHOLDER")  # the other zones without a target are still judged on actual values
    engine, store, line = start(Line(sku=None), cfg)
    status = engine.status()["zones"]
    assert (status["P02.V1"]["hmi"], status["P02.V1"]["target"]) == ("AT_TARGET", "220")
    assert (status["P03.REAR"]["hmi"], status["P03.REAR"]["target"]) == ("NO_TARGET", None)
    line.set("P02.V1", setpoint=222)  # off its target
    line.set("P03.REAR", setpoint=170)  # no target here: not judged on HMI
    advance(engine, line, 0, 31)
    (event,) = store.of(OpenEvent, kind="HMI_MISMATCH")
    assert (event.zone.channel, event.sku, event.raw_target, event.raw_hmi) == ("P02.V1", "PLACEHOLDER", 220, 222)
    assert event.rule["sku_placeholder"] is True and event.rule["target"] == "220"
    assert store.of(Notify, kind="initial", event_id=event.event_id)  # notified and its reason asked for, like any SKU's


def test_without_every_zones_limits_the_placeholder_waits_and_management_hears_once():
    engine, store, line = start(Line(sku=None), placeholder_config(rows=[]))
    advance(engine, line, 0, 5)
    assert not engine.gate.open
    assert engine.reasons == ["The rules in effect lack limits for the placeholder SKU PLACEHOLDER"]
    assert len(store.of(Notify, kind="system")) == 1  # OPC-08


def test_when_the_machine_publishes_its_sku_the_placeholder_ends_with_a_changeover():
    line = Line(sku="A")  # the edge team has added the field, but the mapping doesn't read it yet
    engine, store, line = start(line, placeholder_config())
    line.set("P03.REAR", actual=186)
    advance(engine, line, 0, 40)
    (event,) = store.of(OpenEvent)
    engine.configure(make_config(skus=("A",)), at(41))  # a mapping with the SKU field, and rules with A's targets
    advance(engine, line, 41, 50)
    assert [t.state for t in store.of(Transition, event_id=event.event_id)][-1] == "CLOSED_SKU_CHANGEOVER"
    assert [n.payload for n in store.of(Notify, kind="changeover")] == [{"from": "PLACEHOLDER", "to": "A"}]
    assert not store.of(Notify, kind="recovery") and not store.of(Notify, kind="system")  # no false OPC-08 alert
    assert engine.gate.open and engine.sku == "A" and engine.status()["skuPlaceholder"] is None
    assert engine.status()["zones"]["P02.V1"]["hmi"] == "AT_TARGET"  # HMI mismatch is judged again


def test_a_placeholder_rule_survives_a_restart():
    rule = placeholder_config().zone_rule(REG.zones[0], "PLACEHOLDER")
    assert ZoneRule.from_pinned(rule.pinned(), rule.versions) == rule


def test_the_placeholder_comes_from_the_mapping_in_effect(seeded, tmp_path):
    with seeded.connect() as conn:
        use_placeholder(conn)
        cfg = config_mod.load(conn, tmp_path)
    assert (cfg.sku_place, cfg.sku_placeholder, cfg.mapping_number) == (None, "PLACEHOLDER", 2)
    assert cfg.sku_ready("PLACEHOLDER") and not cfg.sku_ready("NOT-A-SKU")  # limits for every zone, no targets needed
    assert cfg.zone_rule(REG.zones[0], "PLACEHOLDER").target is None

