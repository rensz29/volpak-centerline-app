# ADR-0038: The System health page

- **Status:** Accepted
- **Date:** 2026-10-07
- **Decider:** Szyrelle (system owner), on 2026-10-07: "okay go ahead", for the health page recommended after the
  offline kit
- **URS:** AVL-01, PER-01, RES-01, RES-02, BKP-01/02, SEC-01; SDD §13 (Observability)

## Context

- The SDD's §13 asks for an Administrator health page showing:
  - the broker connection and the age of each area's last message;
  - the machine clocks' skew;
  - the evaluation latency;
  - the outbox's depth and its oldest message;
  - the journal size;
  - disk use;
  - the last successful backup.
- Most of it was already reported, but scattered: monitor-core's and the notifier's heartbeats, the backup agent's
  `status.json`, clamd. An Administrator-only `GET /api/v1/health` gave the raw readings, and no page used them.
- Evaluation latency and the journal's backlog weren't measured anywhere.

## Decision

1. **monitor-core measures two more things** and puts them in its heartbeat:
   - `evaluation`: the longest time a message waited from its arrival to the end of its judging over the last minute,
     against PER-01's 2 s, and how many messages there were;
   - `journal`: the steps waiting in the disk journal, and since when.
2. **`GET /api/v1/health` grades every part** (`centerline_api/health.py`, a pure function of the readings). Each check
   is OK, warning, critical or not measured, with a summary saying what is wrong and what to do, and a link where
   there's somewhere to act. The overall state is the worst of them. The fields it returned before stay.

   | Area | Checks |
   |---|---|
   | Monitoring | monitor-core running; judging or paused (with the reasons); the plant broker; each area's last message against its freshness limit; the machine clocks; time to judge (2 s); the disk journal |
   | Notifications | the notifier running; Teams and email set, and their last delivery; the outbox (failed for good; waiting over 15 min) |
   | Storage and backups | the disk (ADR-0036's states); the last good backup (late after 75 min, critical after 3 h); the daily restore check; the off-host copy (O-27) |
   | Database | reachable, and its size; the audit chain |
   | Uploads and history | clamd answering, and its signatures' age (stale after 7 days, O-24); Timebase reachable |

   What a stopped monitor-core last reported isn't graded: only that it isn't running.
3. **The api reads the backup agent's `status.json`** through a read-only mount of the backup folder
   (`backup_status` in `api.json`, added by `deploy/setup.sh`). It asks clamd for its version, which carries the
   signatures' date. Without a backup status configured, as on a development PC, backups show "not measured".
4. **The System health page** (`/health`), for Administrators, under Setup:
   - a verdict first, listing every critical check and warning, each linking to its row;
   - then each area's checks with their state, summary and link;
   - it refreshes every 15 s while visible, and "Check now" runs at once.

## Consequences

- An Administrator sees in one place what was in four logs and two files, graded the same way every time.
- The grading's limits (75 min, 3 h, 26 h, 15 min, 7 days, 2 s) are code (`health.py`), not settings. They follow
  the hourly backups, the daily restore check, the notifier's retries, PER-01 and freshness on the plant network.
- The page shows what each part reports about itself. A part that can't report (no heartbeat, no status file) shows
  as not running or not measured, never as fine.
- Container health (Docker's own checks) isn't on the page: the api has no access to Docker, and shouldn't.

## Tests

- `services/api/tests/test_health_unit.py`: a healthy plant all OK; then each fault:
  - monitor-core stopped or never run;
  - a silent area, a lost broker, a slow judge, a waiting journal;
  - each storage state;
  - late, missing and unchecked backups, and backups only on this PC;
  - unset or failing channels, and a stuck outbox;
  - old signatures, a silent scanner, a broken audit chain, no Timebase.
- `services/api/tests/test_health_api.py`: the endpoint without monitor-core, with its heartbeat, and for Managers
  (refused).
- `services/monitor_core/tests/test_monitor_storage.py`: the time to judge over the last minute.
- On the Docker stack, 2026-10-07, the endpoint graded the live system:
  - critical: the broker isn't reachable from this network;
  - warnings: no rules or mapping in effect on this database, Teams and email not set, backups on this PC only, Timebase out of reach;
  - OK: monitor-core and the notifier, the disk at 9.1 %, a backup 72 s old, the restore check, the audit chain,
    clamd's signatures of the day before.
- The page was checked in headless Edge with that report as its data.
- Of the full suite, AT-ANA-07 failed once and passed in two later runs of the acceptance suites. It's intermittent,
  like the monitor-core journal test noted in ADR-0036, and unrelated to this change.
