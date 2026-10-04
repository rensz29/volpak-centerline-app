# ADR-0018: monitor-core's disk journal during a database outage (Phase 1)

- **Status:** Accepted
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner), with the Phase 1 go-ahead; the design follows the SDD
- **Related:** [ADR-0014](ADR-0014-monitor-core.md) (it kept writes in memory only), [ADR-0017](ADR-0017-monitoring-control.md)
- **URS:** RES-01, RES-02 (in part), MNT-02; guide §6.6; SDD §4 "Database outage"; open item O-12

## Context

- RES-01 asks for protected disk buffering during a database outage, 30 min by default,
  with ordered, idempotent replay.
- The SDD: monitor-core keeps judging, appends every write to a protected disk journal with
  a sequence number, and replays in order when PostgreSQL returns. Unique IDs make the
  replay safe to repeat, notifications raised meanwhile go out after the replay, and a
  full buffer enters "protected degraded mode".
- What that mode stops or keeps is open (O-12, Phase 5).
- Until now, steps waited in memory, so a restart of monitor-core during an outage lost them.

## Decision

1. **The journal.** When a step (one judgement's effects: events, transitions, outbox rows,
   timers, pauses) can't be written, it's appended to `data/journal/<instance>.jsonl` as
   one JSON line and flushed to disk (`fsync`) before judging goes on.
   - The file is 0600 and the folder 0700. The folder is set with `journal_dir` in the
     monitor-core config; in production it's a volume.
   - Each line's position is its sequence, so steps are replayed in the order they were
     made.
   - Steps made while the journal isn't empty go behind the ones already there, so the
     order holds.
2. **Replay:**
   - While the database is away, monitor-core tries it again every 5 s. A lost database
     doesn't stall judging: steps go straight to the journal meanwhile.
   - When the database answers, the steps are written in order, one transaction each, and
     the journal is emptied.
   - Every write is safe to repeat (UUIDv7 keys, dedup keys, `ON CONFLICT DO NOTHING`), so
     a replay cut short by a crash simply runs again.
   - A last line torn by a crash was never on disk whole, and is skipped.
3. **A restart replays the last run's journal before anything else.** Only then are the
   old timers abandoned and the open events read back, so the history is whole first.
   monitor-core still needs the database to start: its configuration is there.
4. **Past the limit** (`journal_limit_s`, RES-01's 30 min by default), the gate closes:
   "The database has been unreachable for N min, longer than the journal's 30 min:
   judging is paused until it's back; everything so far is kept".
   - Nothing new is judged, so the journal stops growing, and nothing is dropped (RES-02:
     never delete protected records silently).
   - When the database is back, the journal is written and judging resumes.
   - This is the provisional "protected degraded mode". O-12 decides what else stops or
     carries on (Phase 5).

## Consequences

- **After an outage:** the notifications raised during it reach the outbox when the
  journal is written, so the Phase 2 notifier sends them late, not never.
- **Disk:** 30 min of steps is small, a few thousand lines at most. RES-02's disk warnings
  at 80% and 90% come with the health page (Phase 5).
- **During an outage** nothing reads the database: acknowledgments, switches, windows and
  new configuration wait until it's back. They're all in the database anyway.

## Tests

- `services/monitor_core/tests/test_monitor_journal.py`:
  - every effect type survives the file exactly, in order;
  - the file's permissions;
  - a torn last line is skipped;
  - past the limit judging pauses, and resumes when the database is back.
- `test_monitor_store.py`:
  - an outage goes to the journal and is written in order;
  - a restart during an outage writes the journal before anything else;
  - a replay cut short is safe to run again: nothing is duplicated.
