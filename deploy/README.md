# Centerline in Docker

The application as it will run on the control-room PC ([ADR-0030](../docs/decisions/ADR-0030-docker-stack.md)), here
on Docker Desktop for a rehearsal. It judges the **real machine** on the plant broker and reads the **real
Timebase**, on a database of its own. **Everything it writes is permanent**, as on the development setup
([ADR-0026](../docs/decisions/ADR-0026-real-app-on-the-real-machine.md)).

| Container | What it is |
|---|---|
| `proxy` | Caddy: HTTPS with its own local CA, the web app, `/api` to the api. On **https://localhost:8443** (this PC only) |
| `api` | The api (FastAPI). It migrates the database at start; it isn't published, only the proxy reaches it |
| `monitor-core` | Subscribes, read-only, to the broker saved on the Connections tab, and judges every zone. MQTT client ID `centerline-monitor-centerline-docker` |
| `notifier` | Delivers the outbox by the routing in effect |
| `postgres` | PostgreSQL 17 with pgvector, in the `centerline_pgdata` volume. Not published |

The plan's other four containers come with their phases: ai-worker, ollama and clamav (Phase 3), backup-agent
(Phase 5).

## Start

```bash
deploy/setup.sh                                       # once: deploy/config, seeded from config/
docker compose -f deploy/compose.yaml up -d --build
```

- **`deploy/config`** (git-ignored, 0700) is this host's settings and secrets, mounted at `/app/config`. It holds
  the three services' settings (`api.json`, `monitor-core.json`, `notifier.json`) and the connections the
  Configuration page saves. It also holds the register's export, the Analytics query log (`logs/`), and the
  `secrets/` folder.
- `setup.sh` copies the register, the plant connections with the secrets they name, and the old history from
  `config/`. It makes a new database password; the api makes the services' role password at its first start. It
  never overwrites a file.

**One monitor-core judges the line at a time.** Before starting this stack's `monitor-core` and `notifier`, stop the
development ones started from a terminal (Ctrl+C in their terminals). Two would record every alarm twice, in two
databases.

## The first sign-in

The database starts empty. Create the owner's account once, on the server's command line:

```bash
docker compose -f deploy/compose.yaml exec api python -m centerline_api.auth create-admin \
    --username szyrelle --name "Szyrelle" --out /app/config/secrets/first-admin-password
```

The temporary password is in `deploy/config/secrets/first-admin-password` and works for 24 h. Open
https://localhost:8443 and sign in. Choose your own password, then delete the file.

The browser warns about the certificate the first time: it's signed by the proxy's own CA. Continue, or trust that
CA on this PC:

```bash
docker compose -f deploy/compose.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt deploy/config/centerline-ca.crt
```

Then import `deploy/config/centerline-ca.crt` into Windows: certmgr.msc → Trusted Root Certification Authorities.

Then configure it as on the development setup:
- the mapping (Configuration → Mappings, fill from the broker);
- the rules, the routing, the Analytics ranges.

Or carry everything over, as below.

## Carry the development database over (instead of starting empty)

Only while this stack's database is still new: the first command deletes it.

```bash
docker compose -f deploy/compose.yaml down -v
docker compose -f deploy/compose.yaml up -d postgres
docker compose -f deploy/compose.yaml exec -T postgres psql -U centerline -d centerline -c "CREATE ROLE centerline_app LOGIN"
docker exec centerline-dev-postgres-1 pg_dump -U centerline -Fc centerline \
  | docker compose -f deploy/compose.yaml exec -T postgres pg_restore -U centerline -d centerline
docker compose -f deploy/compose.yaml up -d
```

The api then applies the migrations the copy lacks. The accounts, configuration, events and audit chain come with it
(tested on 2026-10-06). From then on the two databases go their own ways.

## Day to day

```bash
docker compose -f deploy/compose.yaml ps                    # what runs, and the health checks
docker compose -f deploy/compose.yaml logs -f monitor-core  # any service's log
docker compose -f deploy/compose.yaml stop                  # stop everything; data stays
docker compose -f deploy/compose.yaml up -d --build         # after a code change: rebuild and restart
(umask 077; docker compose -f deploy/compose.yaml exec -T postgres pg_dump -U centerline -Fc centerline \
   > config/history/centerline-docker-$(date +%F).dump)              # a backup, 0600
```

- **Restarts:** the containers restart by themselves after a crash or when Docker starts. A stopped one stays stopped.
- **Wiping:** `down -v` deletes the database, the journal and the proxy's CA. History is meant to be kept: back
  it up first.

## What this rehearsal can't show

These wait for the control-room PC (G0b):
- **Starting without anyone signed in (DEP-05).** Docker Desktop needs a Windows session, which is why the SDD
  rejects it for production (§3).
- **The browser's real address (SES-04).** Docker Desktop hides it. The proxy sees every browser on this PC as one
  address, which the api gets through `X-Forwarded-For`.

  To let an operator sign in here for a test, add that address to `auth.operator_workstations` in
  `deploy/config/api.json` and restart the api (`docker compose … restart api`). The refusal message names it:
  "This browser (…) isn't the primary or backup operator workstation".
- **The plant LAN reaching it:** the proxy listens on 127.0.0.1 only.
