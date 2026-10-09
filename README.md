# Digital Centerline: monitoring and OCAP assistance for the Volpak line

Centerline watches the Volpak filler's setpoints and actual values, raises an event when they leave the
centerline, asks the shift's operator why, and tells Management. A local AI asks the operator about the change and
points to the plant's OCAP, in Tagalog or English. Centerline also correlates history from the Timebase historian. It
is read-only to the plant: it subscribes to the MQTT broker and only reads Timebase.

The design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), which restates the System Design Document. Every
decision taken since is an ADR in [docs/decisions/](docs/decisions/README.md); where an accepted ADR settles
something, it is authoritative. Phase 0 progress is tracked in [docs/phase-0.md](docs/phase-0.md).

## Repository

| Folder | What it holds |
|---|---|
| [client/](client/README.md) | The web app: React, TypeScript, Vite |
| [services/api/](services/api/README.md) | The api (FastAPI): sign-in, configuration, live monitoring, alarms, reasons, the OCAP library, notifications, Analytics |
| [services/monitor_core/](services/monitor_core/README.md) | monitor-core: subscribes to the broker, judges every zone, writes events and the outbox |
| [services/notifier/](services/notifier/README.md) | The notifier: delivers the outbox to Teams and email |
| [services/backup_agent/](services/backup_agent/README.md) | The backup agent: an hourly set of the database, roles and settings, kept here and off-host, checked by a daily restore |
| `services/common/` | Code the services share, with no web framework in it |
| `db/` | Plain SQL migrations, applied in order by the api, and the seed proposals |
| [deploy/](deploy/README.md) | The application in Docker: `compose.yaml` and `compose.sh` to run it, the images, the proxy's Caddyfile, `setup.sh`, `restore.sh`, the offline kit (ADR-0030, ADR-0049) |
| [deploy/dev/](deploy/dev/README.md) | The development database: PostgreSQL 17 with pgvector, in Docker |
| [deploy/host-check/](deploy/host-check/README.md) | Checks for the control-room PC (G0b) |
| `config/` | The parameter register. Connection settings, secrets and backups stay here too, git-ignored |
| `tools/` | Phase 0 probes and analyses, the MQTT simulator and a local stand-in for Teams and SMTP |
| [tests/acceptance/](tests/acceptance/README.md) | The URS acceptance suites the phase gates run: AT-04…06 for G2, AT-08 for G3 (with the AI running and stopped), AT-ANA-01…10 for G4, AT-07 for G5 |
| [tests/fixtures/analytics/](tests/fixtures/analytics/README.md) | The Analytics reference dataset and its independently calculated results |

## Run it on a development PC

1. Start the database: [deploy/dev/README.md](deploy/dev/README.md).
2. Start the api, and create the first Administrator: [services/api/README.md](services/api/README.md#run).
3. Start the web app: `cd client && npm install && npm run dev`, then open <http://localhost:5173>.
4. To judge a line, run monitor-core and the notifier: [services/monitor_core/README.md](services/monitor_core/README.md)
   and [services/notifier/README.md](services/notifier/README.md). With their default settings they judge the real
   machine on the plant broker and write to the real database, where everything is permanent
   ([ADR-0026](docs/decisions/ADR-0026-real-app-on-the-real-machine.md)). To develop or test, point them at a local
   Mosquitto fed by [tools/mqtt-sim](tools/mqtt-sim/README.md) and a scratch database instead.

## Install in production, step by step

Production is the Docker stack on one server: seven containers, the proxy (the web app), the api, monitor-core, the
notifier, PostgreSQL, ClamAV and the backup agent ([ADR-0030](docs/decisions/ADR-0030-docker-stack.md),
[ADR-0049](docs/decisions/ADR-0049-production-runs-the-laptops-stack.md)). **The local AI, Ollama, isn't part of it:** it's
another container, provided apart, and `deploy/.env` gives its URL ([ADR-0050](docs/decisions/ADR-0050-ollama-outside-the-stack.md)).
The owner's laptop runs the same setup and is the reference. It judges the real machine on the plant broker and reads
Timebase; everything it writes is permanent history. More detail on each part: [deploy/README.md](deploy/README.md).

There are two ways in:
- **A. Move from the PC that runs it now:** the accounts, the configuration and the history come along.
- **B. Start empty:** you create the first account and configure everything.

Without internet on the server, the offline kit carries the images (step 3).

> **Before go-live:** the host test ([deploy/host-check](deploy/host-check/README.md), gate G0b) and the Timebase
> admin's confirmation that Timebase refuses writes (M7, [ADR-0021](docs/decisions/ADR-0021-g0b-revised.md)); HTTP or HTTPS
> (O-25); a place for off-host backups (O-27). **One monitor-core judges the line at a time:** two would record every
> alarm twice, in two databases.

### 1. The server

| | Needs |
|---|---|
| **System** | Ubuntu Server 24.04 LTS, or another Linux that runs Docker Engine. On Windows: a Hyper-V VM, or WSL2 ([ADR-0003](docs/decisions/ADR-0003-host-runtime.md)). Docker Desktop needs someone signed in to Windows: a trial only |
| **Memory** | 8 GB: ClamAV takes about 1 GB. More where the Ollama runs on this server too (its models about 5 GB) |
| **Disk** | 20 GB free: the images, the database and its backups |
| **Network** | A fixed address. It reaches the plant broker (10.156.116.176:1883), Timebase (10.156.116.179:4516) and the Ollama (step 7); the operators' and Managers' browsers reach it on port 6040; the Teams flow and the SMTP relay once IT gives them (O-05) |
| **Internet** | To build the images, or none, with the offline kit |
| **The Ollama** | Provided apart (step 7): with an NVIDIA GPU where it runs (8 GB holds the chat model whole; 4 GB, as on the owner's laptop, half of it) |

### 2. Docker

Install Docker Engine with the Compose plugin ([docs.docker.com/engine/install](https://docs.docker.com/engine/install/))
and git. Check:

```bash
docker version && docker compose version
```

### 3. The code

**With internet.** On the PC where the code is developed, commit and push what you're deploying. Then, on the server:

```bash
git clone https://github.com/rensz29/volpak-centerline-app.git centerline
cd centerline
```

**Without internet: the offline kit** ([ADR-0037](docs/decisions/ADR-0037-offline-install-kit.md)). On the PC that runs it
now, after a commit, `deploy/kit.sh make` writes a kit in `deploy/backups/kits/`: the images, ClamAV's signatures and
the repository. Copy the kit folder to the server, then:

```bash
git clone <kit>/centerline.bundle centerline
cd centerline
deploy/kit.sh load <kit>          # checks every file, then loads the images and the signatures
```

### 4. The data and the settings

**A. Moving.** On the PC that runs it now, stop the judging, then take a last backup set:

```bash
deploy/compose.sh stop monitor-core notifier
deploy/compose.sh exec backup python -m centerline_backup now   # prints the set's name, e.g. 20261009T021348Z
```

Copy that set folder (`deploy/backups/<name>/`) to the server privately: it holds the accounts, the history and the
secrets. On the server:

```bash
deploy/restore.sh <set folder>    # the database and deploy/config from the set; checks the audit chain; starts nothing else
deploy/setup.sh                   # adds only what's missing: deploy/.env
```

**B. Starting empty.**

```bash
deploy/setup.sh                   # deploy/config (the settings and a new database password) and deploy/.env
```

Both are git-ignored and stay on the server.

### 5. This server's address, the Ollama and the backups

Edit `deploy/.env`:

```bash
CENTERLINE_SCHEME=http            # http (the default) or https
CENTERLINE_BIND=0.0.0.0           # the plant LAN too (127.0.0.1: this server only)
CENTERLINE_PORT=6040              # browsers open http://<name or address>:6040
CENTERLINE_OLLAMA_URL=http://10.156.116.70:11434   # the Ollama to ask (step 7): an example, use yours
CENTERLINE_SIMULATOR=off          # always off on the line
CENTERLINE_BACKUP_OFFHOST=/mnt/centerline-backups   # a folder on another disk or a mounted share (O-27)
```

Open the port in the server's firewall. Over HTTP there's no certificate to trust, but passwords and session cookies
cross the network unencrypted ([ADR-0032](docs/decisions/ADR-0032-docker-stack-over-http.md)). For HTTPS, set
`CENTERLINE_SCHEME=https` and list every name and address browsers will use:

```bash
CENTERLINE_SITE=centerline.plant.local, 10.156.116.50   # examples: use the server's own
CENTERLINE_DEFAULT_SNI=10.156.116.50                     # the address, for browsers that open it by IP
```

### 6. Start it

Always through **`deploy/compose.sh`**: it's `docker compose -f deploy/compose.yaml`, with the simulator's file only
when `CENTERLINE_SIMULATOR=on` (never on the line).

```bash
deploy/compose.sh up -d --build   # with the kit: deploy/compose.sh up -d (no --build: it uses the loaded images)
deploy/compose.sh ps              # api and postgres "healthy", the rest "Up"
```

The api applies the database migrations at its first start.

### 7. The Ollama

Centerline doesn't install Ollama: it asks the one `CENTERLINE_OLLAMA_URL` names
([ADR-0050](docs/decisions/ADR-0050-ollama-outside-the-stack.md)). That Ollama needs:
- **the models** `qwen3.5:4b` (the questions, summaries and translation) and `bge-m3` (the OCAP search by meaning);
- **these settings:** `OLLAMA_CONTEXT_LENGTH=4096`, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=24h`,
  `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_NO_CLOUD=true`;
- **a GPU**, for answers within 30 s;
- **a port only Centerline reaches:** Ollama has no password. On another machine, its firewall lets in only this
  server: `http://<its address>:11434`. On this server, publish it on 127.0.0.1 (Docker Desktop) or the Docker bridge,
  172.17.0.1 (Linux), and use `http://host.docker.internal:<port>`.

Where none runs yet, `deploy/ollama/` is one with those settings, as its own project:

```bash
docker compose -f deploy/ollama/compose.yaml -f deploy/ollama/compose.gpu.yaml up -d   # without the GPU file: the CPU, slower
docker compose -f deploy/ollama/compose.yaml exec ollama ollama pull qwen3.5:4b
docker compose -f deploy/ollama/compose.yaml exec ollama ollama pull bge-m3
```

`deploy/ollama/.env` sets where it listens (`OLLAMA_BIND`, `OLLAMA_PORT`). Its GPU needs the NVIDIA driver and, on
Linux, the NVIDIA Container Toolkit ([its guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)).

Then, from Centerline, check it answers and pin its models: put the full digests this prints in
`deploy/config/api.json`, as `ai.model_digest` and `ai.embed_model_digest`, then `deploy/compose.sh restart api`. A model
with another digest isn't used. Moved settings (A) already pin the chat model; check the digest matches.

```bash
deploy/compose.sh exec api python -c "import json, os, urllib.request; [print(m['name'], m['digest']) for m in json.load(urllib.request.urlopen(os.environ['CENTERLINE_OLLAMA_URL'] + '/api/tags'))['models']]"
```

### 8. The first account (B only)

```bash
deploy/compose.sh exec api python -m centerline_api.auth create-admin \
    --username szyrelle --name "Szyrelle" --out /app/config/secrets/first-admin-password
```

Open `http://<name or address>:6040` and sign in with the temporary password in
`deploy/config/secrets/first-admin-password` (valid 24 h). Choose your own password, then delete the file. With moved
settings (A), sign in as before.

With HTTPS, the proxy signs its own certificate, and browsers warn until its CA is trusted. Export it, then install
it on each workstation under Trusted Root Certification Authorities, or ask IT to deploy it or to issue a certificate:

```bash
deploy/compose.sh cp proxy:/data/caddy/pki/authorities/local/root.crt centerline-ca.crt
```

### 9. Configure it (B; for A, check the first two)

On the Configuration page, as an Administrator, then as a Manager:
1. **Connections:** the broker (host, account, password), Timebase, the Teams flow and the SMTP relay.
2. **Operator workstations:** operators sign in only at the line's desks (SES-04). Put the desks' addresses in
   `deploy/config/api.json` under `auth.operator_workstations`, for example
   `[{"name": "Line desk", "ip": "10.156.116.60"}]`, then `deploy/compose.sh restart api`.
3. **Mappings:** "Fill from the broker", check, then activate.
4. **Rules:** give each zone its target and limits ("Fill empty targets from current HMI setpoints" takes the live
   values), then activate.
5. **Notifications:** who gets which messages. Then **Reasons**, and **Analytics ranges** once process engineering
   fills in the template.
6. **Accounts:** the Managers and the operators.
7. **OCAP library** (a Manager): upload the plant's OCAPs (PDF, Word or Excel), check each one's sections, and in an
   Excel OCAP which parameters each row is offered for as a reason, then activate it
   ([ADR-0031](docs/decisions/ADR-0031-ocap-library-deterministic-path.md), [ADR-0039](docs/decisions/ADR-0039-excel-ocaps-and-picked-reasons.md)).
   The AI translates it into Tagalog in the background; a checked Tagalog file, added on the version's sheet and
   activated, is shown instead ([ADR-0044](docs/decisions/ADR-0044-checked-tagalog-ocap.md), [ADR-0045](docs/decisions/ADR-0045-ai-translates-the-ocap.md)).

### 10. Check it

Open **Setup → System health** as an Administrator ([ADR-0038](docs/decisions/ADR-0038-system-health-page.md)). Every line should
be green, and in particular:
- **Plant broker**, **Machine messages** and **Judging:** connected, every area fresh, the line judged;
- **AI model:** "ready on the GPU"; "No Ollama to ask" or "isn't answering" means step 5's URL or step 7's network;
  "runs on the CPU only" means the Ollama has no GPU;
- **OCAP search by meaning:** ready, the Active OCAPs searched by meaning too;
- **Backups** and **Off-host copy:** the last set, and its copy;
- **Malware scanner** and **Timebase:** answering.

Then open Digital Centerline: every zone shows its live values.

### 11. After the move (A)

The old PC must never judge the line again. There:

```bash
deploy/compose.sh down            # stops and removes its containers; its database and backups stay, for reference
```

Keep its last backup set until the server has made its own, off-host.

### Day to day

```bash
git pull && deploy/compose.sh up -d --build                      # a new version; the api migrates the database
deploy/compose.sh exec backup python -m centerline_backup list   # the hourly backups (ADR-0035)
deploy/compose.sh logs -f monitor-core                           # any service's log
deploy/compose.sh stop                                           # stop; everything stays
deploy/kit.sh make                                               # after each release: a new offline kit
```

The containers restart by themselves after a crash or a reboot, unless stopped. `down -v` deletes the database; the
backup sets in `deploy/backups` stay. To restore after a failure, follow step 4 A on a new server with the newest set,
from the off-host folder ([deploy/README.md](deploy/README.md#backups-and-restore)).

The services run as user id 1000. If `deploy/config` belongs to another user, set `CENTERLINE_UID` in `deploy/.env`
and build on that server, or give it to 1000: `sudo chown -R 1000:1000 deploy/config`.

## Tests

```bash
cd services && .venv/bin/python -m pytest   # api, monitor-core, notifier and the acceptance suites; the database tests need deploy/dev running
cd client && npm run lint && npm run build
```

## Secrets

Passwords, tokens and keys live in files under a `secrets/` folder (0600), never in code, configuration files or
logs: `config/secrets/` on a development PC, `deploy/config/secrets/` on a Docker host. These are git-ignored, and
no image contains any of them:
- those folders;
- `config/connections.json` and `config/history/`;
- `deploy/config/` and `deploy/.env`;
- `services/api/config.json`;
- the monitor-core journal (`data/`).

In Docker only the proxy is published, over plain HTTP unless `deploy/.env` says HTTPS (ADR-0032); the development
api stays on 127.0.0.1.
