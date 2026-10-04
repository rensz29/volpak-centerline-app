"""The retry schedule (NOT-04/05). Pure.

A delivery is first tried within 10 s of being created, then 30 s, 1 min and 5 min after each
failed attempt, then every 15 min. An attempt that would fall more than 24 h after the
delivery was created isn't made: the delivery is a permanent failure, which an Administrator
can re-drive.
"""

from __future__ import annotations

from datetime import datetime, timedelta

WAITS = (timedelta(seconds=30), timedelta(minutes=1), timedelta(minutes=5))
EVERY = timedelta(minutes=15)
GIVE_UP = timedelta(hours=24)


def next_attempt(created_at: datetime, failed: int, now: datetime) -> datetime | None:
    """When to try again after `failed` failed attempts, or None to give up."""
    at = now + (WAITS[failed - 1] if failed <= len(WAITS) else EVERY)
    return None if at > created_at + GIVE_UP else at
