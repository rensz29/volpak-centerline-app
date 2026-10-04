"""Step series, exclusions, heartbeat gaps, bucketing, shift and production date."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from centerline_common.historian import UNREADABLE_Q, Sample

from centerline_api.analytics.buckets import aggregate, production_date, shift_of
from centerline_api.analytics.series import build_series, heartbeat_gaps, mask

LO = 1_800_000_000  # a multiple of 3600, so buckets align with the range start


def s(offset: float, v, q: int = 192) -> Sample:
    return Sample(datetime.fromtimestamp(LO + offset, timezone.utc), v, q)


def test_value_holds_until_next_sample_and_carry_in_counts():
    series, ex = build_series([s(-100, 10.0), s(30, 20.0)], LO, LO + 120)
    avg = aggregate(series, LO, LO + 120, 60, "AVG")
    assert avg.value.tolist() == [15.0, 20.0]  # 30 s at 10 and 30 s at 20, then 20 held with no new sample
    assert ex.samples == 2


def test_min_max_use_values_in_force():
    series, _ = build_series([s(-100, 10.0), s(30, 20.0), s(70, 5.0), s(80, 20.0)], LO, LO + 120)
    assert aggregate(series, LO, LO + 120, 60, "MIN").value.tolist() == [10.0, 5.0]
    assert aggregate(series, LO, LO + 120, 60, "MAX").value.tolist() == [20.0, 20.0]


def test_bad_sample_makes_value_unknown_until_next_and_coverage_rule():
    samples = [s(-1, 10.0), s(20, 99.0, q=0), s(50, 30.0)]
    series, ex = build_series(samples, LO, LO + 60)
    b = aggregate(series, LO, LO + 60, 60, "AVG", min_coverage=0.5)
    assert ex.bad_quality == 1
    assert b.coverage[0] == pytest.approx(0.5)
    assert b.value[0] == pytest.approx((20 * 10 + 10 * 30) / 30)
    b = aggregate(series, LO, LO + 60, 60, "AVG", min_coverage=0.6)
    assert np.isnan(b.value[0])  # missing, never zero (ANA-08)


def test_each_exclusion_reason_is_counted():
    samples = [s(0, None), s(1, "abc"), s(2, float("nan")), s(3, float("inf")), s(4, 5.0, q=64), s(5, 500.0),
               s(6, 50.0), s(7, True)]
    _, ex = build_series(samples, LO, LO + 10, valid=(0.0, 100.0))
    assert (ex.null, ex.non_numeric, ex.nan, ex.infinite, ex.bad_quality, ex.out_of_range) == (1, 2, 1, 1, 1, 1)
    assert ex.samples == 8


def test_unreadable_span_is_measured_not_counted_as_a_sample():
    series, ex = build_series([s(-5, 1.0), s(10, None, UNREADABLE_Q), s(40, 2.0)], LO, LO + 60)
    assert ex.unreadable_s == 30
    assert ex.samples == 2
    assert np.isnan(series.vals[1])


def test_heartbeat_gap_starts_after_the_threshold():
    arrivals = [LO - 1, LO + 10, LO + 400, LO + 410]
    assert heartbeat_gaps(arrivals, LO, LO + 1000, 120) == [(LO + 130, LO + 400), (LO + 530, LO + 1000)]


def test_mask_turns_gap_time_unknown_and_counts_it():
    series, ex = build_series([s(-1, 7.0)], LO, LO + 100)
    masked = mask(series, [(LO + 20, LO + 50)], ex)
    assert ex.gap_s == 30
    avg = aggregate(masked, LO, LO + 100, 100, "AVG")
    assert avg.value[0] == 7.0 and avg.coverage[0] == pytest.approx(0.7)


def manila(y, m, d, hh, mm=0) -> float:
    return (datetime(y, m, d, hh, mm) - timedelta(hours=8)).replace(tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("when, shift, date", [
    ((2026, 9, 28, 5, 59), "C", "2026-09-27"),
    ((2026, 9, 28, 6, 0), "A", "2026-09-28"),
    ((2026, 9, 28, 13, 59), "A", "2026-09-28"),
    ((2026, 9, 28, 14, 0), "B", "2026-09-28"),
    ((2026, 9, 28, 22, 0), "C", "2026-09-28"),
    ((2026, 9, 29, 0, 30), "C", "2026-09-28"),
])
def test_shift_and_production_date_follow_manila_shift_start(when, shift, date):
    t = np.array([manila(*when)])
    assert shift_of(t)[0] == shift
    assert production_date(t)[0] == date  # the 22:00 shift belongs to its start date (A-07)


def test_long_range_is_fast_enough_to_vectorise():
    rng = np.random.default_rng(1)
    t = np.sort(rng.uniform(0, 30 * 86400, 400_000))
    samples = [s(x, float(v)) for x, v in zip(t, 180 + rng.normal(0, 1, t.size))]
    series, _ = build_series(samples, LO, LO + 30 * 86400)
    b = aggregate(series, LO, LO + 30 * 86400, 10, "MAX")
    assert b.value.size == 259_200 and np.isfinite(b.value[1:]).all()
