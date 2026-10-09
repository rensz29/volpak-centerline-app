# ADR-0036: Storage limits, protected degraded mode, and the AT-07 acceptance suite

- **Status:** Accepted
- **Date:** 2026-10-07
- **Decider:** Szyrelle (system owner), on 2026-10-07. Asked what stops in protected degraded mode (O-12), the owner
  chose the SDD's proposal:
  - carry on: monitoring, events, the reason workflow, notifications and backups;
  - stop: brief-change records, the Analytics query log and new uploads;
  - an Administrator alert every hour and a banner on every page until storage is under 85 %.
- **Closes:** O-12
- **URS:** RES-02, and AT-07 for DEP-02, DEP-03, DEP-05, RES-01, RES-02, MNT-02

## Context

- RES-02:
  - warn at 80 % storage;
  - run the eligible cleanup at 90 %;
  - enter protected degraded mode if that doesn't resolve it;
  - never silently delete a protected record.

  Nothing watched the disk.
- AT-07 asks for offline core operation, buffer replay, storage degraded mode and restart recovery. Most of the behaviour
  was built and unit-tested: the disk journal and its replay (ADR-0018), restarts that keep open events and repeat
  no first notice (ADR-0014). There was no acceptance suite.
- Of what RES-01 retention lets go, most already cleans itself:
  - idempotency keys after 24 h (ADR-0028);
  - ended sessions;
  - backup sets past their policy (ADR-0035).

  Container logs, though, grew without limit.

## Decision

1. **monitor-core watches the disk** under its journal, which is the disk of the database's volume. It reads it every
   minute; `storage_paths` in its settings adds others, and the fullest counts. The states:

   | State | Enters at | Leaves |
   |---|---|---|
   | normal | | |
   | warning | 80 % | below 78 % |
   | cleanup | 90 %: the backup agent runs the eligible cleanup | below 90 % |
   | degraded | still 90 % or more 10 min after reaching it | below 85 % (the owner's choice) |

   The state, the disk's use, since when, and the brief changes skipped go in the heartbeat. A disk it can't read is
   reported, not treated as full.
2. **Alerts** go to the routing's system recipients:
   - one on entering warning, cleanup or degraded;
   - one every hour while degraded;
   - one when degraded mode ends.

   They are monitor-core's outbox rows, so they wait in the journal if the database is away.
3. **The eligible cleanup:** the backup agent reads the state every minute. Once per episode of cleanup or degraded it:
   - deletes the backup sets past their policy, here and off-host;
   - deletes the idempotency keys past their 24 hours;
   - writes an audit entry saying what went (`storage.cleanup`), and nothing protected.
4. **Protected degraded mode (O-12):**
   - monitor-core doesn't write brief-change records. They're lightweight rows, not evidence, and it counts what it
     skipped.
   - The api refuses new OCAP files and guidance files, with the problem `507 storage-full`. A guidance's text
     without a file still goes through.
   - The api doesn't write the Analytics query log.
   - Monitoring, events, the reason workflow, notifications and backups carry on.
5. **A banner on every page**, from the event counts every page already polls:
   - amber from 80 %;
   - amber with the time degraded mode would begin at 90 %;
   - red in degraded mode, saying what is paused and what isn't.

   Without a fresh heartbeat the state is unknown and nothing is refused.
6. **Container logs are rotated:** at most 3 files of 10 MB each, for every container (`deploy/compose.yaml`). They're
   bounded, not cleaned up.
7. **AT-07** (`tests/acceptance/test_at07_resilience.py`) drives the real components as the other suites do:
   - **DEP-02, DEP-03:** with Timebase out of reach, no notifier and no AI, monitor-core judges a mismatch with no api
     call. The operator signs in locally and runs the reason workflow to the end, the OCAP library answers, the audit
     chain holds, and the notice waits in the outbox.
   - **RES-01:**
     - an outage journals the steps to a file only monitor-core's user can read;
     - replay writes them in order;
     - a replay cut short runs again without a duplicate;
     - past 30 min judging pauses and nothing judged is lost.
   - **RES-02:** the states, the refused uploads, the paused query log and brief changes, monitoring carrying on, the
     alerts, and recovery below 85 %.
   - **MNT-02:** after a restart open events carry on, delays start from zero, and no first notice is sent twice.
   - **DEP-05** is skipped: it needs the control-room PC (the host test, G0b).

## Consequences

- AT-07 passes, except DEP-05, which waits for the control-room PC with G0b.
- **What is measured is the disk Docker's volumes live on:**
  - On the control-room PC's Linux VM, that's the one disk.
  - On Docker Desktop, the backup folder (on the WSL disk) is another; `storage_paths` adds it if wanted.
- **A restart re-enters the states from normal,** so a disk still at 90 % gets ten more minutes of cleanup before
  degraded mode returns, and the alerts are sent again.
- Retention's purge of old protected records (RET-01/02, legal hold) is still to come. Until then the cleanup removes
  nothing protected because nothing protected is eligible.
- The health page will show the same state when it's built.

## Tests

- `services/monitor_core/tests/test_monitor_storage.py`: the states and their limits, the hourly repeat, recovery,
  the fullest disk, an unreadable disk, a state's start time, and brief changes stopping only while degraded.
- `services/backup_agent/tests`: the cleanup removes only what's past its policy, and audits it.
- `tests/acceptance/test_at07_resilience.py`: as decision 7. With the rest of the suite, everything passes. One older
  monitor-core test (`test_a_replay_cut_short_is_safe_to_run_again`) failed once in three full runs, with its journal
  file missing; it passes alone and in the other runs. It's left to investigate.
- On the Docker stack, 2026-10-07:
  - the heartbeat reports the data disk at 9.1 %, state normal;
  - every container's log rotates at 3 × 10 MB.
