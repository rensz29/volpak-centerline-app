"""Which backup sets to keep (BKP-01, ADR-0035): every set from the last 48 hours, then the newest set of each of the
last 30 days and of each of the last 12 months. Days and months are UTC calendar days and months."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Keep:
    hours: int = 48
    days: int = 30
    months: int = 12


def keep(stamps: list[datetime], now: datetime, policy: Keep = Keep()) -> set[datetime]:
    """The sets to keep, of `stamps` (aware UTC times); the newest is always kept."""
    if not stamps:
        return set()
    kept = {s for s in stamps if now - s <= timedelta(hours=policy.hours)}
    newest_of_day: dict = {}
    newest_of_month: dict = {}
    for s in stamps:
        day, month = s.date(), (s.year, s.month)
        newest_of_day[day] = max(s, newest_of_day.get(day, s))
        newest_of_month[month] = max(s, newest_of_month.get(month, s))
    kept |= {s for day, s in newest_of_day.items() if (now.date() - day).days < policy.days}
    this_month = now.year * 12 + now.month
    kept |= {s for (y, m), s in newest_of_month.items() if this_month - (y * 12 + m) < policy.months}
    kept.add(max(stamps))
    return kept
