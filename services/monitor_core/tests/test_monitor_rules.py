"""The two rules against the URS and SDD examples (HMI-01, ACT-01)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from centerline_common.register import HmiMatch
from centerline_monitor.rules import Limits, Severity, classify, hmi_matches

LIMITS = Limits(Decimal("2"), Decimal("1"), Decimal("4"), Decimal("2"))  # P02's proposal: −2/+1, −4/+2


@pytest.mark.parametrize("target, hmi, same", [
    (180, 180.9, True), (180.9, 180.2, True), (180, 179.9, False), (0, -0.7, True), (-1, -1.9, True),
    (220, 221, False), (1.3, 1.25, True),
])
def test_hmi_compares_whole_numbers_truncated_toward_zero(target, hmi, same):
    assert hmi_matches(target, hmi) is same


def test_a_parameter_can_compare_to_one_decimal():
    one = HmiMatch("truncate", 1)  # proposed for P09 (O-17)
    assert not hmi_matches(1.3, 1.2, one) and hmi_matches(1.3, 1.39, one)


@pytest.mark.parametrize("actual, expected", [
    (178, Severity.NORMAL), (181, Severity.NORMAL), (180, Severity.NORMAL),  # the Warning edges are Normal
    (177.99, Severity.WARNING), (181.01, Severity.WARNING),
    (176, Severity.WARNING), (182, Severity.WARNING),  # the Critical edges are Warning
    (175.99, Severity.CRITICAL), (182.01, Severity.CRITICAL),
])
def test_each_boundary_belongs_to_the_milder_state(actual, expected):
    assert classify(actual, 180, LIMITS) is expected


def test_limits_follow_the_hmi_setpoint_not_the_target():
    assert classify(185.5, 185, LIMITS) is Severity.NORMAL  # the HMI says 185 even if the target is 180 (A-02)
    assert classify(180.1 + 0.9, 180, LIMITS) is Severity.NORMAL  # 181.0 exactly, not 181.00000000000003
