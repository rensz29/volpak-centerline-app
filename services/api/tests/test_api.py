"""The HTTP API against the mock Timebase (one synthetic day from 2026-09-02 00:00 Manila)."""

from __future__ import annotations

import json

QUERY = {"from": "2026-09-01T18:00:00Z", "to": "2026-09-02T06:00:00Z", "x": "P02.V1.actual", "y": "P02.V2.actual"}


def codes(body: dict) -> set[str]:
    return {w["code"] for w in body["warnings"]}


def test_options_list_actuals_and_setpoints_of_every_zone(make_client):
    body = make_client().get("/api/v1/analytics/options").json()
    by_channel = {v["channel"]: v for v in body["variables"]}
    # 14 zones × (actual + setpoint) + P08 Machine Speed, which has no setpoint yet
    assert len(by_channel) == 29
    assert {"P02.V1.actual", "P02.V1.setpoint", "P08.MAIN.actual"} <= set(by_channel)
    assert "P08.MAIN.setpoint" not in by_channel
    assert by_channel["P02.V1.setpoint"]["label"] == "Vertical 1 · Setpoint"
    assert by_channel["P09.MAIN.setpoint"]["caution"] and by_channel["P09.MAIN.actual"]["caution"]
    assert body["defaults"]["x"].endswith(".actual") and body["defaults"]["x"] != body["defaults"]["y"]
    assert "sku" not in body  # Centerline has no SKU (ADR-0027)


def test_setpoint_can_be_analysed_against_its_actual(make_client):
    r = make_client().post("/api/v1/analytics/query", json={**QUERY, "x": "P02.V1.setpoint", "y": "P02.V1.actual"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["x"]["kind"] == "setpoint" and body["y"]["kind"] == "actual"
    assert body["buckets"]["paired"] > 700 and body["statistics"]["correlation"]["computable"]
    # People see zone names, not parameter IDs (ADR-0009)
    assert not any("P02" in w["message"] for w in body["warnings"])


def test_bare_zone_channel_still_means_the_actual(make_client):
    body = make_client().post("/api/v1/analytics/query", json={**QUERY, "x": "P02.V1"}).json()
    assert body["query"]["x"] == "P02.V1.actual"


def test_zone_without_setpoint_has_no_setpoint_variable(make_client):
    r = make_client().post("/api/v1/analytics/query", json={**QUERY, "x": "P08.MAIN.setpoint"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "x"


def test_query_returns_pairs_statistics_and_warnings(make_client, tmp_path):
    r = make_client().post("/api/v1/analytics/query", json=QUERY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["buckets"]["total"] == 720 and body["buckets"]["paired"] > 700
    assert len(body["pairs"]["t"]) == body["buckets"]["paired"]
    assert body["statistics"]["correlation"]["computable"]
    assert {"NO_RANGES", "HISTORIAN_CLOCK"} <= codes(body) and "NO_SKU_TAG" not in codes(body)
    assert "does not prove" in body["note"]
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert audit[-1]["query"]["x"] == "P02.V1.actual" and "pairs" in audit[-1] and "t" not in audit[-1]


def test_invalid_queries_are_problem_documents(make_client):
    c = make_client()
    cases = [({**QUERY, "y": "P02.V1.actual"}, "y"), ({**QUERY, "to": "2099-01-01T00:00:00Z"}, "to"),
             ({**QUERY, "from": "2026-07-01T00:00:00Z"}, "from"), ({**QUERY, "x": "P01.MAIN.actual"}, "x"),
             ({**QUERY, "from": "2026-09-01T18:00:00"}, "from")]
    for body, field in cases:
        r = c.post("/api/v1/analytics/query", json=body)
        assert r.status_code == 422, (body, r.text)
        assert r.headers["content-type"].startswith("application/problem+json")
        assert field in [e["field"] for e in r.json()["errors"]], r.json()


def test_size_guard_recommends_the_smallest_larger_bucket(make_client):
    body = make_client(pair_limit=500).post("/api/v1/analytics/query", json=QUERY).json()
    assert body["sizeGuard"] == {"limit": 500, "exceeded": True, "recommendedBucket": "PT5M"}
    assert body["pairs"] is None and "TOO_MANY_PAIRS" in codes(body)


def test_grouping_by_shift_and_production_date(make_client):
    c = make_client()
    body = c.post("/api/v1/analytics/query", json={**QUERY, "groupBy": "SHIFT", "groupStats": True}).json()
    keys = [g["key"] for g in body["groups"]["items"]]
    assert keys == ["A", "C"] and all("correlation" in g for g in body["groups"]["items"])
    assert set(body["pairs"]["g"]) == {"A", "C"}
    body = c.post("/api/v1/analytics/query", json={**QUERY, "groupBy": "PRODUCTION_DATE"}).json()
    assert [g["key"] for g in body["groups"]["items"]] == ["2026-09-01", "2026-09-02"]


def test_shift_filter_keeps_only_that_shift(make_client):
    # 02:00–14:00 Manila: 4 h of shift C (240 one-minute buckets), then 8 h of shift A (480).
    body = make_client().post("/api/v1/analytics/query", json={**QUERY, "shift": "A"}).json()
    assert 400 < body["buckets"]["paired"] <= 480
    assert 200 < body["buckets"]["outsideShift"] <= 240


def test_unreadable_timebase_span_counts_as_missing(make_client, mock_timebase):
    mod, _ = mock_timebase
    original = mod.BAD_TAG
    mod.BAD_TAG = f"{mod.NS}.SPC.Actual_Temp_Vertical_1"
    try:
        body = make_client().post("/api/v1/analytics/query", json=QUERY).json()
    finally:
        mod.BAD_TAG = original
    assert "UNREADABLE" in codes(body) and body["exclusions"]["x"]["unreadableSeconds"] > 0


def test_heartbeat_gaps_remove_silent_periods(make_client):
    loose = make_client().post("/api/v1/analytics/query", json=QUERY).json()
    strict = make_client(heartbeat_gap_s=4).post("/api/v1/analytics/query", json=QUERY).json()
    assert "DATA_GAP" in codes(strict) and strict["exclusions"]["x"]["gapSeconds"] > 0
    assert strict["buckets"]["paired"] <= loose["buckets"]["paired"]
