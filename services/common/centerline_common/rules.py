"""Monitoring rules: how one version resolves for a SKU and zone (ADR-0012). Pure functions, no I/O.

A rules version holds line-wide settings and rule rows. A row applies to one SKU
or every SKU (sku None), and to one zone or every zone of a parameter (zone_id
None). A field a row leaves empty is inherited; the most specific row that sets
it wins:

    this SKU and zone > this SKU, every zone > every SKU, this zone > every SKU and zone > line defaults

Limits are offsets around the raw HMI setpoint (A-02). Targets and limits have no
line default; delays, the brief-change mode and Warning notifications do. A SKU
is ready when every monitored zone resolves a target and all four limits;
monitor-core treats a SKU that isn't ready as unconfigured (OPC-08, ADR-0001).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

LIMITS = ("warn_low", "warn_high", "crit_low", "crit_high")
DELAYS = ("mismatch_delay_s", "warning_delay_s", "critical_delay_s", "recovery_delay_s")
HANDLING = ("brief_change_mode", "warning_notifications")
FIELDS = ("target", *LIMITS, *DELAYS, *HANDLING)
NUMERIC = ("target", *LIMITS)
DEFAULTABLE = (*DELAYS, *HANDLING)
BRIEF_CHANGE_MODES = ("do_not_record", "lightweight", "cleared_before_trigger")

LABELS = {
    "target": "Target",
    "warn_low": "Warning below",
    "warn_high": "Warning above",
    "crit_low": "Critical below",
    "crit_high": "Critical above",
    "mismatch_delay_s": "HMI mismatch delay",
    "warning_delay_s": "Warning delay",
    "critical_delay_s": "Critical delay",
    "recovery_delay_s": "Recovery delay",
    "brief_change_mode": "Short setpoint changes",
    "warning_notifications": "Warning notifications",
}

# Most specific first: (uses the SKU, uses the zone)
LAYERS = (("sku_zone", True, True), ("sku", True, False), ("zone", False, True), ("parameter", False, False))
SPECIFICITY = {"sku_zone": 4, "sku": 3, "zone": 2, "parameter": 1, "default": 0}


@dataclass(frozen=True)
class Resolved:
    value: object
    layer: str  # sku_zone | sku | zone | parameter | default | none
    row: int | None  # index of the rule row it came from


def is_empty(rule: dict) -> bool:
    return all(rule.get(f) is None for f in FIELDS)


def resolve(rules: list[dict], defaults: dict, parameter_id: str, zone_id: str, sku: str | None) -> dict[str, Resolved]:
    """Every field's effective value for one zone under one SKU (None: the rules for every SKU)."""
    index: dict[tuple, int] = {}
    for i, r in enumerate(rules):
        if r["parameter_id"] == parameter_id:
            index.setdefault((r.get("sku"), r.get("zone_id")), i)  # a repeated scope is an error; the first one counts
    out = {}
    for f in FIELDS:
        hit = Resolved(defaults.get(f), "default", None) if f in DEFAULTABLE and defaults.get(f) is not None \
            else Resolved(None, "none", None)
        for layer, uses_sku, uses_zone in LAYERS:
            if uses_sku and sku is None:
                continue
            i = index.get((sku if uses_sku else None, zone_id if uses_zone else None))
            if i is not None and rules[i].get(f) is not None:
                hit = Resolved(rules[i][f], layer, i)
                break
        out[f] = hit
    return out


def readiness(rules: list[dict], defaults: dict, zones, skus: list[str]) -> dict[str, list[dict]]:
    """What each SKU still lacks before it can be monitored; an empty list means ready.

    ``zones`` are the register's monitored zones (register.Zone). Each gap is
    {parameter_id, zone_id, label, missing}, missing being 'target' and/or field names of absent limits.
    """
    out = {}
    for sku in skus:
        gaps = []
        for z in zones:
            eff = resolve(rules, defaults, z.parameter_id, z.zone_id, sku)
            missing = [f for f in ("target", *LIMITS) if eff[f].value is None]
            if missing:
                gaps.append({"parameter_id": z.parameter_id, "zone_id": z.zone_id,
                             "label": f"{z.parameter_name} · {z.zone_name}", "missing": missing})
        out[sku] = gaps
    return out


def validate(rules: list[dict], defaults: dict, zones, known_skus: set[str]) -> list[dict]:
    """Problems that stop a version being saved, as {field, message} with fields like rules[3].critLow."""
    errors: list[dict] = []
    by_parameter: dict[str, dict[str, object]] = {}
    for z in zones:
        by_parameter.setdefault(z.parameter_id, {})[z.zone_id] = z
    seen: dict[tuple, int] = {}
    for i, r in enumerate(rules):
        pid, zid, sku = r["parameter_id"], r.get("zone_id"), r.get("sku")
        if pid not in by_parameter:
            errors.append({"field": f"rules[{i}].parameterId", "message": f"{pid} isn't monitored: set it to Monitored on the Tags tab first"})
            continue
        if zid is not None and zid not in by_parameter[pid]:
            errors.append({"field": f"rules[{i}].zoneId", "message": f"{pid} has no monitored zone {zid}"})
        if sku is not None and sku not in known_skus:
            errors.append({"field": f"rules[{i}].sku", "message": f"SKU {sku} isn't in the SKU list"})
        key = (sku, pid, zid)
        if key in seen:
            errors.append({"field": f"rules[{i}]", "message": f"Row {i + 1} repeats row {seen[key] + 1} ({_scope(pid, zid, sku)})"})
        seen[key] = i

    # Critical must lie beyond Warning once the layers are combined (ACT-01)
    reported = set()
    for sku in [None, *sorted({r["sku"] for r in rules if r.get("sku")})]:
        for z in zones:
            eff = resolve(rules, defaults, z.parameter_id, z.zone_id, sku)
            for warn, crit in (("warn_low", "crit_low"), ("warn_high", "crit_high")):
                w, c = eff[warn], eff[crit]
                if w.value is None or c.value is None or Decimal(str(c.value)) >= Decimal(str(w.value)):
                    continue
                blame, field = (c, crit) if SPECIFICITY[c.layer] >= SPECIFICITY[w.layer] else (w, warn)
                if (blame.row, field) in reported:
                    continue
                reported.add((blame.row, field))
                zonal = {c.layer, w.layer} & {"sku_zone", "zone"}
                where = f"{z.parameter_name} · {z.zone_name}" if zonal else z.parameter_name
                errors.append({"field": f"rules[{blame.row}].{_camel(field)}",
                               "message": f"{where}{f' (SKU {sku})' if sku else ''}: {LABELS[crit]} "
                                          f"({canonical_number(c.value)}) must be at least {LABELS[warn]} ({canonical_number(w.value)})"})
    return errors


def canonical_number(v):
    """Numbers as normalised decimal text, so the hash doesn't depend on 2 vs 2.0 or float noise."""
    if v is None or isinstance(v, (bool, str)):
        return v
    return format(Decimal(str(v)).normalize(), "f")


def digest(settings: dict, rules: list[dict]) -> str:
    """SHA-256 of a version's content, stored with it and checked on every read."""
    rows = sorted(({"sku": r.get("sku"), "parameter_id": r["parameter_id"], "zone_id": r.get("zone_id"),
                    **{f: canonical_number(r.get(f)) if f in NUMERIC else r.get(f) for f in FIELDS}} for r in rules),
                  key=lambda r: (r["parameter_id"], r["zone_id"] or "", r["sku"] or ""))
    text = json.dumps({"settings": settings, "rules": rows}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scope(pid: str, zid: str | None, sku: str | None) -> str:
    return f"{pid}, {'zone ' + zid if zid else 'every zone'}, {'SKU ' + sku if sku else 'every SKU'}"


def _camel(field: str) -> str:
    head, *rest = field.split("_")
    return head + "".join(p.capitalize() for p in rest)
