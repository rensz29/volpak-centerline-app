"""PostgreSQL for monitor-core (ADR-0014): each step's effects in one transaction (invariant 6),
and what the engine reads: its configuration, the open events to carry on after a restart,
and new acknowledgments.

Every write is safe to repeat (UUIDv7 keys, dedup keys). If the database can't be reached,
steps go to the disk journal, in order, and are written when it returns, also after a restart
of monitor-core (RES-01, ADR-0018).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from centerline_common import shifts, workflow
from centerline_common.db import DatabaseConfig, DatabaseUnavailable, uuid7
from centerline_common.isotime import iso
from psycopg.types.json import Jsonb

from . import config as config_mod
from .effects import (BriefChange, CancelTimer, Notify, OpenEvent, PauseEnded, PauseStarted, StartTimer, TimerDone,
                      Transition, Versions)
from .journal import Journal
from .machines import text

log = logging.getLogger("centerline.monitor")
FAILURES = (psycopg.OperationalError, psycopg.InterfaceError, DatabaseUnavailable)
RETRY_S = 5  # after losing the database, steps go straight to the journal this long before trying it again


class Store:
    def __init__(self, database: DatabaseConfig, config_dir: Path, instance: str, journal_path: Path | None = None):
        self.database = database
        self.config_dir = config_dir
        self.instance = instance
        self.conn = None
        self.journal = Journal(journal_path or config_dir / "journal" / f"{instance}.jsonl")
        self.retry_at: datetime | None = None
        self.ack_seq = 0

    def reachable(self, now: datetime) -> bool:
        """False for a few seconds after the database was lost: nothing waits on it meanwhile."""
        return self.retry_at is None or now >= self.retry_at

    def _conn(self):
        if self.conn is None or self.conn.closed:
            self.conn = self.database.connect()
        return self.conn

    def _lost(self, e: Exception, now: datetime | None = None) -> None:
        self.retry_at = (now or datetime.now(timezone.utc)) + timedelta(seconds=RETRY_S)
        log.warning("database unavailable (%d step(s) in the journal): %s", self.journal.steps, e)
        if self.conn is not None and not self.conn.closed:
            self.conn.close()
        self.conn = None

    # -- start-up and configuration -------------------------------------------------------

    def start(self, now: datetime) -> None:
        """Before judging: the previous run's journal is written first (RES-01); then its timers restart from
        zero (MNT-02) and its open pauses end now."""
        if not self.drain(now, force=True):
            raise DatabaseUnavailable("the journal couldn't be written yet")
        conn = self._conn()
        conn.execute("UPDATE scheduled_action SET status = 'abandoned', finished_at = %s WHERE status = 'pending'", (now,))
        conn.execute("UPDATE pause_period SET ended_at = %s WHERE ended_at IS NULL", (now,))
        # Every acknowledgment of an open event is read again: one given while monitor-core was down
        # still counts, and the machines ignore the ones they've applied or that were for an earlier period
        self.ack_seq = 0
        conn.commit()

    def config(self) -> config_mod.EngineConfig:
        return config_mod.load(self._conn(), self.config_dir)

    def signature(self) -> tuple:
        return config_mod.signature(self._conn(), self.config_dir)

    def open_events(self) -> list[dict]:
        """Open events with what the machines need to carry on: pinned rule, severity, repeats sent."""
        conn = self._conn()
        rows = conn.execute("""
            SELECT e.id, e.kind, e.parameter_id, e.zone_id, e.rule, e.raw_hmi, e.config_version_id,
                   e.mapping_version_id, e.register_version_id, s.severity,
                   -- acknowledged in the current Critical period: a new period needs a new acknowledgment (ACT-04)
                   EXISTS (SELECT 1 FROM event_transition a WHERE a.event_id = e.id AND a.state = 'ACKNOWLEDGED'
                              AND a.seq > coalesce((SELECT max(c.seq) FROM event_transition c
                                                     WHERE c.event_id = e.id AND c.state = 'CRITICAL'), 0)) AS acknowledged,
                   (SELECT count(*) FROM event_transition t WHERE t.event_id = e.id AND t.state = 'CRITICAL') AS periods
              FROM event e JOIN event_state s ON s.event_id = e.id
             WHERE s.open""").fetchall()
        out = []
        for r in rows:
            prefix = f"{r['id']}:critical:{r['periods']}"
            sent = conn.execute("""SELECT count(*) FILTER (WHERE dedup_key LIKE %s) AS repeats,
                                          count(*) FILTER (WHERE dedup_key = %s) AS escalated
                                     FROM notification WHERE event_id = %s""",
                                (f"{prefix}:repeat:%", f"{prefix}:escalation", r["id"])).fetchone()
            out.append({"id": r["id"], "kind": r["kind"], "parameter_id": r["parameter_id"], "zone_id": r["zone_id"],
                        "rule": r["rule"], "raw_hmi": r["raw_hmi"], "severity": r["severity"],
                        "acknowledged": r["acknowledged"], "critical_periods": r["periods"],
                        "repeats": sent["repeats"], "escalated": sent["escalated"] > 0,
                        "versions": Versions(r["config_version_id"], r["mapping_version_id"], r["register_version_id"])})
        conn.commit()
        return out

    def new_acks(self) -> list[dict]:
        """Acknowledgments of open events not read yet: who, why, and the Critical period they're for."""
        conn = self._conn()
        rows = conn.execute("""SELECT a.seq, a.id, a.event_id, a.by_user, a.note, a.critical_period
                                 FROM event_acknowledgment a JOIN event_state s ON s.event_id = a.event_id
                                WHERE a.seq > %s AND s.open ORDER BY a.seq""", (self.ack_seq,)).fetchall()
        conn.commit()
        if rows:
            self.ack_seq = rows[-1]["seq"]
        return [dict(r) for r in rows]

    def control(self) -> tuple[dict, list[dict]]:
        """Zones switched off, by their latest switch (MON-01), and maintenance windows not ended (MNT-01)."""
        conn = self._conn()
        off = {r["channel"]: dict(r) for r in conn.execute(
            """SELECT DISTINCT ON (channel) channel, enabled, at, by_user, reason
                 FROM monitoring_switch ORDER BY channel, seq DESC""").fetchall() if not r["enabled"]}
        windows = [dict(r) for r in conn.execute(
            """SELECT id, scope, channels, reason, planned_start, planned_end
                 FROM maintenance_window WHERE ended_at IS NULL ORDER BY planned_start""").fetchall()]
        conn.commit()
        return off, windows

    def workflow_tick(self, now: datetime, names: dict) -> None:
        """Requests of a shift that's over close as not answered; one open 15 min alerts Management once (WF-03)."""
        conn = self._conn()
        closed = workflow.close_ended_shifts(conn, now)
        for r in workflow.overdue(conn, now):
            parameter, zone, unit = names.get((r["parameter_id"], r["zone_id"]), (r["parameter_id"], r["zone_id"], None))
            shift = shifts.Shift(r["shift"], r["starts_at"], r["ends_at"], r["production_date"])
            payload = {"kind": "Reason overdue", "parameter": r["parameter_id"], "parameterName": parameter,
                       "zone": r["zone_id"], "zoneName": zone, "unit": unit,
                       "hmi": text(r["raw_hmi"]), "target": text(r["raw_target"]),
                       "shift": r["shift"], "shiftLabel": shifts.label(shift), "request": str(r["id"]),
                       "waitingSince": iso(r["created_at"]), "status": r["status"]}
            conn.execute("""INSERT INTO notification (id, dedup_key, kind, event_id, created_at, payload)
                            VALUES (%s, %s, 'workflow_escalation', %s, %s, %s) ON CONFLICT (dedup_key) DO NOTHING""",
                         (uuid7(), f"workflow:{r['id']}:escalation", r["event_id"], now, Jsonb(payload)))
            conn.execute("UPDATE workflow_request SET escalated_at = %s, updated_at = %s WHERE id = %s", (now, now, r["id"]))
            log.info("reason overdue on %s.%s (%s): Management told", r["parameter_id"], r["zone_id"], shifts.label(shift))
        conn.commit()
        if closed:
            log.info("%d reason request(s) closed as not answered: their shift ended", closed)

    def heartbeat(self, now: datetime, started: datetime, status: dict) -> None:
        conn = self._conn()
        conn.execute("""INSERT INTO monitor_heartbeat (instance, started_at, beat_at, status) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (instance) DO UPDATE SET started_at = EXCLUDED.started_at, beat_at = EXCLUDED.beat_at,
                                                            status = EXCLUDED.status""",
                     (self.instance, started, now, Jsonb(status)))
        conn.commit()

    # -- writing ------------------------------------------------------------------------

    def apply(self, fx: list, now: datetime) -> None:
        """One step's effects in one transaction. While the database is away they go to the journal, in order
        behind any steps already there, and are written when it's back (RES-01)."""
        if self.journal.pending or (self.retry_at is not None and now < self.retry_at):
            self.journal.append(fx, now)
            self.drain(now)  # writes it all, in order, once the database answers again
            return
        try:
            conn = self._conn()
            with conn.transaction():
                for e in fx:
                    self._write(conn, e, now)
        except FAILURES as e:
            self.journal.append(fx, now)
            self._lost(e, now)

    def drain(self, now: datetime, force: bool = False) -> bool:
        """Write the journal's steps in order, each in its own transaction; True once it's empty. Soon after
        losing the database it doesn't try, unless forced. A replay cut short writes them again next time:
        every write is safe to repeat."""
        if not self.journal.pending:
            return True
        if not force and self.retry_at is not None and now < self.retry_at:
            return False
        try:
            conn = self._conn()
            written = 0
            for fx, at in self.journal.entries():
                with conn.transaction():
                    for e in fx:
                        self._write(conn, e, at)
                written += 1
        except FAILURES as e:
            self._lost(e, now)
            return False
        self.journal.clear()
        self.retry_at = None
        log.info("database reachable again: %d journalled step(s) written in order", written)
        return True

    @staticmethod
    def _write(conn, e, at: datetime) -> None:
        if isinstance(e, OpenEvent):
            v = e.versions
            conn.execute("""INSERT INTO event (id, kind, parameter_id, zone_id, opened_at, severity, raw_target,
                                               raw_hmi, raw_actual, config_version_id, mapping_version_id,
                                               register_version_id, supersedes_event_id, rule)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                         (e.event_id, e.kind, e.zone.parameter_id, e.zone.zone_id, e.at, e.severity, e.raw_target,
                          e.raw_hmi, e.raw_actual, v.config_version_id, v.mapping_version_id, v.register_version_id,
                          e.supersedes, Jsonb(e.rule)))
            conn.execute("""INSERT INTO event_state (event_id, state, severity, open, updated_at) VALUES (%s, %s, %s, true, %s)
                            ON CONFLICT (event_id) DO NOTHING""", (e.event_id, e.severity or "OPEN", e.severity, e.at))
            if e.kind == "HMI_MISMATCH":  # that shift's operator says why (WF-01), in the same transaction (HMI-02)
                workflow.open_request(conn, e.event_id, e.at)
        elif isinstance(e, Transition):
            conn.execute("""INSERT INTO event_transition (id, event_id, seq, at, state, inputs)
                            SELECT %s, %s, coalesce(max(seq), 0) + 1, %s, %s, %s FROM event_transition WHERE event_id = %s
                            ON CONFLICT (id) DO NOTHING""", (e.id, e.event_id, e.at, e.state, Jsonb(e.inputs), e.event_id))
            if e.state == "ACKNOWLEDGED":
                conn.execute("UPDATE event_state SET acknowledged_at = %s, updated_at = %s WHERE event_id = %s",
                             (e.at, e.at, e.event_id))
            else:
                # A new Critical period needs its own acknowledgment (ACT-04)
                conn.execute("""UPDATE event_state SET state = %s, severity = coalesce(%s, severity), open = %s, updated_at = %s,
                                       closed_at = CASE WHEN %s THEN closed_at ELSE %s END,
                                       acknowledged_at = CASE WHEN %s = 'CRITICAL' THEN NULL ELSE acknowledged_at END
                                 WHERE event_id = %s""", (e.state, e.severity, e.open, e.at, e.open, e.at, e.state, e.event_id))
                if not e.open:
                    workflow.close_requests(conn, e.event_id, e.state, e.at)  # its reason request closes with it
        elif isinstance(e, BriefChange):
            v = e.versions
            conn.execute("""INSERT INTO lightweight_change (id, parameter_id, zone_id, mode, started_at, ended_at,
                                                            raw_target, raw_hmi, config_version_id, mapping_version_id, evidence)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                         (e.id, e.zone.parameter_id, e.zone.zone_id, e.mode, e.started_at, e.ended_at, e.raw_target,
                          e.raw_hmi, v.config_version_id, v.mapping_version_id, Jsonb(e.evidence) if e.evidence else None))
        elif isinstance(e, Notify):
            conn.execute("""INSERT INTO notification (id, dedup_key, kind, event_id, created_at, payload)
                            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (dedup_key) DO NOTHING""",
                         (uuid7(), e.dedup_key, e.kind, e.event_id, e.at, Jsonb(e.payload)))
        elif isinstance(e, StartTimer):
            conn.execute("UPDATE scheduled_action SET status = 'cancelled', finished_at = %s WHERE key = %s AND status = 'pending'",
                         (at, e.key))
            conn.execute("""INSERT INTO scheduled_action (id, key, kind, event_id, due_at, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                         (e.id, e.key, e.kind, e.event_id, e.due, at))
        elif isinstance(e, (CancelTimer, TimerDone)):
            status, when = ("cancelled", at) if isinstance(e, CancelTimer) else ("done", e.at)
            conn.execute("UPDATE scheduled_action SET status = %s, finished_at = %s WHERE key = %s AND status = 'pending'",
                         (status, when, e.key))
        elif isinstance(e, PauseStarted):
            conn.execute("UPDATE pause_period SET ended_at = %s WHERE scope = %s AND ended_at IS NULL", (e.at, e.scope))
            conn.execute("INSERT INTO pause_period (id, scope, started_at, reasons) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                         (e.id, e.scope, e.at, Jsonb(e.reasons)))
        elif isinstance(e, PauseEnded):
            conn.execute("UPDATE pause_period SET ended_at = %s WHERE scope = %s AND ended_at IS NULL", (e.at, e.scope))
