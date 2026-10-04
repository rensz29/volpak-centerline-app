"""The shift clock (§6.7, A-07): A at 06:00, B at 14:00, C at 22:00 Manila; the production date is the start's."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from centerline_common.shifts import MANILA, label, shift_at


def manila(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=MANILA)


def test_each_moment_belongs_to_one_eight_hour_shift_dated_by_its_start():
    cases = [(manila(1, 6), "A", 1), (manila(1, 13, 59), "A", 1), (manila(1, 14), "B", 1), (manila(1, 21, 59), "B", 1),
             (manila(1, 22), "C", 1), (manila(2, 5, 59), "C", 1), (manila(2, 6), "A", 2)]
    for t, code, day in cases:
        s = shift_at(t)
        assert (s.code, s.production_date) == (code, date(2026, 10, day)), t
        assert s.starts_at <= t < s.ends_at and s.ends_at - s.starts_at == timedelta(hours=8)
    utc = shift_at(datetime(2026, 9, 30, 22, 30, tzinfo=timezone.utc))  # 06:30 Manila on 1 Oct
    assert (utc.code, utc.production_date) == ("A", date(2026, 10, 1))
    assert label(shift_at(manila(2, 3))) == "Shift C, 1 Oct (22:00–06:00)"  # the night shift belongs to the day it starts
