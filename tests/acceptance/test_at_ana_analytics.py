"""AT-ANA-01…10: Analytics & Correlation against an independently calculated dataset (gate G4).

URS v1.1 §11 (ANA-01…21) as built in ADR-0008, ADR-0009 and ADR-0029. The api reads a stand-in Timebase serving
tests/fixtures/analytics/dataset.json. Every number it returns is compared with expected.json, which
tests/fixtures/analytics/independent.py calculated from the same data with Python's standard library alone (exact
fractions and 50-digit decimals), not with the api's code. A test checks that expected.json is still what that
calculation gives.
"""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest
from centerline_api.analytics import service
from centerline_api.main import create_app

from .conftest import add_account, api, new_client, sign_in
from .timebase_stub import FIXTURES, TimebaseStub

REPO = Path(__file__).resolve().parents[2]
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
QUERIES, RESULTS = EXPECTED["queries"], EXPECTED["results"]
QUERY = "/api/v1/analytics/query"
RANGES = "/api/v1/config/analytics-ranges"


@pytest.fixture(scope="module")
def timebase():
    stub = TimebaseStub()
    yield stub
    stub.close()


@pytest.fixture
def analyst(timebase, tmp_path, database):
    """A Manager and Administrator on an api that reads the stand-in Timebase."""
    service._tag_cache.clear()
    app = create_app(api.make_settings(timebase.url, tmp_path, database))
    c = new_client(app)
    sign_in(c, add_account(app, database))
    return c


def use_ranges(c, name: str = "ranges.csv", data: bytes | None = None, reason: str = "Process engineering's ranges"):
    data = data if data is not None else (FIXTURES / "ranges.csv").read_bytes()
    return c.post(f"{RANGES}/versions", json={"expectedLatest": c.get(RANGES).json()["latest"], "source": name,
                                              "contentBase64": base64.b64encode(data).decode(), "reason": reason,
                                              "activate": "now"})


def body_of(name: str, **override) -> dict:
    q = QUERIES[name]
    lo, hi = EXPECTED["windows"][q["window"]]
    return {"from": lo, "to": hi, "x": EXPECTED["variables"]["x"], "y": EXPECTED["variables"]["y"], "bucket": q["bucket"],
            "aggregation": q["aggregation"], "shift": q["shift"], "groupBy": q["groupBy"],
            "groupStats": q.get("groupStats", False), **override}


def query(c, name: str, **override) -> dict:
    r = c.post(QUERY, json=body_of(name, **override))
    assert r.status_code == 200, r.text
    return r.json()


def same(got, want, path: str = "") -> None:
    """`got` holds everything `want` does: numbers within 1e-9 (the api's floats against 50 digits), the rest exactly."""
    if isinstance(want, dict):
        assert isinstance(got, dict), path
        for k, v in want.items():
            same(got.get(k), v, f"{path}.{k}")
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want), f"{path}: {len(got or [])} items, not {len(want)}"
        for i, (g, w) in enumerate(zip(got, want)):
            same(g, w, f"{path}[{i}]")
    elif isinstance(want, float):
        assert got == pytest.approx(want, rel=1e-9, abs=1e-9), path
    else:
        assert got == want, f"{path}: {got!r}, not {want!r}"


def codes(result: dict) -> set[str]:
    return {w["code"] for w in result["warnings"]}


def test_the_expected_results_are_still_what_the_independent_calculation_gives():
    spec = importlib.util.spec_from_file_location("acceptance_independent", FIXTURES / "independent.py")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, str(FIXTURES))
    try:
        spec.loader.exec_module(module)
        data = json.loads((FIXTURES / "dataset.json").read_text(encoding="utf-8"))
        name = "dense-PT1M-AVG"
        assert json.loads(json.dumps(module.run(data, module.QUERIES[name], module.ranges()))) == RESULTS[name]
    finally:
        sys.path.remove(str(FIXTURES))


@pytest.mark.urs("AT-ANA-01", "ANA-01", "ANA-04", "ANA-05")
def test_the_variables_are_the_zones_values_x_and_y_differ_and_the_shift_is_optional(analyst):
    options = analyst.get("/api/v1/analytics/options").json()
    channels = {v["channel"] for v in options["variables"]}
    assert {"P03.FRONT.actual", "P03.FRONT.setpoint", "P09.MAIN.actual", "P08.MAIN.actual"} <= channels  # ADR-0009
    assert all(c.endswith((".actual", ".setpoint")) for c in channels) and "P08.MAIN.setpoint" not in channels
    assert [s["code"] for s in options["shifts"]] == ["ALL", "A", "B", "C"] and options["defaults"]["shift"] == "ALL"
    for bad, field in (({"y": EXPECTED["variables"]["x"]}, "y"), ({"x": "P01.MAIN.actual"}, "x"), ({"x": "P02.V1.target"}, "x")):
        r = analyst.post(QUERY, json=body_of("dense-PT1M-AVG", **bad))
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == field
    assert analyst.post(QUERY, json=body_of("dense-PT1M-AVG", shift="D")).status_code == 422
    assert analyst.post(QUERY, json=body_of("dense-PT1M-AVG", sku="X")).status_code == 422  # no SKU (ADR-0027)
    without_shift = {k: v for k, v in body_of("dense-PT1M-AVG").items() if k != "shift"}
    assert analyst.post(QUERY, json=without_shift).json()["query"]["shift"] == "ALL"


@pytest.mark.urs("AT-ANA-02", "ANA-06", "ANA-07")
def test_six_buckets_and_three_aggregations_with_1_minute_average_by_default(analyst):
    use_ranges(analyst)
    options = analyst.get("/api/v1/analytics/options").json()
    assert [(b["code"], b["seconds"]) for b in options["buckets"]] == [
        ("PT10S", 10), ("PT30S", 30), ("PT1M", 60), ("PT5M", 300), ("PT15M", 900), ("PT1H", 3600)]
    assert [a["code"] for a in options["aggregations"]] == ["AVG", "MIN", "MAX"]
    assert (options["defaults"]["bucket"], options["defaults"]["aggregation"]) == ("PT1M", "AVG")
    plain = {k: v for k, v in body_of("dense-PT1M-AVG").items() if k not in ("bucket", "aggregation")}
    assert analyst.post(QUERY, json=plain).json()["query"] | {} == query(analyst, "dense-PT1M-AVG")["query"]
    for b in ("PT10S", "PT30S", "PT1M", "PT5M", "PT15M", "PT1H"):
        for a in ("AVG", "MIN", "MAX"):
            got, want = query(analyst, f"dense-{b}-{a}"), RESULTS[f"dense-{b}-{a}"]
            same(got["buckets"], want["buckets"], f"{b} {a} buckets")
            same(got["statistics"], want["statistics"], f"{b} {a} statistics")


@pytest.mark.urs("AT-ANA-03", "ANA-08", "ANA-09")
def test_each_excluded_sample_is_counted_by_reason_and_nothing_missing_becomes_zero(analyst):
    use_ranges(analyst)
    got, want = query(analyst, "dense-PT1M-AVG"), RESULTS["dense-PT1M-AVG"]
    same(got["exclusions"], want["exclusions"])
    x, y = got["exclusions"]["x"], got["exclusions"]["y"]
    assert (x["badQuality"], x["null"], x["nonNumeric"], x["outOfRange"], x["gapSeconds"]) == (1, 1, 1, 1, 185.0)
    assert (y["nan"], y["infinite"], y["outOfRange"]) == (1, 1, 1)
    same(got["buckets"], want["buckets"])
    same(got["pairs"], want["pairs"])  # the 10 buckets not known enough are absent, not zero
    assert 0.0 not in got["pairs"]["x"] + got["pairs"]["y"] and got["buckets"]["paired"] < got["buckets"]["total"]


@pytest.mark.urs("AT-ANA-04", "ANA-10", "ANA-11")
def test_the_ranges_file_is_imported_whole_versioned_and_rolled_back(analyst):
    reference = (FIXTURES / "ranges.csv").read_bytes()
    before = query(analyst, "dense-PT1M-AVG")
    assert "NO_RANGES" in codes(before) and before["exclusions"]["x"]["outOfRange"] == 0
    incomplete = b"\n".join(line for line in reference.split(b"\n") if not line.startswith(b"P11"))
    assert use_ranges(analyst, data=incomplete).status_code == 422  # the whole file is rejected
    assert analyst.get(RANGES).json()["latest"] is None
    assert use_ranges(analyst).status_code == 201  # v1: the reference ranges
    wide = reference.replace(b"P03,\xc2\xb0C,0,300", b"P03,\xc2\xb0C,-100000,100000").replace(b"P09,bar,0,5", b"P09,bar,-100000,100000")
    assert use_ranges(analyst, "wide.csv", wide, "Wider, for a test").status_code == 201  # v2
    assert query(analyst, "dense-PT1M-AVG")["exclusions"]["x"]["outOfRange"] == 0
    r = analyst.post(f"{RANGES}/versions/1/activate", json={"expectedActive": 2, "reason": "Back to the approved ranges"})
    assert r.json()["active"]["number"] == 1
    after = query(analyst, "dense-PT1M-AVG")
    assert after["ranges"]["version"] == 1 and after["exclusions"]["x"]["outOfRange"] == 1
    v1 = analyst.get(f"{RANGES}/versions/1").json()
    assert v1["intact"] and analyst.get(f"{RANGES}/versions/1/original.csv").content == reference
    actions = [e["action"] for e in analyst.get("/api/v1/config/register").json()["audit"]]
    assert actions[:5] == ["analytics_ranges.activate", "analytics_ranges.activate", "analytics_ranges.version",
                           "analytics_ranges.activate", "analytics_ranges.version"]


@pytest.mark.urs("AT-ANA-05", "ANA-12", "ANA-13")
def test_r_the_least_squares_line_r_squared_and_the_statistics_match_the_independent_calculation(analyst):
    use_ranges(analyst)
    for name in ("dense-PT1M-AVG", "dense-PT15M-MIN", "dense-PT1M-AVG-shift-A", "days-PT15M-AVG-by-date"):
        got, want = query(analyst, name), RESULTS[name]
        same(got["statistics"], want["statistics"], name)
        corr = got["statistics"]["correlation"]
        assert corr["equation"].startswith("y = ") and corr["n"] == got["buckets"]["paired"]
    assert query(analyst, "dense-PT15M-MIN")["statistics"]["correlation"]["direction"] == "negative"
    hourly = query(analyst, "dense-PT1H-AVG")
    assert not hourly["statistics"]["correlation"]["computable"] and "Fewer than 3" in hourly["statistics"]["correlation"]["reason"]
    assert "NOT_COMPUTABLE" in codes(hourly)


@pytest.mark.urs("AT-ANA-06", "ANA-15")
def test_scatter_and_trend_draw_one_paired_result_with_units_utc_times_and_gaps(analyst):
    use_ranges(analyst)
    got = query(analyst, "dense-PT1M-AVG")
    same(got["pairs"], RESULTS["dense-PT1M-AVG"]["pairs"])
    t = got["pairs"]["t"]
    assert t == sorted(t) and all(ms % 60_000 == 0 for ms in t)  # bucket starts, UTC milliseconds
    assert any(b - a > 60_000 for a, b in zip(t, t[1:]))  # missing buckets leave a gap for the Trend tab to show
    assert (got["x"]["unit"], got["y"]["unit"]) == ("°C", "bar")  # different units: two Y axes
    charts = (REPO / "client" / "src" / "components" / "correlation" / "chartOptions.ts").read_text(encoding="utf-8")
    assert charts.count("const pairs = result.pairs") == 2  # Scatter and Trend from the same pairs
    assert "connectNulls: false" in charts and "yAxisIndex: axis" in charts and "dataZoom" in charts


@pytest.mark.urs("AT-ANA-07", "ANA-16", "ANA-17", "ANA-20")
def test_grouping_by_shift_or_production_date_with_sample_size_warnings_and_ten_groups(analyst):
    use_ranges(analyst)
    by_shift = query(analyst, "dense-PT1M-AVG-by-shift")
    same(by_shift["groups"], RESULTS["dense-PT1M-AVG-by-shift"]["groups"])
    assert [g["key"] for g in by_shift["groups"]["items"]] == ["A", "B"]  # 13:00–15:00 Manila, across 14:00
    by_date = query(analyst, "days-PT15M-AVG-by-date")
    same(by_date["groups"], RESULTS["days-PT15M-AVG-by-date"]["groups"])
    items = by_date["groups"]["items"]
    assert len(items) == 10 and by_date["groups"]["hidden"] == 2 and "GROUPS_HIDDEN" in codes(by_date)
    warnings = {g["key"]: g["warning"] for g in items}
    assert (warnings["2026-09-15"], warnings["2026-09-17"], warnings["2026-09-21"]) == ("INSUFFICIENT_DATA", "LOW_SAMPLE_SIZE", None)
    assert "correlation" not in next(g for g in items if g["key"] == "2026-09-15")  # fewer than 3 pairs
    no_stats = query(analyst, "days-PT15M-AVG-by-date", groupStats=False)
    assert all("correlation" not in g for g in no_stats["groups"]["items"])
    assert query(analyst, "dense-PT1M-AVG")["groups"] is None  # no grouping by default


@pytest.mark.urs("AT-ANA-08", "ANA-18", "ANA-19")
def test_a_30_day_maximum_and_over_10000_pairs_no_chart_but_the_smallest_bucket_that_fits(analyst):
    use_ranges(analyst)
    options = analyst.get("/api/v1/analytics/options").json()
    assert (options["limits"]["maxRangeDays"], options["limits"]["pairLimit"], options["defaults"]["rangeHours"]) == (30, 10_000, 24)
    lo = EXPECTED["windows"]["days"][1]
    for bad in ({"from": "2026-08-20T22:00:00Z", "to": lo}, {"to": "2099-01-01T00:00:00Z"}):
        assert analyst.post(QUERY, json=body_of("days-PT10S-AVG", **bad)).status_code == 422
    got = query(analyst, "days-PT10S-AVG")
    same(got["buckets"], RESULTS["days-PT10S-AVG"]["buckets"])
    assert got["sizeGuard"] == {"limit": 10_000, **RESULTS["days-PT10S-AVG"]["sizeGuard"]}
    assert got["sizeGuard"]["recommendedBucket"] == "PT5M" and got["pairs"] is None and got["statistics"] is None
    assert any(w["code"] == "TOO_MANY_PAIRS" and "5 minutes" in w["message"] for w in got["warnings"])


@pytest.mark.urs("AT-ANA-09", "ANA-02", "ANA-03", "ANA-21")
def test_only_the_api_reads_timebase_read_only_and_nothing_keeps_the_series(analyst, timebase, owner):
    use_ranges(analyst)

    def rows() -> dict[str, int]:
        with owner.connect() as conn:
            tables = [r["table_name"] for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")]
            return {t: conn.execute(f'SELECT count(*) AS n FROM "{t}"').fetchone()["n"] for t in tables}

    before, asked = rows(), len(timebase.requests)
    query(analyst, "days-PT15M-AVG-by-date")
    assert rows() == before  # no table took the series or the pairs (ANA-03, ANA-21)
    assert len(timebase.requests) > asked and {m for m, _ in timebase.requests} == {"GET"}
    logged = json.loads(analyst.app.state.settings.audit_log.read_text(encoding="utf-8").splitlines()[-1])
    assert "pairs" in logged and isinstance(logged["pairs"], int) and "x" not in logged  # the query's description only
    src = REPO / "client" / "src"
    fetchers = [p.relative_to(src).as_posix() for p in src.rglob("*.ts*") if "fetch(" in p.read_text(encoding="utf-8")]
    assert fetchers == ["services/http.ts"]  # the browser calls the api only (ANA-02)
    assert not [p for p in (src / "services").glob("*.ts") if "://" in p.read_text(encoding="utf-8")]


@pytest.mark.urs("AT-ANA-10", "ANA-14")
def test_every_result_says_correlation_is_association_not_causation(analyst):
    use_ranges(analyst)
    note = analyst.get("/api/v1/analytics/options").json()["note"]
    assert "association" in note and "does not prove" in note
    for name in ("dense-PT1M-AVG", "dense-PT1H-AVG", "days-PT10S-AVG"):
        assert query(analyst, name)["note"] == note  # also with no statistics, or no chart
    page = "".join(p.read_text(encoding="utf-8") for p in (REPO / "client" / "src" / "components" / "correlation").glob("*.tsx"))
    assert "result.note" in page or ".note}" in page  # the page shows it with every result
