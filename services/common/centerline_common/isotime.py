"""Times as the api writes them: ISO 8601 in UTC, ending in `Z` (SDD §11, ADR-0028).

Dedup keys and monitor-core's journal keep `isoformat()`: they're identifiers and an internal file, not times
anyone reads, and changing them would let a key made before the change miss its match.
"""

from __future__ import annotations

from datetime import datetime, timezone


def iso(t: datetime | None, timespec: str = "auto") -> str | None:
    """`2026-10-06T07:45:12.345678Z`; `timespec` as for datetime.isoformat ("seconds" for the audit trail)."""
    return None if t is None else t.astimezone(timezone.utc).isoformat(timespec=timespec).replace("+00:00", "Z")


def parse(s: str) -> datetime:
    """Either form, `Z` or `+00:00` (Python before 3.11 doesn't read `Z`)."""
    return datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
