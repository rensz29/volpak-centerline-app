# ADR-0035: Backups: an hourly pg_dump set, kept here and off-host, with a daily restore check

- **Status:** Accepted
- **Date:** 2026-10-07
- **Decider:** Szyrelle (system owner), on 2026-10-07. Asked how to back up the database, the owner chose "pg_dump
  hourly" over the SDD's pgBackRest. Asked where the off-host copies go until IT names a place, the owner chose a
  path set in `deploy/.env`.
- **Amends:** the SDD §13 and [ARCHITECTURE §13](../ARCHITECTURE.md#13-reliability-backup-and-operations)
  (pgBackRest: daily full, hourly incremental, continuous WAL)
- **URS:** BKP-01, BKP-02, DEP-02 (no internet), RET-01 (what is kept)

## Context

- Nothing backed the database up. The Docker stack's database is real, permanent history (ADR-0030), and a backup
  was a `pg_dump` someone remembered to run.
- BKP-01:
  - back the database up hourly (incrementally) and daily (in full);
  - back the OCAPs up daily and after each activation;
  - keep 30 daily and 12 monthly copies off-host.
- BKP-02: data loss at most 1 hour (RPO), back in 4 hours (RTO), and a full restore tested quarterly without the
  internet.
- **The database is about 10 MB.** The OCAPs and guidance files are in it (`bytea`, ADR-0031), so backing up the
  database backs them up too, after every activation included. A restore also needs:
  - the roles: a database dump doesn't carry them;
  - this host's settings and secrets in `deploy/config`.
- **pgBackRest, as the SDD planned, needs:**
  - a database image of our own;
  - WAL archiving switched on, with a restart of the permanent database;
  - a second container sharing the data volume.

  Its retention counts full backups, so "30 daily and 12 monthly" would still be scripted around it.

## Decision

1. **A backup agent** (`services/backup_agent`, the `backup` container) writes **one backup set every hour**,
   two minutes past the hour (UTC), and one at start when the last set is older than 55 minutes. A set is a folder
   named by its UTC time:

   | File | What it is |
   |---|---|
   | `centerline.dump` | The whole database: `pg_dump`'s custom format, compressed. The OCAPs and files are in it |
   | `globals.sql` | The roles (`pg_dumpall --globals-only`) |
   | `config.tar.gz` | `deploy/config`: the settings and secrets a restore needs to start |
   | `manifest.json` | Each file's size and SHA-256, the server's version, and the restore check's result |

   Every set is a full copy, so "incremental" in BKP-01 is met by a full set each hour: an hour's loss at most.

   A set is written as `<name>.partial` and renamed when complete, so a half-written set never counts as a backup.
2. **Kept:**
   - every set from the last 48 hours;
   - the newest set of each of the last 30 days;
   - the newest set of each of the last 12 months;
   - always the newest set, whatever its age.

   Days and months are UTC. Older sets, and the remains of interrupted runs, are deleted after each run.
3. **The first set of each UTC day is restored and checked:**
   - restored into a scratch database (`centerline_restore_check`) on the same server;
   - its tables are counted;
   - its audit chain is verified (`audit_log_verify()`);
   - then the scratch database is dropped.

   A set whose check fails is kept, because it may be the newest copy there is, and the failure goes in its manifest
   and in the status.
4. **Off-host:** when `deploy/.env` names `CENTERLINE_BACKUP_OFFHOST` (a folder on another disk, or a mounted
   network share), each set is copied there, its checksums are verified, and the same retention applies. A failed
   copy, such as a share that isn't mounted, fails the run's status but not the local backup. Until a folder is named,
   the status says the sets are on this PC only.
5. **`status.json`** in the backup folder records:
   - the last attempt and the last success;
   - the last error;
   - the last restore check;
   - the off-host state.

   `python -m centerline_backup list` shows every set. The health page reads this file when it is built.
6. **The agent runs as the database owner.** `pg_dumpall` and the scratch database need it. It mounts `deploy/config`
   read-only and is published nowhere. The sets go to `deploy/backups` (or `CENTERLINE_BACKUP_DIR`) on the host,
   0700, so they outlive the stack's volumes (`down -v`).
7. **Restore: `deploy/restore.sh <set> [--replace]`.** It:
   - checks the set's checksums;
   - takes `deploy/config` from the set when the PC has none;
   - starts only postgres and refuses a database that already has records, unless `--replace`;
   - restores the roles, then sets their passwords to this PC's secret files;
   - restores the database and checks its audit chain.

   It starts nothing else, so a second monitor-core never judges the line by surprise. It uses the postgres
   container's own tools: nothing to install, nothing from the internet.

## Consequences

- RPO is one hour, and RTO is far below four: the 2026-10-07 drill on this laptop restored the database onto a new
  server in 6 seconds, with the audit chain intact and both roles signing in with this PC's passwords.
- **A restore loses at most the last hour.** The SDD's continuous WAL would lose minutes. pgBackRest can replace the
  agent later, if the database grows past what an hourly full dump handles or minutes matter; the sets'
  layout and `restore.sh` would change with it.
- **The sets hold every record and this PC's secrets:**
  - the backup folder is this user's only (0700);
  - the off-host place must be as restricted;
  - the sets aren't encrypted: whether IT wants that is part of O-27.
- **Disk:** a set is about 0.2 MB today, and about 90 sets are kept. RES-02's storage limits (O-12) will count the
  backup folder.
- **New:** O-27, the off-host place: IT names it, and restricts it. The services image gains PostgreSQL 17's client
  tools.
- **Still to come for BKP-02 and G5:**
  - the quarterly drill on a clean, offline machine (deploy/README.md, "Restore drill");
  - the offline install kit (the images' archives) kept with the backups;
  - the health page's "last successful backup".

## Tests

- `services/backup_agent/tests` (12 tests):
  - what a set holds, and that a half-written one never counts;
  - the retention over 500 days of hourly sets;
  - the daily restore check, and a set whose check fails;
  - a failed dump;
  - the off-host copy, and a share that isn't mounted;
  - the settings.
- On the Docker stack, 2026-10-07:
  - the first set (0.2 MB in 2.3 s), its restore check (46 tables, audit chain intact) and an off-host copy;
  - `restore.sh` into a separate Compose project (`centerline-drill`) with an empty volume: 6 s, audit chain intact,
    both roles signing in;
  - the project removed afterwards.
