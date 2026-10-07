# The backup agent

Backs up the Docker stack's database every hour, keeps the sets by BKP-01's policy here and off-host, and restores
the first set of each day into a scratch database to check it
([ADR-0035](../../docs/decisions/ADR-0035-backups-pg-dump.md)). It runs as the `backup` container
([deploy/compose.yaml](../../deploy/compose.yaml)). Restoring is `deploy/restore.sh`
([deploy/README.md](../../deploy/README.md#backups-and-restore)).

```bash
python -m centerline_backup              # the service: a set every hour, two minutes past
python -m centerline_backup now --check  # one set now, restored and checked
python -m centerline_backup list         # the sets here and off-host, and the last run
```

In the stack: `docker compose -f deploy/compose.yaml exec backup python -m centerline_backup list`.

## Settings

`CENTERLINE_BACKUP_CONFIG` (`deploy/config/backup.json`, written by `deploy/setup.sh`):

| Key | Meaning |
|---|---|
| `database` | The **owner** account: the roles' dump and the scratch database need it |
| `config_dir` | This host's settings and secrets, archived in each set |
| `backup_dir` | Where the sets go (`/backups` in the stack: `deploy/backups`, or `CENTERLINE_BACKUP_DIR`) |
| `keep` | `hours` (48), `days` (30), `months` (12) |

`CENTERLINE_OFFHOST` is the off-host folder. The stack sets it to `/offhost` only when `deploy/.env` names
`CENTERLINE_BACKUP_OFFHOST`.

## A set

`<UTC time>/`: `centerline.dump` (pg_dump, custom format), `globals.sql` (the roles), `config.tar.gz`
(`deploy/config`), `manifest.json` (sizes, SHA-256, the restore check). `status.json` beside the sets says how
the last run went.

## Tests

`cd services && .venv/bin/python -m pytest backup_agent/tests`: no database needed, because PostgreSQL's tools are
replaced by fakes.
