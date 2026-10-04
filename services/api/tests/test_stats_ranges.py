"""Statistics against an independent implementation (AT-ANA-05 spirit), strength bands, ranges CSV."""

from __future__ import annotations

import statistics

import numpy as np
import pytest
from centerline_common import register

from centerline_api.analytics.ranges import parse_ranges
from centerline_api.analytics.stats import correlate, describe, strength

from .conftest import REGISTER

REG = register.load(REGISTER)


def test_pearson_and_least_squares_match_python_statistics():
    rng = np.random.default_rng(7)
    x = 180 + rng.normal(0, 0.8, 500)  # large offset, small spread: the two-pass case
    y = 0.6 * x + rng.normal(0, 0.5, 500) - 40
    got = correlate(x, y)
    fit = statistics.linear_regression(x.tolist(), y.tolist())
    assert got["r"] == pytest.approx(statistics.correlation(x.tolist(), y.tolist()), rel=1e-12)
    assert got["slope"] == pytest.approx(fit.slope, rel=1e-10)
    assert got["intercept"] == pytest.approx(fit.intercept, rel=1e-10)
    assert got["rSquared"] == pytest.approx(got["r"] ** 2)


def test_descriptive_statistics_use_sample_sd():
    d = describe(np.array([1.0, 2.0, 3.0, 4.0]))
    assert d == {"n": 4, "min": 1.0, "max": 4.0, "mean": 2.5, "sd": pytest.approx(statistics.stdev([1, 2, 3, 4]))}


@pytest.mark.parametrize("r, label", [(0.1999, "very weak/none"), (0.20, "weak"), (0.3996, "weak"),
                                      (0.40, "moderate"), (0.6999, "moderate"), (0.70, "strong"),
                                      (0.90, "very strong"), (-0.95, "very strong"), (-0.25, "weak")])
def test_strength_bands_follow_ana_13_on_unrounded_r(r, label):
    assert strength(r) == label


def test_not_computable_cases_give_a_reason():
    assert correlate(np.array([1.0, 2.0]), np.array([1.0, 2.0]))["reason"].startswith("Fewer than 3")
    got = correlate(np.array([5.0, 5.0, 5.0]), np.array([1.0, 2.0, 3.0]))
    assert not got["computable"] and "X is constant" in got["reason"]


def good_csv(**override) -> bytes:
    rows = {p["id"]: (p.get("unit") or "", 0, 1000) for p in REG.parameters}
    rows.update(override)
    lines = ["parameter_id,unit,valid_min,valid_max"] + [f"{k},{u},{a},{b}" for k, (u, a, b) in rows.items()]
    return "\n".join(lines).encode()


def test_complete_ranges_file_is_accepted_with_hash():
    check = parse_ranges(good_csv(), REG, "ranges.csv")
    assert check.problems == [] and len(check.ranges.ranges) == 11 and len(check.ranges.sha256) == 64


@pytest.mark.parametrize("override, fragment", [
    ({"P02": ("bar", 0, 400)}, "unit"),
    ({"P03": ("°C", 300, 100)}, "valid_min < valid_max"),
])
def test_bad_rows_reject_the_whole_file(override, fragment):
    check = parse_ranges(good_csv(**override), REG, "ranges.csv")
    assert check.ranges is None and any(fragment in p for p in check.problems)


def test_missing_parameter_rejects_the_file():
    text = b"\n".join(line for line in good_csv().split(b"\n") if not line.startswith(b"P11"))
    check = parse_ranges(text, REG, "ranges.csv")
    assert check.ranges is None and "P11" in " ".join(check.problems)
