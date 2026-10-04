"""The shift clock (§6.7, A-07): shifts A, B and C start at 06:00, 14:00 and 22:00 Asia/Manila.

The production date is the Manila date a shift starts, so the 22:00 shift belongs to the day it
begins. Manila has no daylight saving time, so every shift lasts 8 hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .db import uuid7

MANILA = timezone(timedelta(hours=8))
STARTS = {"A": 6, "B": 14, "C": 22}
LENGTH = timedelta(hours=8)


@dataclass(frozen=True)
class Shift:
    code: str
    starts_at: datetime
    ends_at: datetime
    production_date: date


def shift_at(t: datetime) -> Shift:
    """The shift a moment belongs to."""
    m = t.astimezone(MANILA)
    if m.hour < STARTS["A"]:  # before 06:00: still the 22:00 shift of the day before
        code, day = "C", m.date() - timedelta(days=1)
    elif m.hour < STARTS["B"]:
        code, day = "A", m.date()
    elif m.hour < STARTS["C"]:
        code, day = "B", m.date()
    else:
        code, day = "C", m.date()
    starts = datetime(day.year, day.month, day.day, STARTS[code], tzinfo=MANILA)
    return Shift(code, starts, starts + LENGTH, day)


def shift_id(conn, t: datetime):
    """The shift_instance row for the shift at t, made the first time it's needed."""
    s = shift_at(t)
    conn.execute("""INSERT INTO shift_instance (id, code, starts_at, ends_at, production_date) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (starts_at) DO NOTHING""", (uuid7(), s.code, s.starts_at, s.ends_at, s.production_date))
    return conn.execute("SELECT id FROM shift_instance WHERE starts_at = %s", (s.starts_at,)).fetchone()["id"]


def label(s: Shift) -> str:
    """How people name it: "Shift A, 1 Oct (06:00–14:00)"."""
    start, end = s.starts_at.astimezone(MANILA), s.ends_at.astimezone(MANILA)  # rows read back come in UTC
    return f"Shift {s.code}, {s.production_date.day} {s.production_date:%b} ({start:%H:%M}–{end:%H:%M})"
