"""Analytics-valid engineering ranges (ANA-10/11, SDD §9.3, ADR-0029).

A CSV with columns parameter_id, unit, valid_min, valid_max and exactly one row for each parameter in the
register (P01–P11). The file is accepted or rejected as a whole: units must match the register and min must be
below max. An Administrator uploads it on the Configuration page; each accepted file is a version in the database,
kept as uploaded with its SHA-256 (config/ranges_store.py). Queries use the version in effect, checked again
against the register as it is now: a range set that no longer fits it isn't applied, and every result says why.
A sample counts as valid when valid_min ≤ value ≤ valid_max; the range applies to the parameter's actual values
and setpoints alike.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass, field

from centerline_common.register import Register

NO_UNIT = {"", "-", "none", "no unit", "n/a"}
COLUMNS = ("parameter_id", "unit", "valid_min", "valid_max")


@dataclass(frozen=True)
class RangeSet:
    ranges: dict[str, tuple[float, float]]
    source: str
    sha256: str
    units: dict[str, str] = field(default_factory=dict)  # as written in the file
    version: int | None = None  # the version in effect, once saved


@dataclass
class RangeCheck:
    ranges: RangeSet | None = None
    problems: list[str] = field(default_factory=list)


def _unit_matches(csv_unit: str, register_unit: str | None) -> bool:
    got = csv_unit.strip().lower()
    return got in NO_UNIT if register_unit is None else got == register_unit.strip().lower()


def _check(rows: list[tuple[int | None, str, str, str, str]], register: Register) -> tuple[dict, dict, list[str]]:
    """(line, parameter_id, unit, min, max) rows against the register: the ranges, their units and the problems."""
    problems: list[str] = []
    units = register.units()
    seen: dict[str, tuple[float, float]] = {}
    written: dict[str, str] = {}
    for line, pid, unit, lo_s, hi_s in rows:
        at = f"Line {line}: " if line else ""
        if pid not in units:
            problems.append(f"{at}unknown parameter {pid!r}")
            continue
        if pid in seen:
            problems.append(f"{at}{pid} appears more than once")
            continue
        if not _unit_matches(unit, units[pid]):
            problems.append(f"{at}{pid} unit {unit!r} doesn't match the register ({units[pid] or 'no unit'})")
        try:
            lo, hi = float(lo_s), float(hi_s)
        except ValueError:
            problems.append(f"{at}{pid} valid_min/valid_max must be numbers")
            continue
        if not (math.isfinite(lo) and math.isfinite(hi)) or lo >= hi:
            problems.append(f"{at}{pid} needs finite valid_min < valid_max")
            continue
        seen[pid], written[pid] = (lo, hi), unit
    missing = [p for p in units if p not in seen and not any(r[1] == p for r in rows)]
    if missing:
        problems.append(f"Missing parameters: {', '.join(missing)} (every register parameter needs a row)")
    return seen, written, problems


def parse_ranges(data: bytes, register: Register, source: str) -> RangeCheck:
    """A whole file, accepted with its SHA-256 or rejected with every problem found."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return RangeCheck(problems=["The file isn't UTF-8 text"])
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    if sorted(header) != sorted(COLUMNS):
        return RangeCheck(problems=[f"Columns must be {', '.join(COLUMNS)}; found {', '.join(header) or 'none'}"])
    rows = []
    for line, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        rows.append((line, row["parameter_id"], row["unit"], row["valid_min"], row["valid_max"]))
    seen, written, problems = _check(rows, register)
    if problems:
        return RangeCheck(problems=problems)
    return RangeCheck(RangeSet(seen, source, hashlib.sha256(data).hexdigest(), written))


def template(register: Register) -> str:
    """The file to fill in: every register parameter with its unit, the limits left for process engineering."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for pid, unit in register.units().items():
        w.writerow([pid, unit or "", "", ""])
    return out.getvalue()


_cache: dict[tuple, RangeCheck] = {}


def active(conn, register: Register) -> RangeCheck:
    """The version in effect, checked against the register as it is now; RangeCheck() when none is."""
    v = conn.execute("""SELECT id, number, source, sha256 FROM analytics_range_version
                         WHERE id = active_analytics_range_version()""").fetchone()
    if v is None:
        return RangeCheck()
    key = (v["id"], register.version, tuple(register.units().items()))
    if key not in _cache:
        rows = conn.execute("""SELECT parameter_id, unit, valid_min, valid_max FROM analytics_range
                                WHERE version_id = %s ORDER BY parameter_id""", (v["id"],)).fetchall()
        seen, written, problems = _check([(None, r["parameter_id"], r["unit"] or "", str(r["valid_min"]), str(r["valid_max"]))
                                          for r in rows], register)
        _cache.clear()
        _cache[key] = (RangeCheck(problems=[f"Analytics ranges v{v['number']} no longer fit the register: " + "; ".join(problems)])
                       if problems else RangeCheck(RangeSet(seen, v["source"], v["sha256"], written, v["number"])))
    return _cache[key]
