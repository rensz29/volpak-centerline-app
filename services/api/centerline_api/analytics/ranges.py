"""Analytics-valid engineering ranges (ANA-10, SDD §8).

A CSV with columns parameter_id, unit, valid_min, valid_max and exactly one
row for each parameter in the register (P01–P11). The file is accepted or
rejected as a whole: units must match the register and min must be below max.
Versioning, the Administrator's reason and rollback (ANA-11) need the
database and come with Phase 1; until then the active file is the one in the
api config, identified by its SHA-256.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass, field
from pathlib import Path

from centerline_common.register import Register

NO_UNIT = {"", "-", "none", "no unit", "n/a"}
COLUMNS = ("parameter_id", "unit", "valid_min", "valid_max")


@dataclass(frozen=True)
class RangeSet:
    ranges: dict[str, tuple[float, float]]
    source: str
    sha256: str


@dataclass
class RangeCheck:
    ranges: RangeSet | None = None
    problems: list[str] = field(default_factory=list)


def _unit_matches(csv_unit: str, register_unit: str | None) -> bool:
    got = csv_unit.strip().lower()
    return got in NO_UNIT if register_unit is None else got == register_unit.strip().lower()


def parse_ranges(data: bytes, register: Register, source: str) -> RangeCheck:
    problems: list[str] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return RangeCheck(problems=["The file isn't UTF-8 text"])
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    if sorted(header) != sorted(COLUMNS):
        return RangeCheck(problems=[f"Columns must be {', '.join(COLUMNS)}; found {', '.join(header) or 'none'}"])
    units = register.units()
    seen: dict[str, tuple[float, float]] = {}
    for line, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        pid = row["parameter_id"]
        if pid not in units:
            problems.append(f"Line {line}: unknown parameter {pid!r}")
            continue
        if pid in seen:
            problems.append(f"Line {line}: {pid} appears more than once")
            continue
        if not _unit_matches(row["unit"], units[pid]):
            problems.append(f"Line {line}: {pid} unit {row['unit']!r} doesn't match the register ({units[pid] or 'no unit'})")
        try:
            lo, hi = float(row["valid_min"]), float(row["valid_max"])
        except ValueError:
            problems.append(f"Line {line}: {pid} valid_min/valid_max must be numbers")
            continue
        if not (math.isfinite(lo) and math.isfinite(hi)) or lo >= hi:
            problems.append(f"Line {line}: {pid} needs finite valid_min < valid_max")
            continue
        seen[pid] = (lo, hi)
    missing = [p for p in units if p not in seen]
    if missing:
        problems.append(f"Missing parameters: {', '.join(missing)} (every register parameter needs a row)")
    if problems:
        return RangeCheck(problems=problems)
    return RangeCheck(RangeSet(seen, source, hashlib.sha256(data).hexdigest()))


_cache: dict[tuple[str, float], RangeCheck] = {}


def load_ranges(path: Path | None, register: Register) -> RangeCheck:
    """The configured file, re-read when it changes on disk."""
    if path is None:
        return RangeCheck()
    if not path.exists():
        return RangeCheck(problems=[f"Configured ranges file not found: {path.name}"])
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache.clear()
        _cache[key] = parse_ranges(path.read_bytes(), register, path.name)
    return _cache[key]
