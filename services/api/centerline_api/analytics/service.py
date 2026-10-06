"""Analytics query pipeline (SDD §8): validate → fetch → clean → bucket → pair → guard size → compute.

Each analysis is computed on request from Timebase and returned once; only
query metadata is kept, in the audit log (ANA-03, ANA-21, DD-03).
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone

import numpy as np
from centerline_common.historian import Gap, TagNotFound, TimebaseClient, TimebaseError
from centerline_common.register import AnalyticsVariable, Register
from centerline_common import isotime

from ..problems import Problem
from ..settings import Settings
from . import stats
from .buckets import aggregate, production_date, shift_of
from .models import BUCKET_LABELS, BUCKETS, AnalyticsQuery
from .ranges import RangeCheck
from .series import build_series, heartbeat_gaps, mask

FUTURE_TOLERANCE_S = 60
TAG_CACHE_S = 600
SHIFT_LABELS = {"ALL": "All shifts", "A": "Shift A · 06:00–14:00", "B": "Shift B · 14:00–22:00",
                "C": "Shift C · 22:00–06:00"}

_tag_cache: dict[str, tuple[float, set[str]]] = {}


def _known_tags(client: TimebaseClient, register: Register) -> set[str]:
    key = f"{client.base}|{client.dataset}|{register.namespace}"
    hit = _tag_cache.get(key)
    if hit and time.time() - hit[0] < TAG_CACHE_S:
        return hit[1]
    names = client.tag_names(contains=register.namespace)
    _tag_cache[key] = (time.time(), names)
    return names


def _caution(register: Register, v: AnalyticsVariable) -> str | None:
    p = next((p for p in register.parameters if p["id"] == v.parameter_id), {})
    return p.get("tag_review")


def _describe_variable(register: Register, v: AnalyticsVariable) -> dict:
    return {"channel": v.channel, "zoneChannel": v.zone_channel, "kind": v.kind, "label": v.label,
            "parameterId": v.parameter_id, "parameterName": v.parameter_name,
            "zoneId": v.zone_id, "zoneName": v.zone_name, "unit": v.unit, "area": v.area,
            "caution": _caution(register, v)}


def _duration(seconds: float) -> str:
    s = abs(seconds)
    if s < 120:
        return f"{s:.0f} s"
    if s < 7200:
        return f"{s // 60:.0f} min {s % 60:.0f} s"
    return f"{s / 3600:.1f} h"


def options(settings: Settings, register: Register, ranges: RangeCheck) -> dict:
    a = settings.analytics
    rc = ranges
    variables = [_describe_variable(register, v) for v in register.analytics]
    actuals = [v for v in register.analytics if v.kind == "actual"]
    first = actuals[0] if actuals else None
    second = next((v for v in actuals if first and v.parameter_id != first.parameter_id), None)
    return {
        "variables": variables,
        "buckets": [{"code": c, "seconds": s, "label": BUCKET_LABELS[c]} for c, s in BUCKETS.items()],
        "aggregations": [{"code": "AVG", "label": "Average"}, {"code": "MIN", "label": "Minimum"},
                         {"code": "MAX", "label": "Maximum"}],
        "shifts": [{"code": c, "label": label} for c, label in SHIFT_LABELS.items()],
        "groupings": [{"code": "NONE", "label": "None"}, {"code": "SHIFT", "label": "Shift"},
                      {"code": "PRODUCTION_DATE", "label": "Production date"}],
        "defaults": {"x": first.channel if first else None, "y": second.channel if second else None,
                     "bucket": "PT1M", "aggregation": "AVG", "shift": "ALL", "groupBy": "NONE", "rangeHours": 24},
        "limits": {"maxRangeDays": a.max_range_days, "pairLimit": a.pair_limit, "visibleGroups": a.visible_groups},
        "ranges": {"loaded": rc.ranges is not None, "version": rc.ranges.version if rc.ranges else None,
                   "source": rc.ranges.source if rc.ranges else None, "sha256": rc.ranges.sha256 if rc.ranges else None,
                   "problems": rc.problems},
        "timezone": "Asia/Manila",
        "note": stats.NOTE,
        "registerVersion": register.version,
    }


def _validate(q: AnalyticsQuery, settings: Settings, register: Register, now: float):
    errors = []
    x, y = register.variable(q.x), register.variable(q.y)
    for field, name, v in (("x", q.x, x), ("y", q.y, y)):
        if v is None:
            errors.append({"field": field, "message": f"{name!r} isn't an Analytics variable (ANA-04, ADR-0009)"})
    if x and y and x.channel == y.channel:
        errors.append({"field": "y", "message": "X and Y must be different variables (ANA-04)"})
    lo, hi = q.from_.timestamp(), q.to.timestamp()
    if hi <= lo:
        errors.append({"field": "to", "message": "'to' must be after 'from'"})
    if hi > now + FUTURE_TOLERANCE_S:
        errors.append({"field": "to", "message": "The range ends in the future (ANA-18)"})
    max_s = settings.analytics.max_range_days * 86400
    if hi - lo > max_s:
        errors.append({"field": "from", "message": f"The range is longer than the {settings.analytics.max_range_days}-day maximum (ANA-18)"})
    if errors:
        raise Problem(422, "invalid-query", "The analytics query is invalid",
                      "; ".join(e["message"] for e in errors), errors=errors)
    return x, y, lo, hi


def run(q: AnalyticsQuery, settings: Settings, register: Register, ranges: RangeCheck, client_host: str | None = None,
        user: str | None = None, now: float | None = None) -> dict:
    started = time.monotonic()
    now = time.time() if now is None else now
    a = settings.analytics
    x, y, lo, hi = _validate(q, settings, register, now)

    # -- fetch (ANA-02: the browser never talks to Timebase) -----------------------
    client = TimebaseClient(settings.timebase)
    warnings: list[dict] = []
    heartbeats: dict[str, str] = {}
    gaps: list[Gap] = []
    try:
        names = _known_tags(client, register)
        for v in (x, y):
            if v.tag not in names:
                raise Problem(502, "historian-tag-missing", "A tag is missing in Timebase",
                              f"{v.label} ({v.parameter_name}) has no tag in Timebase")
        if a.use_heartbeat:
            for area in sorted({x.area, y.area}):
                tag = register.heartbeat_tag(area)
                if tag in names:
                    heartbeats[area] = tag
                else:
                    warnings.append({"code": "NO_HEARTBEAT", "message": f"Data gaps in {area} can't be detected: it has no _timestamp tag."})
        start, end = math.floor(lo), math.ceil(hi)
        data = client.read_range(list(dict.fromkeys([x.tag, y.tag])), start, end, a.fetch_window_s,
                                 a.min_window_s, gaps, workers=a.fetch_workers)
        arrivals = {area: client.read_times(tag, start, end, a.fetch_window_s, a.min_window_s, gaps,
                                            workers=a.fetch_workers) for area, tag in heartbeats.items()}
    except TagNotFound as e:
        raise Problem(502, "historian-tag-missing", "A tag is missing in Timebase", str(e)) from None
    except TimebaseError as e:
        raise Problem(502, "historian-unavailable", "Timebase isn't answering", str(e)) from None
    finally:
        client.close()
    fetch_ms = (time.monotonic() - started) * 1000
    clock_offset = (client.last_server_date - time.time()) if client.last_server_date else None

    # -- clean and mask (ANA-09, ANA-10) -----------------------------------------------
    rc = ranges
    valid = rc.ranges.ranges if rc.ranges else {}
    sx, ex = build_series(data[x.tag], lo, hi, good_min=a.good_quality_min, valid=valid.get(x.parameter_id))
    sy, ey = build_series(data[y.tag], lo, hi, good_min=a.good_quality_min, valid=valid.get(y.parameter_id))
    area_gaps = {area: heartbeat_gaps(times, lo, hi, a.heartbeat_gap_s) for area, times in arrivals.items()}
    sx = mask(sx, area_gaps.get(x.area, []), ex)
    sy = mask(sy, area_gaps.get(y.area, []), ey)

    # -- bucket and pair (ANA-06…08, ANA-05 shift filter) ------------------------------
    def pair(width: int):
        bx = aggregate(sx, lo, hi, width, q.aggregation, a.min_coverage)
        by = aggregate(sy, lo, hi, width, q.aggregation, a.min_coverage)
        vx, vy = ~np.isnan(bx.value), ~np.isnan(by.value)
        shifts = shift_of(bx.start)
        in_shift = np.ones(vx.shape, bool) if q.shift == "ALL" else shifts == q.shift
        return bx, by, vx, vy, in_shift, shifts, vx & vy & in_shift

    width = BUCKETS[q.bucket]
    bx, by, vx, vy, in_shift, shifts, paired = pair(width)
    n_pairs = int(paired.sum())
    buckets = {"total": int(bx.start.size), "xValid": int(vx.sum()), "yValid": int(vy.sum()),
               "bothValid": int((vx & vy).sum()), "outsideShift": int((vx & vy & ~in_shift).sum()), "paired": n_pairs}

    # -- warnings -------------------------------------------------------------------------
    if rc.problems:
        warnings.append({"code": "RANGES_REJECTED", "message": "The Analytics-valid ranges in effect aren't applied, so out-of-range samples aren't excluded: " + "; ".join(rc.problems)})
    elif rc.ranges is None:
        warnings.append({"code": "NO_RANGES", "message": "No Analytics-valid ranges are in effect, so out-of-range samples aren't excluded (ANA-10). An Administrator uploads them on Configuration → Analytics ranges."})
    if clock_offset is not None and abs(clock_offset) > a.clock_warning_s:
        side = "behind" if clock_offset < 0 else "ahead of"
        warnings.append({"code": "HISTORIAN_CLOCK", "message": f"The Timebase server clock is {_duration(clock_offset)} {side} this server. Bucket times and shift boundaries follow the Timebase clock (O-18)."})
    unreadable = [f"{_duration(e.unreadable_s)} of {label} ({v.label})"
                  for label, v, e in (("X", x, ex), ("Y", y, ey)) if e.unreadable_s > 0]
    if unreadable:
        warnings.append({"code": "UNREADABLE", "message": f"Timebase couldn't return {' and '.join(unreadable)} data; that time counts as missing."})
    silent = {v.area: e.gap_s for v, e in ((x, ex), (y, ey)) if e.gap_s > 0}
    if silent:
        parts = " and ".join(f"{area} data for {_duration(sec)}" for area, sec in silent.items())
        warnings.append({"code": "DATA_GAP", "message": f"The machine sent no {parts} in this range; that time counts as missing."})
    under_review = {v.parameter_id: v for v in (x, y) if _caution(register, v)}  # once per parameter
    for v in under_review.values():
        warnings.append({"code": "VARIABLE_UNDER_REVIEW", "message": f"{v.parameter_name} ({v.zone_name}): {_caution(register, v)}"})

    result = {
        "query": {"from": isotime.iso(q.from_),
                  "to": isotime.iso(q.to),
                  "x": x.channel, "y": y.channel, "bucket": q.bucket, "bucketSeconds": width, "aggregation": q.aggregation,
                  "shift": q.shift, "groupBy": q.group_by, "groupStats": q.group_stats},
        "x": _describe_variable(register, x), "y": _describe_variable(register, y),
        "exclusions": {"x": ex.as_dict(), "y": ey.as_dict()},
        "ranges": {"version": rc.ranges.version if rc.ranges else None,
                   "x": list(valid[x.parameter_id]) if x.parameter_id in valid else None,
                   "y": list(valid[y.parameter_id]) if y.parameter_id in valid else None},
        "buckets": buckets,
        "sizeGuard": {"limit": a.pair_limit, "exceeded": False, "recommendedBucket": None},
        "pairs": None, "statistics": None, "groups": None,
        "warnings": warnings, "note": stats.NOTE,
    }

    # -- size guard (ANA-19) ----------------------------------------------------------------
    if n_pairs > a.pair_limit:
        rec = next((code for code, w in BUCKETS.items() if w > width and int(pair(w)[-1].sum()) <= a.pair_limit), None)
        result["sizeGuard"] |= {"exceeded": True, "recommendedBucket": rec}
        hint = f"choose {BUCKET_LABELS[rec]} or longer" if rec else "shorten the date range"
        warnings.append({"code": "TOO_MANY_PAIRS", "message": f"{n_pairs:,} paired buckets exceed the {a.pair_limit:,} limit, so no chart is drawn: {hint} (ANA-19)."})
        return _finish(result, settings, client_host, user, started, fetch_ms, clock_offset, n_pairs)

    # -- statistics and groups (ANA-12, ANA-16, ANA-17) --------------------------------------
    ts, xs, ys = bx.start[paired], bx.value[paired], by.value[paired]
    corr = stats.correlate(xs, ys)
    if not corr["computable"]:
        warnings.append({"code": "NOT_COMPUTABLE", "message": corr["reason"]})
    result["statistics"] = {"correlation": corr, "x": stats.describe(xs), "y": stats.describe(ys)}

    keys = None
    if q.group_by != "NONE":
        keys = shifts[paired] if q.group_by == "SHIFT" else production_date(ts)
        uniq = sorted(set(keys.tolist()))
        visible = uniq[-a.visible_groups:]  # the most recent production dates when there are more (O-10)
        groups = []
        for key in visible:
            sel = keys == key
            n = int(sel.sum())
            g = {"key": key, "label": SHIFT_LABELS.get(key, key) if q.group_by == "SHIFT" else key, "n": n,
                 "warning": "INSUFFICIENT_DATA" if n < 3 else "LOW_SAMPLE_SIZE" if n < 30 else None}
            if q.group_stats and n >= 3:
                g["correlation"] = stats.correlate(xs[sel], ys[sel])
            groups.append(g)
        result["groups"] = {"by": q.group_by, "items": groups, "hidden": len(uniq) - len(visible)}
        if len(uniq) > len(visible):
            warnings.append({"code": "GROUPS_HIDDEN", "message": f"{len(uniq) - len(visible)} older groups aren't shown; only the {a.visible_groups} most recent are (ANA-17, O-10)."})

    result["pairs"] = {"t": (ts * 1000).astype(np.int64).tolist(), "x": xs.tolist(), "y": ys.tolist(),
                       "g": keys.tolist() if keys is not None else None}
    return _finish(result, settings, client_host, user, started, fetch_ms, clock_offset, n_pairs)


def _finish(result: dict, settings: Settings, client_host: str | None, user: str | None, started: float, fetch_ms: float,
            clock_offset: float | None, n_pairs: int) -> dict:
    duration_ms = (time.monotonic() - started) * 1000
    result["meta"] = {"generatedAt": isotime.iso(datetime.now(timezone.utc)),
                      "durationMs": round(duration_ms), "fetchMs": round(fetch_ms),
                      "historianClockOffsetS": None if clock_offset is None else round(clock_offset, 1),
                      "timezone": "Asia/Manila"}
    if settings.audit_log:
        # Query metadata only: never the paired data (ANA-21)
        entry = {"at": result["meta"]["generatedAt"], "client": client_host, "user": user,
                 "query": result["query"], "ranges": result["ranges"]["version"], "pairs": n_pairs, "exceeded": result["sizeGuard"]["exceeded"],
                 "durationMs": round(duration_ms), "warnings": [w["code"] for w in result["warnings"]]}
        settings.audit_log.parent.mkdir(parents=True, exist_ok=True)
        with settings.audit_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    return result
