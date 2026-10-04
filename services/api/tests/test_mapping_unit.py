"""Tag mapping logic (centerline_common.mapping), without a database or a broker."""

from __future__ import annotations

from centerline_common import mapping
from centerline_common import register as register_mod

from .conftest import REGISTER

REG = register_mod.load(REGISTER)
BASE = "Unilever_Ph_Nutrition/Dressings_Halal/Filling/Volpak/Filler"
SUBS = [BASE + "/#"]


def by_convention() -> list[dict]:
    """Where the plant broker puts every tag: one topic per area, one JSON field per tag."""
    return [{"tag": r.tag, "topic": f"{BASE}/{r.tag.split('.', 1)[0]}", "field": r.tag.split(".", 1)[1]}
            for r in mapping.required(REG)]


def test_required_tags_are_the_monitored_zones_and_machine_state():
    req = mapping.required(REG)
    assert len(req) == 2 * len(REG.zones) + len(REG.context)
    assert {r.tag for r in req if r.kind == "context"} == {"SPC.Machine_Run", "SPC.Machine_Speed"}
    v1 = next(r for r in req if r.tag == "SPC.SetPointTemperatureVertical1")
    assert (v1.kind, v1.parameter_id, v1.zone_id, v1.label) == ("setpoint", "P02", "V1", "Vertical 1 setpoint")


def test_topic_filters_match_like_mqtt():
    assert mapping.matches("a/#", "a") and mapping.matches("a/#", "a/b/c") and mapping.matches("a/+/c", "a/b/c")
    assert not mapping.matches("a/+", "a/b/c") and not mapping.matches("a/b", "a/c") and not mapping.matches("a/+/c", "a/b")


def test_a_full_mapping_by_convention_is_valid_and_covers_the_register():
    rows = by_convention()
    errors, warnings = mapping.validate(rows, None, REG, SUBS)
    assert errors == [] and any("No SKU field" in w for w in warnings)
    assert mapping.coverage(rows, REG)["missing"] == []
    assert mapping.validate(rows, {"topic": f"{BASE}/SPC", "field": "SKU_Code"}, REG, SUBS) == ([], [])


def test_validation_names_the_row_and_field():
    rows = by_convention()
    rows[1] = {**rows[0], "tag": rows[1]["tag"]}  # the same place as row 0
    rows[2] = {**rows[2], "topic": BASE + "/+"}
    rows[3] = {**rows[3], "tag": "SPC.Feed"}  # awaiting a tag, not monitored
    rows.append(dict(rows[4]))  # a tag twice
    rows[5] = {**rows[5], "topic": "other/place"}
    errors, warnings = mapping.validate(rows, {"topic": f"{BASE}/SPC", "field": " "}, REG, SUBS)
    fields = {e["field"]: e["message"] for e in errors}
    assert "can't both come from" in fields["rows[1].field"]
    assert "subscriptions" in fields["rows[2].topic"]
    assert "isn't a monitored" in fields["rows[3].tag"]
    assert "appears twice" in fields[f"rows[{len(rows) - 1}].tag"]
    assert "sku.field" in fields
    assert any("other/place isn't under the connection's topic filters" in w for w in warnings)
    assert len(mapping.coverage(rows, REG)["missing"]) == 1  # SPC.Feed replaced a needed tag


def test_topic_map_and_csv_round_trip():
    ns = REG.namespace
    topic_map = {"tags": {f"{ns}.{r['tag']}": {"topic": r["topic"], "field": r["field"]} for r in by_convention()}
                 | {f"{ns}.SPC.Feed": {"topic": f"{BASE}/SPC", "field": "Feed"}},
                 "not_seen": [f"{ns}.SPC.Film_Reel"]}
    rows, ignored, not_seen = mapping.from_topic_map(topic_map, REG)
    assert len(rows) == len(mapping.required(REG)) and ignored == ["SPC.Feed"] and not_seen == []
    sku = {"topic": f"{BASE}/SPC", "field": "SKU_Code"}
    back, back_sku, problems = mapping.from_csv(mapping.to_csv(rows, sku))
    assert problems == [] and back_sku == sku
    assert mapping.digest(back, back_sku) == mapping.digest(rows, sku)
    _, _, bad = mapping.from_csv("topic,tag\nx,y\n")
    assert bad[0]["line"] == 1
