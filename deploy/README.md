# Centerline in Docker

The application as it will run on the control-room PC ([ADR-0030](../docs/decisions/ADR-0030-docker-stack.md)), here
on Docker Desktop for a rehearsal. It judges the **real machine** on the plant broker and reads the **real
Timebase**, on a database of its own. **Everything it writes is permanent**, as on the development setup
([ADR-0026](../docs/decisions/ADR-0026-real-app-on-the-real-machine.md)).

| Container | What it is |
|---|---|
| `proxy` | Caddy: the web app, and `/api` to the api. On **http://localhost:6040** (this PC only): plain HTTP by default ([ADR-0032](../docs/decisions/ADR-0032-docker-stack-over-http.md)), HTTPS with its own local CA when `deploy/.env` says `CENTERLINE_SCHEME=https` |
| `api` | The api (FastAPI). It migrates the database at start; it isn't published, only the proxy reaches it |
| `monitor-core` | Subscribes, read-only, to the broker saved on the Connections tab, and judges every zone. MQTT client ID `centerline-monitor-centerline-docker` |
| `notifier` | Delivers the outbox by the routing in effect |
| `postgres` | PostgreSQL 17 with pgvector, in the `centerline_pgdata` volume. Not published |
| `backup` | The backup agent ([ADR-0035](../docs/decisions/ADR-0035-backups-pg-dump.md)): a set every hour in `deploy/backups`, kept 48 hours, then the newest of each of 30 days and 12 months; the first set of each day is restored into a scratch database and checked; off-host copies once `deploy/.env` names a folder |
| `clamav` | ClamAV's clamd: the api sends it every uploaded OCAP and guidance file before keeping it ([ADR-0031](../docs/decisions/ADR-0031-ocap-library-deterministic-path.md)). Its signatures are in the `centerline_clamav-db` volume, and it updates them itself while it has the internet. Not published |

The plan's other two containers come with Phase 3: ai-worker and ollama, once the AI model is chosen (O-01).

**clamav** takes about 1 GB of memory once its signatures are loaded, which takes a minute or two after a start.
Until it answers, uploads are refused ("the malware scanner isn't answering") and nothing else waits for it.
`setup.sh` points the api at it (`"scanner"` in `deploy/config/api.json`), and adds that to an api.json made before.
On the plant network its signatures need another way in (O-24).

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
- **`deploy/.env`** (git-ignored), also written by `setup.sh`: how and where the proxy listens.
  - `CENTERLINE_SCHEME`: `http` (the default) or `https`.
  - `CENTERLINE_SITE` and `CENTERLINE_DEFAULT_SNI`, for HTTPS only: the names and address browsers use, for the
    certificate.
  - `CENTERLINE_BIND` and `CENTERLINE_PORT`: the address and port (127.0.0.1:6040 here).
  - `CENTERLINE_UID`: the owner of `deploy/config`.
  To set it up on another machine, see [the README's deployment guide](../README.md#deploy-on-another-machine).

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
http://localhost:6040 and sign in. Choose your own password, then delete the file.

**Over plain HTTP** (the default), passwords and the session cookie cross the network unencrypted: keep it to a
network you trust, for testing. If the browser still jumps to `https://localhost:6040`, it remembers the HTTPS
setup (HSTS). Clear it once at `edge://net-internals/#hsts` ("Delete domain security policies": `localhost`), or open
http://127.0.0.1:6040.

**With `CENTERLINE_SCHEME=https`**, open https://localhost:6040. The browser warns about the certificate the first
time: it's signed by the proxy's own CA. Continue, or trust that CA on this PC:

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
docker compose -f deploy/compose.yaml exec backup python -m centerline_backup now   # a backup set now, as before a migration
```

- **Restarts:** the containers restart by themselves after a crash or when Docker starts. A stopped one stays stopped.
- **Switching HTTP and HTTPS:** change `CENTERLINE_SCHEME` in `deploy/.env`, then
  `docker compose -f deploy/compose.yaml up -d proxy api` (the api sets its cookie by it).
- **Wiping:** `down -v` deletes the database, the journal and the proxy's CA. History is meant to be kept: the
  backup sets in `deploy/backups` stay, because they're a folder on the host, not a volume.

## Backups and restore

The `backup` container ([ADR-0035](../docs/decisions/ADR-0035-backups-pg-dump.md)) writes a set every hour, two
minutes past, in `deploy/backups/<UTC time>/`:
- `centerline.dump`: the database, OCAPs included;
- `globals.sql`: the roles;
- `config.tar.gz`: `deploy/config`, with its secrets;
- `manifest.json`: the checksums and the restore check.

Kept: 48 hours of sets, the newest of each of the last 30 days, and of the last 12 months.

```bash
docker compose -f deploy/compose.yaml exec backup python -m centerline_backup list   # the sets, and the last run
cat deploy/backups/status.json                                                       # last success, last error, off-host
docker compose -f deploy/compose.yaml logs backup                                    # each run in one line
```

**Off-host (O-27):** set `CENTERLINE_BACKUP_OFFHOST` in `deploy/.env` to a folder on another disk or a mounted
network share, then `docker compose -f deploy/compose.yaml up -d backup`. Each set is copied there and checked. The
sets hold every record and this PC's secrets: keep that place as restricted as `deploy/config`. Until it's set, the
status says the sets are on this PC only, and a disk failure takes them with the database.

**Restore** (a damaged database, or a new PC after a hardware failure):

```bash
deploy/restore.sh deploy/backups/20261007T120200Z            # or a set from the off-host folder
deploy/restore.sh deploy/backups/20261007T120200Z --replace  # this PC's database has records: replace them
docker compose -f deploy/compose.yaml up -d                  # then start the stack
```

It checks the set's checksums and takes `deploy/config` from the set when the PC has none. It then:
- starts only postgres;
- restores the roles and sets their passwords to this PC's secret files;
- restores the database and checks its audit chain.

It starts nothing else. On a new PC: install Docker, clone the repository, restore, check `deploy/.env`, run
`deploy/setup.sh` (it adds only what's missing), start. Everything after the set's time is lost: at most an hour.

**Restore drill (quarterly, BKP-02):** on a clean machine without the internet, restore the newest off-host set and
start the stack with monitor-core stopped (`docker compose … up -d` then `docker compose … stop monitor-core`), sign
in, and record the time from start to sign-in. On a PC with the stack running, a drill can run beside it as its own
project, which touches nothing of the running stack:

```bash
CENTERLINE_PROJECT=centerline-drill deploy/restore.sh deploy/backups/<set>   # a new, empty database server
docker compose -p centerline-drill -f deploy/compose.yaml down -v            # afterwards: only the drill's volumes
```

## What this rehearsal can't show

These wait for the control-room PC (G0b):
- **Starting without anyone signed in (DEP-05).** Docker Desktop needs a Windows session, which is why the SDD
  rejects it for production (§3).
- **The browser's real address (SES-04).** Docker Desktop hides it. The proxy sees every browser on this PC as one
  address, which the api gets through `X-Forwarded-For`.

  To let an operator sign in here for a test, add that address to `auth.operator_workstations` in
  `deploy/config/api.json` and restart the api (`docker compose … restart api`). The refusal message names it:
  "This browser (…) isn't the primary or backup operator workstation".
- **The plant LAN reaching it:** on this laptop the proxy listens on 127.0.0.1 only. `deploy/.env` opens it, as
  [the README's deployment guide](../README.md#deploy-on-another-machine) describes.
