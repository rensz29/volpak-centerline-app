"""Monitoring rules: how one version resolves for a zone (ADR-0012, ADR-0027). Pure functions, no I/O.

A rules version holds line-wide settings and rule rows. A row applies to one zone or every zone of a
parameter (zone_id None). A field a row leaves empty is inherited; the more specific row that sets it wins:

    this zone > every zone of the parameter > line defaults

Limits are offsets around the raw HMI setpoint (A-02). Targets and limits have no line default;
delays, the brief-change mode and Warning notifications do. The line is judged once every monitored
zone resolves all four limits; a zone's HMI setpoint is judged once it also has a target.

There is no SKU (ADR-0027). Versions saved before then may hold rows for a SKU: they still count in
the version's fingerprint, but no zone is judged by them. `carry_over` turns one SKU's rows into rows
for the line, for the editor to start a new version from.
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

# Most specific first: (layer, uses the zone)
LAYERS = (("zone", True), ("parameter", False))
SPECIFICITY = {"zone": 2, "parameter": 1, "default": 0}


@dataclass(frozen=True)
class Resolved:
    value: object
    layer: str  # zone | parameter | default | none
    row: int | None  # index of the rule row it came from


def is_empty(rule: dict) -> bool:
    return all(rule.get(f) is None for f in FIELDS)


def resolve(rules: list[dict], defaults: dict, parameter_id: str, zone_id: str) -> dict[str, Resolved]:
    """Every field's effective value for one zone. Rows saved for a SKU before ADR-0027 don't count."""
    index: dict[str | None, int] = {}
    for i, r in enumerate(rules):
        if r["parameter_id"] == parameter_id and r.get("sku") is None:
            index.setdefault(r.get("zone_id"), i)  # a repeated scope is an error; the first one counts
    out = {}
    for f in FIELDS:
        hit = Resolved(defaults.get(f), "default", None) if f in DEFAULTABLE and defaults.get(f) is not None \
            else Resolved(None, "none", None)
        for layer, uses_zone in LAYERS:
            i = index.get(zone_id if uses_zone else None)
            if i is not None and rules[i].get(f) is not None:
                hit = Resolved(rules[i][f], layer, i)
                break
        out[f] = hit
    return out


def readiness(rules: list[dict], defaults: dict, zones) -> list[dict]:
    """What each zone still lacks: limits, without which the line isn't judged, or a target, without which that
    zone's HMI setpoint isn't. An empty list means every zone is fully judged.

    ``zones`` are the register's monitored zones (register.Zone). Each gap is
    {parameter_id, zone_id, label, missing}, missing being 'target' and/or the names of absent limits.
    """
    gaps = []
    for z in zones:
        eff = resolve(rules, defaults, z.parameter_id, z.zone_id)
        missing = [f for f in ("target", *LIMITS) if eff[f].value is None]
        if missing:
            gaps.append({"parameter_id": z.parameter_id, "zone_id": z.zone_id,
                         "label": f"{z.parameter_name} · {z.zone_name}", "missing": missing})
    return gaps


def limits_complete(rules: list[dict], defaults: dict, zones) -> bool:
    """Every zone has all four limits: the line can be judged (targets are optional, per zone)."""
    return all(g["missing"] == ["target"] for g in readiness(rules, defaults, zones))


def carry_over(rules: list[dict]) -> tuple[list[dict], str | None]:
    """A version saved before ADR-0027 as rows for the line: the rows of its SKU (the one with the most rows, if
    it had several) fill in whatever the line's rows leave empty. Returns the rows and that SKU, if any."""
    line = [dict(r) for r in rules if r.get("sku") is None]
    skus = [r["sku"] for r in rules if r.get("sku") is not None]
    if not skus:
        return line, None
    chosen = max(sorted(set(skus)), key=skus.count)
    for r in rules:
        if r.get("sku") != chosen:
            continue
        mine = next((x for x in line if x["parameter_id"] == r["parameter_id"] and x.get("zone_id") == r.get("zone_id")), None)
        if mine is None:
            line.append({**{k: v for k, v in r.items() if k != "sku"}, "sku": None})
        else:
            for f in FIELDS:
                if mine.get(f) is None and r.get(f) is not None:
                    mine[f] = r[f]
    return [{k: v for k, v in r.items() if k != "sku"} for r in line], chosen


def validate(rules: list[dict], defaults: dict, zones) -> list[dict]:
    """Problems that stop a version being saved, as {field, message} with fields like rules[3].critLow."""
    errors: list[dict] = []
    by_parameter: dict[str, dict[str, object]] = {}
    for z in zones:
        by_parameter.setdefault(z.parameter_id, {})[z.zone_id] = z
    seen: dict[tuple, int] = {}
    for i, r in enumerate(rules):
        pid, zid = r["parameter_id"], r.get("zone_id")
        if pid not in by_parameter:
            errors.append({"field": f"rules[{i}].parameterId", "message": f"{pid} isn't monitored: set it to Monitored on the Tags tab first"})
            continue
        if zid is not None and zid not in by_parameter[pid]:
            errors.append({"field": f"rules[{i}].zoneId", "message": f"{pid} has no monitored zone {zid}"})
        key = (pid, zid)
        if key in seen:
            errors.append({"field": f"rules[{i}]", "message": f"Row {i + 1} repeats row {seen[key] + 1} ({_scope(pid, zid)})"})
        seen[key] = i

    # Critical must lie beyond Warning once the layers are combined (ACT-01)
    reported = set()
    for z in zones:
        eff = resolve(rules, defaults, z.parameter_id, z.zone_id)
        for warn, crit in (("warn_low", "crit_low"), ("warn_high", "crit_high")):
            w, c = eff[warn], eff[crit]
            if w.value is None or c.value is None or Decimal(str(c.value)) >= Decimal(str(w.value)):
                continue
            blame, field = (c, crit) if SPECIFICITY[c.layer] >= SPECIFICITY[w.layer] else (w, warn)
            if (blame.row, field) in reported:
                continue
            reported.add((blame.row, field))
            where = f"{z.parameter_name} · {z.zone_name}" if "zone" in {c.layer, w.layer} else z.parameter_name
            errors.append({"field": f"rules[{blame.row}].{_camel(field)}",
                           "message": f"{where}: {LABELS[crit]} ({canonical_number(c.value)}) must be at least "
                                      f"{LABELS[warn]} ({canonical_number(w.value)})"})
    return errors


def canonical_number(v):
    """Numbers as normalised decimal text, so the hash doesn't depend on 2 vs 2.0 or float noise."""
    if v is None or isinstance(v, (bool, str)):
        return v
    return format(Decimal(str(v)).normalize(), "f")


def digest(settings: dict, rules: list[dict]) -> str:
    """SHA-256 of a version's content, stored with it and checked on every read. Rows have no SKU since ADR-0027;
    those saved for one before still hash with it, so earlier versions keep their fingerprints."""
    rows = sorted(({"sku": r.get("sku"), "parameter_id": r["parameter_id"], "zone_id": r.get("zone_id"),
                    **{f: canonical_number(r.get(f)) if f in NUMERIC else r.get(f) for f in FIELDS}} for r in rules),
                  key=lambda r: (r["parameter_id"], r["zone_id"] or "", r["sku"] or ""))
    text = json.dumps({"settings": settings, "rules": rows}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scope(pid: str, zid: str | None) -> str:
    return f"{pid}, {'zone ' + zid if zid else 'every zone'}"


def _camel(field: str) -> str:
    head, *rest = field.split("_")
    return head + "".join(p.capitalize() for p in rest)
