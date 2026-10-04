"""The two monitoring rules as pure functions (DD-01: a rules bug is caught without a broker).

HMI mismatch (HMI-01): the target and the HMI setpoint are compared as whole numbers,
truncated toward zero by default, so 180.9 and 180.2 both become 180 and match, and −0.7
becomes 0. A parameter can compare differently (the register's hmi_match, ADR-0007, O-17).

Actual severity (ACT-01, A-02): limits are distances from the raw HMI setpoint, compared
on raw decimals, and each boundary belongs to the milder state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum

from centerline_common.register import HmiMatch


def decimal(value) -> Decimal:
    """A reading as an exact decimal: 180.1 stays 180.1, not 180.0999…"""
    return value if isinstance(value, Decimal) else Decimal(repr(float(value)))


def hmi_matches(target, hmi, match: HmiMatch = HmiMatch()) -> bool:
    return match.key(target) == match.key(hmi)


class Severity(IntEnum):
    NORMAL = 0
    WARNING = 1
    CRITICAL = 2


@dataclass(frozen=True)
class Limits:
    """Distances below and above the HMI setpoint (A-02)."""

    warn_low: Decimal
    warn_high: Decimal
    crit_low: Decimal
    crit_high: Decimal


def classify(actual, hmi_setpoint, limits: Limits) -> Severity:
    a, s = decimal(actual), decimal(hmi_setpoint)
    if s - limits.warn_low <= a <= s + limits.warn_high:
        return Severity.NORMAL
    if s - limits.crit_low <= a <= s + limits.crit_high:
        return Severity.WARNING
    return Severity.CRITICAL
