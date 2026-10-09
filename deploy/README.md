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

The local AI, Ollama, isn't one of them: the api asks the Ollama that `CENTERLINE_OLLAMA_URL` in `deploy/.env` names,
another container, here or on another machine ([ADR-0050](../docs/decisions/ADR-0050-ollama-outside-the-stack.md);
[The AI model](#the-ai-model) below).

**clamav** takes about 1 GB of memory once its signatures are loaded, which takes a minute or two after a start.
Until it answers, uploads are refused ("the malware scanner isn't answering") and nothing else waits for it.
`setup.sh` points the api at it (`"scanner"` in `deploy/config/api.json`), and adds that to an api.json made before.
On the plant network its signatures need another way in (O-24).

## Start

```bash
deploy/setup.sh                                       # once: deploy/config, seeded from config/
deploy/compose.sh up -d --build
```

**`deploy/compose.sh`** is `docker compose -f deploy/compose.yaml`, plus `deploy/compose.sim.yaml` when `deploy/.env`
has `CENTERLINE_SIMULATOR=on` (away from the plant only) ([ADR-0049](../docs/decisions/ADR-0049-production-runs-the-laptops-stack.md)).
Use it for every command, so nothing brings the simulator onto the line. The commands below written as
`docker compose -f deploy/compose.yaml …` work the same through it.

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
  - `CENTERLINE_OLLAMA_URL`: the Ollama the AI asks ([ADR-0050](../docs/decisions/ADR-0050-ollama-outside-the-stack.md)); empty, no AI.
  - `CENTERLINE_SIMULATOR`: `on` only away from the plant; `off` on the line.
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
deploy/compose.sh ps                    # what runs, and the health checks
deploy/compose.sh logs -f monitor-core  # any service's log
deploy/compose.sh stop                  # stop everything; data stays
deploy/compose.sh up -d --build         # after a code change: rebuild and restart
deploy/compose.sh exec backup python -m centerline_backup now   # a backup set now, as before a migration
```

- **Restarts:** the containers restart by themselves after a crash or when Docker starts. A stopped one stays stopped.
- **After an update,** browsers get the new page on their next reload: the page is never cached, its files (named by
  their content) always are. A tab left open keeps the version it loaded until it's reloaded.
- **System health** ([ADR-0038](../docs/decisions/ADR-0038-system-health-page.md)): Administrators open **System health**
  (under Setup) for every part graded at once, with what to do. The api reads `deploy/backups/status.json` read-only.
- **Storage (RES-02, [ADR-0036](../docs/decisions/ADR-0036-storage-degraded-mode-and-at07.md)):** monitor-core measures the disk
  under the database's volume every minute. Every page shows a banner from 80 %, and in protected degraded mode (90 %
  for 10 min, ending below 85 %) uploads are refused. Each container's log is capped at 3 × 10 MB. To see the reading:
  `docker compose -f deploy/compose.yaml exec postgres psql -U centerline -d centerline -Atc "SELECT status->'storage' FROM monitor_heartbeat"`.
- **Switching HTTP and HTTPS:** change `CENTERLINE_SCHEME` in `deploy/.env`, then
  `docker compose -f deploy/compose.yaml up -d proxy api` (the api sets its cookie by it).
- **Wiping:** `down -v` deletes the database, the journal and the proxy's CA. History is meant to be kept: the
  backup sets in `deploy/backups` stay, because they're a folder on the host, not a volume.

## The AI model

The api asks an Ollama outside this stack: the one `CENTERLINE_OLLAMA_URL` in `deploy/.env` names
([ADR-0050](../docs/decisions/ADR-0050-ollama-outside-the-stack.md)), over `ai.url` in `deploy/config/api.json`. After a
change: `deploy/compose.sh up -d api`. On another machine: `http://<its address>:11434`; on this one:
`http://host.docker.internal:<port>` (the api resolves it to this host, on Linux too).

That Ollama needs the models `qwen3.5:4b` (3.3 GB) and `bge-m3` (1.2 GB, the OCAP search by meaning, ADR-0048), with
`OLLAMA_CONTEXT_LENGTH=4096`, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_NUM_PARALLEL=1` and
`OLLAMA_NO_CLOUD=true`, a GPU, and a port only Centerline reaches (Ollama has no password). **`deploy/ollama/`** runs one
with those settings, as its own Compose project (`ollama`), where none runs yet:

```bash
docker compose -f deploy/ollama/compose.yaml -f deploy/ollama/compose.gpu.yaml up -d   # the GPU file: an NVIDIA GPU
docker compose -f deploy/ollama/compose.yaml exec ollama ollama pull qwen3.5:4b
docker compose -f deploy/ollama/compose.yaml exec ollama ollama pull bge-m3
```

`deploy/ollama/.env` (git-ignored) says where it listens: `OLLAMA_BIND` (127.0.0.1 by default; 172.17.0.1, the Docker
bridge, on Linux) and `OLLAMA_PORT` (11434), and `OLLAMA_VOLUME`, the models' volume. The owner's laptop runs it on
127.0.0.1:11435 with the models of the stack's earlier `centerline_ollama` volume.

The full digests, for `ai.model_digest` and `ai.embed_model_digest` in `deploy/config/api.json`:

```bash
deploy/compose.sh exec api python -c "import json, os, urllib.request; [print(m['name'], m['digest']) for m in json.load(urllib.request.urlopen(os.environ['CENTERLINE_OLLAMA_URL'] + '/api/tags'))['models']]"
```

- **On the GPU:** the Ollama's own. Docker reaches the GPU on Linux with the NVIDIA driver and the NVIDIA Container
  Toolkit, on Windows through WSL2 with the NVIDIA driver. System health says how much of the model is on the GPU, and
  warns when none of it is, when Ollama isn't answering, and when no URL is set.
- **Pinned:** a model whose digest isn't the pinned one isn't used (`ollama list` shows only the first 12 characters).
  After changing them: `deploy/compose.sh restart api`.
- **Kept warm:** `ai.warm_every_s` (60) has the api reload the model after a restart, so a first question doesn't wait
  for it to load (over a minute on a 4 GB GPU).
- **Opening questions:** `ai.open_every_s` (2) has the api write each new request's first question from the OCAP
  ([ADR-0042](../docs/decisions/ADR-0042-ai-opens-the-conversation.md)).
- **The OCAP search by meaning:** with `ai.embed_model` (bge-m3) pulled, the api embeds the Active OCAPs' sections
  (`ai.embed_every_s`, 10) and a search finds a section by what a Taglish reason means, merged with the keyword search
  ([ADR-0048](../docs/decisions/ADR-0048-ocap-search-by-meaning.md)). Not pulled, or slow: keywords alone.
- **The summary of the OCAP sections offered:** `ai.summary_every_s` (2) has the api sum up each request's sections
  once they're offered, shown above them only when it's grounded in them
  ([ADR-0046](../docs/decisions/ADR-0046-ai-summary-of-the-ocap.md)).
- **The OCAP in Tagalog by the AI:** `ai.translate_every_s` (20; 0 switches it off) has the api translate one more
  section of the Active OCAPs in English, while no operator is answering; each takes 20–60 s on a 4 GB GPU (`ai.translate_timeout_s`, 180). A translation
  that changes a number or an instruction word is kept out, and that section stays English
  ([ADR-0045](../docs/decisions/ADR-0045-ai-translates-the-ocap.md)). The OCAP's page shows how far it got.
- **Off, slow or wrong,** operators get the fixed questions; System health says why.

## Away from the plant: simulated data

Off the plant network the broker and Timebase can't be reached. To keep testing, `deploy/compose.sim.yaml` adds a
local MQTT broker (`sim-broker`, on the stack's network only) and the simulator (`tools/mqtt-sim`), which publishes
Volpak-shaped data on the plant's topics and fields: steady values, a short setpoint change every 5 min, a mismatch
nobody puts back every 10 min (for 15 min), and an actual value leaving its band every 15 min.

Set `CENTERLINE_SIMULATOR=on` in `deploy/.env`, then:

```bash
deploy/compose.sh up -d sim-broker sim
```

Then the saved broker is `sim-broker`, port 1883, no TLS, no account: on the Connections tab, or in
`deploy/config/connections.json` (monitor-core and the api pick the file up by themselves). Keep the plant's settings
first, as `deploy/config/connections.plant.json`. The simulator's setpoints are Vertical 1–6 at 220, 215, 215, 220,
214, 214 °C, Bottom at 180, Top at 185, the nozzles at 98 and Pressure at 1.3: Rules targets other than these show as
HMI mismatches on every zone. In the Rules editor, **Fill empty targets from current HMI setpoints** takes them
from monitor-core's live values (the Tags and Rules tabs prefer those to Timebase's, at the plant too).

Everything monitor-core judges goes into the stack's database as if it were real. Back at the plant:

```bash
deploy/compose.sh rm -sf sim sim-broker
cp -p deploy/config/connections.plant.json deploy/config/connections.json   # or save the plant broker on the Connections tab
```

and set `CENTERLINE_SIMULATOR=off` in `deploy/.env`.

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

**The offline install kit** ([ADR-0037](../docs/decisions/ADR-0037-offline-install-kit.md)). A new PC also needs the images,
and building them needs the internet. The kit carries them, with ClamAV's signatures and the repository:

```bash
deploy/kit.sh make            # after each release (commit first): deploy/backups/kits/, the two newest kept, copied off-host
deploy/kit.sh verify <kit>    # its checksums and archives
deploy/kit.sh load <kit>      # on the new PC: the images and ClamAV's signatures
```

A kit is about 600 MB and holds no secrets. Its `RESTORE.md` is the whole restore on a PC without the internet:
Docker and git, `git clone <kit>/centerline.bundle`, `kit.sh load`, `restore.sh`, then `up -d` **without** `--build`.

**Restore drill (quarterly, BKP-02):** on a clean machine without the internet, follow the newest kit's `RESTORE.md` with the newest off-host set and
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
