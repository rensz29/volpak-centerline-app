"""Protected degraded mode, as monitor-core reports it in its heartbeat (RES-02, O-12, ADR-0036).

monitor-core measures the disk under its journal and the database every minute. While it says "degraded", new
uploads (OCAP files, guidance files) are refused and the Analytics query log isn't written; everything else carries
on. Without a fresh heartbeat the state is unknown, and nothing is refused.
"""

from __future__ import annotations

from .problems import Problem

FRESH_S = 60  # as the live page: an older heartbeat means monitor-core isn't running (guide §6.7)


def storage(conn) -> dict | None:
    """The storage state monitor-core last reported, or None without a fresh heartbeat."""
    row = conn.execute("""SELECT status->'storage' AS storage FROM monitor_heartbeat
                           WHERE beat_at > clock_timestamp() - make_interval(secs => %s)
                           ORDER BY beat_at DESC LIMIT 1""", (FRESH_S,)).fetchone()
    return row["storage"] if row else None


def degraded(conn) -> bool:
    s = storage(conn)
    return bool(s and s.get("state") == "degraded")


def refuse_uploads(conn) -> None:
    """New uploads stop in protected degraded mode (O-12): the files are the largest writes there are."""
    s = storage(conn)
    if s and s.get("state") == "degraded":
        raise Problem(507, "storage-full", "Uploads are paused: storage is full",
                      f"The disk is {s.get('usedPct')} % full, so new files aren't kept (RES-02). An Administrator frees "
                      f"space; uploads resume once it's under {s.get('limits', {}).get('degradedUntilBelow', 85)} %.")
