# Development database (ADR-0012)

PostgreSQL 17 with pgvector, the SDD's database, for this PC. The Configuration
page keeps the register, the monitoring rules, the tag mappings and the audit log here.
Analytics works without it.

## Start and stop

Docker Desktop has to be running.

```bash
# once: a password nobody types, readable by you only (config/secrets is git-ignored)
(umask 077; mkdir -p config/secrets && python3 -c "import secrets; print(secrets.token_urlsafe(24))" > config/secrets/postgres-password)

docker compose -f deploy/dev/compose.yaml up -d      # start; restarts with Docker Desktop
docker compose -f deploy/dev/compose.yaml ps         # "healthy" when ready
docker compose -f deploy/dev/compose.yaml stop       # stop, keeping the data
```

- **Address:** `127.0.0.1:55432`, loopback only (5432 is taken on this PC).
- **Accounts:**
  - `centerline` owns the database, with the password from the file. Only
    migrations use it.
  - The api, monitor-core and the notifier connect as `centerline_app`, which can add and read
    evidence but never change it ([ADR-0020](../../docs/decisions/ADR-0020-database-roles.md)).
    Its password is in `config/secrets/postgres-app-password` (0600); the api writes it
    there on its first start, or run `python -m centerline_common.roles` from `services/`.

  These are the defaults, so `services/api/config.json` needs no `database` block.
- **Schema:** the api applies `db/migrations` when it starts, as the owner. On the first
  start it also imports `config/parameter-register.json` and the old
  `config/history/audit.jsonl`.

## What's in it

| Table | Holds |
|---|---|
| `register_version` | Every version of the parameter register |
| `config_version`, `parameter_rule` | Every rules version and its rows: a zone's, or every zone of a parameter's (ADR-0027) |
| `config_activation` | When each version took, or will take, effect |
| `audit_log` | Every configuration change, hash-chained. `SELECT audit_log_verify()` returns NULL when intact |
| `notification`, `notification_route`, `notification_delivery`, `delivery_attempt`, `routing_version` | The outbox, how each message was routed, its deliveries and every attempt, the routing versions ([ADR-0023](../../docs/decisions/ADR-0023-notifier.md)) |

History is append-only: the database refuses to change or delete it, even for the owner,
and `centerline_app` isn't allowed to try. Every table is listed with its migration in
[docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) §10.

## Notifications on this PC

The notifier ([services/notifier](../../services/notifier/README.md)) sends whatever the Connections tab
names. Until IT gives the real Teams flow and relay, run the local sink, which keeps each message
instead of sending it:

```bash
services/.venv/bin/python tools/notify-sink/notify_sink.py                     # Teams on :8025, SMTP on :2525
cd services && PYTHONPATH=common:notifier .venv/bin/python -m centerline_notifier
```

Then on Configuration → Connections → Notifications set the flow URL
`http://127.0.0.1:8025/flow?sig=dev` and the relay `127.0.0.1` port `2525`.

## Reset (development only)

This deletes every rules version, mapping, event and audit entry on this PC. On the next
start the api imports the register file and the old history again.

```bash
docker compose -f deploy/dev/compose.yaml down -v
docker compose -f deploy/dev/compose.yaml up -d
```

## Backup

Nothing backs this up yet (pgBackRest comes with the production stack, BKP-01).
Before trying anything risky, take a copy:

```bash
docker compose -f deploy/dev/compose.yaml exec -T postgres pg_dump -U centerline -Fc centerline > ~/centerline-$(date +%F).dump
```

The api tests don't touch the `centerline` database. They create databases
named `centerline_test_*` on this server and drop them afterwards.
