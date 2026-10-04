"""Correlation and descriptive statistics (ANA-12, ANA-13, SDD §8).

64-bit floats with a two-pass method, so large offsets such as 180 °C
readings don't lose precision. Standard deviation uses n − 1 (A-08). The
strength label uses the unrounded |r| (0.3996 is Weak even when shown as 0.40).
"""

from __future__ import annotations

import math

import numpy as np

# ANA-13: <0.20 very weak/none, 0.20–<0.40 weak, 0.40–<0.70 moderate, 0.70–<0.90 strong, 0.90–1.00 very strong
BANDS = ((0.20, "very weak/none"), (0.40, "weak"), (0.70, "moderate"), (0.90, "strong"))
NOTE = "Correlation shows association between the two values; it does not prove that one causes the other."


def strength(r: float) -> str:
    a = abs(r)
    for limit, label in BANDS:
        if a < limit:
            return label
    return "very strong"


def describe(a: np.ndarray) -> dict:
    n = int(a.size)
    if n == 0:
        return {"n": 0, "min": None, "max": None, "mean": None, "sd": None}
    mean = float(np.mean(a))
    sd = float(math.sqrt(np.sum((a - mean) ** 2) / (n - 1))) if n > 1 else None
    return {"n": n, "min": float(np.min(a)), "max": float(np.max(a)), "mean": mean, "sd": sd}


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def correlate(x: np.ndarray, y: np.ndarray) -> dict:
    """Pearson r and the least-squares line y = slope·x + intercept, or the reason it isn't computable."""
    n = int(x.size)
    base = {"n": n, "computable": False, "reason": None, "r": None, "rSquared": None, "slope": None,
            "intercept": None, "equation": None, "strength": None, "direction": None}
    if n < 3:
        return base | {"reason": f"Fewer than 3 paired buckets ({n})"}
    mx, my = float(np.mean(x)), float(np.mean(y))
    dx, dy = x - mx, y - my
    sxx, syy, sxy = float(np.sum(dx * dx)), float(np.sum(dy * dy)), float(np.sum(dx * dy))
    if sxx == 0.0 or syy == 0.0:
        which = "X" if sxx == 0.0 else "Y"
        return base | {"reason": f"{which} is constant over the paired buckets, so r is undefined"}
    r = max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))
    slope = sxy / sxx
    intercept = my - slope * mx
    sign = "+" if intercept >= 0 else "−"
    return base | {
        "computable": True, "r": r, "rSquared": r * r, "slope": slope, "intercept": intercept,
        "equation": f"y = {_fmt(slope)}·x {sign} {_fmt(abs(intercept))}",
        "strength": strength(r), "direction": "positive" if r > 0 else "negative" if r < 0 else "none",
    }
