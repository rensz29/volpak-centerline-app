# Digital Centerline: monitoring and OCAP assistance for the Volpak line

Centerline watches the Volpak filler's setpoints and actual values, raises an event when they leave the
centerline, asks the shift's operator why, and tells Management. It also correlates history from the
Timebase historian. It is read-only to the plant: it subscribes to the MQTT broker and only reads Timebase.

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
| [deploy/](deploy/README.md) | The application in Docker: `compose.yaml`, the images, the proxy's Caddyfile, `setup.sh` (ADR-0030) |
| [deploy/dev/](deploy/dev/README.md) | The development database: PostgreSQL 17 with pgvector, in Docker |
| [deploy/host-check/](deploy/host-check/README.md) | Checks for the control-room PC (G0b) |
| `config/` | The parameter register. Connection settings, secrets and backups stay here too, git-ignored |
| `tools/` | Phase 0 probes and analyses, the MQTT simulator and a local stand-in for Teams and SMTP |
| [tests/acceptance/](tests/acceptance/README.md) | The URS acceptance suites the phase gates run: AT-04…06 for G2, AT-08's deterministic part for G3, AT-ANA-01…10 for G4 |
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

## Deploy on another machine

The application runs as seven containers: the proxy, api, monitor-core, notifier, PostgreSQL, ClamAV and the backup
agent. They judge the real
machine on the plant broker and read the real Timebase, on the machine's own database
([deploy/README.md](deploy/README.md), [ADR-0030](docs/decisions/ADR-0030-docker-stack.md)). Everything it writes is
permanent history.

> **Before the control-room PC goes live,** gate G0b still asks for the host test
> ([deploy/host-check](deploy/host-check/README.md)) and the Timebase admin's confirmation that Timebase refuses
> writes (M7, [ADR-0021](docs/decisions/ADR-0021-g0b-revised.md)). The SDD's host is a Hyper-V Linux VM with Docker
> Engine ([ADR-0003](docs/decisions/ADR-0003-host-runtime.md)). Docker Desktop is fine for a trial, but needs someone
> signed in to Windows.

### 1. What the machine needs

- **Docker Engine with the Compose plugin** ([docs.docker.com/engine/install](https://docs.docker.com/engine/install/)),
  and git.
- **Network access:**
  - to the plant broker (10.156.116.176:1883) and to Timebase (10.156.116.179:4516);
  - from the operators' and Managers' browsers to the port you choose below (6040 by default);
  - to the Teams flow and the SMTP relay, once IT gives them (O-05).
- **About 1 GB of memory for clamav**, the malware scanner for uploaded OCAPs.
- **Internet, to build the images.** Without it, see [Without internet on the plant network](#without-internet-on-the-plant-network).

### 2. Get the code and prepare the machine's settings

On the development PC, commit and push what you want to deploy (`git push`). Then, on the new machine:

```bash
git clone https://github.com/rensz29/volpak-centerline-app.git
cd volpak-centerline-app
deploy/setup.sh
```

`setup.sh` creates two things:
- **`deploy/config/`** (0700): the services' settings and a new database password. The register comes from
  `config/parameter-register.json` in git, and the broker and Timebase connections from `config/` where they exist.
  On a new machine they don't, so you enter them on the Configuration page in step 5.
- **`deploy/.env`:** where the proxy listens.

Both are git-ignored and stay on that machine.

### 3. Let the plant reach it

Edit `deploy/.env`:

```bash
CENTERLINE_SCHEME=http                                   # plain HTTP (the default) or https
CENTERLINE_BIND=0.0.0.0                                  # all network interfaces: the plant LAN too
CENTERLINE_PORT=6040                                     # the port browsers use: http://<name or address>:6040
```

Open the port in the machine's firewall. Over HTTP any name or address of the machine works, and there's no
certificate to trust. But passwords and session cookies cross the network unencrypted: test on a network you trust
([ADR-0032](docs/decisions/ADR-0032-docker-stack-over-http.md)). HTTP or HTTPS at go-live is the owner's decision (O-25).

For HTTPS, set `CENTERLINE_SCHEME=https` and list every name and address browsers will use, for the certificate:

```bash
CENTERLINE_SITE=centerline.plant.local, 10.156.116.50   # examples: use the machine's own
CENTERLINE_DEFAULT_SNI=10.156.116.50                     # the address, for browsers that open it by IP
```

### 4. Start it and create the first account

```bash
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps            # api and postgres "healthy", the rest "Up"
docker compose -f deploy/compose.yaml exec api python -m centerline_api.auth create-admin \
    --username szyrelle --name "Szyrelle" --out /app/config/secrets/first-admin-password
```

Open `http://<name or address>:6040` and sign in with the temporary password in
`deploy/config/secrets/first-admin-password` (valid 24 h). Choose your own password, then delete the file.

With HTTPS, open `https://<name>:6040`. The proxy signs its own certificate, so browsers warn until its CA is
trusted. Export the CA:

```bash
docker compose -f deploy/compose.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt centerline-ca.crt
```

Install it on each workstation under Trusted Root Certification Authorities, or ask IT to deploy it, or to issue a
certificate.

### 5. Configure it

On the Configuration page, as an Administrator, then as a Manager:
1. **Connections:** the broker (host, account, password), Timebase, the Teams flow and the SMTP relay.
2. **Mappings:** "Fill from the broker", check, then activate.
3. **Rules:** start from the Phase 0 proposal, give each zone its target, then activate.
4. **Notifications:** who gets which messages. Then **Reasons**, and **Analytics ranges** once process engineering
   fills in the template.
5. **Accounts:** the Managers and the operators.
6. **OCAP library** (a Manager): upload the plant's OCAPs, PDF or Word, check each one's sections and activate it
   ([ADR-0031](docs/decisions/ADR-0031-ocap-library-deterministic-path.md)). Until then, every reason goes to a Manager's guidance.

**Operator workstations:** operators sign in only at the line's desks (SES-04). Put the desks' addresses in
`deploy/config/api.json` under `auth.operator_workstations`, for example
`[{"name": "Line desk", "ip": "10.156.116.60"}]`, then `docker compose -f deploy/compose.yaml restart api`.

**One monitor-core judges the line.** Stop any other one, the development PC's or another Docker stack's, before this
one starts. Otherwise every alarm is recorded twice, in two databases.

### Move the history from another machine

To keep the configuration, accounts and events instead of starting empty, restore a backup in place of step 4, before
the stack's first start. On the old machine:

```bash
(umask 077; docker compose -f deploy/compose.yaml exec -T postgres pg_dump -U centerline -Fc centerline > centerline.dump)
```

Copy `centerline.dump` privately: it holds the accounts and the history. Then, on the new machine:

```bash
docker compose -f deploy/compose.yaml up -d postgres
docker compose -f deploy/compose.yaml exec -T postgres psql -U centerline -d centerline -c "CREATE ROLE centerline_app LOGIN"
docker compose -f deploy/compose.yaml exec -T postgres pg_restore -U centerline -d centerline < centerline.dump
docker compose -f deploy/compose.yaml up -d --build
```

The accounts come with the backup, so skip `create-admin` and sign in as before. From the development database, make
the backup with `docker exec centerline-dev-postgres-1 pg_dump -U centerline -Fc centerline > centerline.dump`
instead. The api applies any migrations the backup lacks.

### Without internet on the plant network

Build the images where there is internet, and carry them over:

```bash
docker compose -f deploy/compose.yaml build
docker pull clamav/clamav:stable
docker save centerline-services:latest centerline-web:latest pgvector/pgvector:pg17 clamav/clamav:stable | gzip > centerline-images.tar.gz
```

On the plant machine, after `git clone` (or a copy of the repository) and `setup.sh`:

```bash
gunzip -c centerline-images.tar.gz | docker load
docker compose -f deploy/compose.yaml up -d          # no --build: it uses the loaded images
```

The clamav image carries the signatures of the day it was pulled; keeping them current there is O-24.

The services run as user id 1000. If `deploy/config` belongs to another user there, either set `CENTERLINE_UID` in
`deploy/.env` and build on that machine, or give it to 1000: `sudo chown -R 1000:1000 deploy/config`.

### Update, back up, stop

```bash
git pull && docker compose -f deploy/compose.yaml up -d --build      # a new version; the api migrates the database
docker compose -f deploy/compose.yaml exec backup python -m centerline_backup list   # the hourly backups (ADR-0035)
docker compose -f deploy/compose.yaml stop                           # stop; everything stays
docker compose -f deploy/compose.yaml logs -f monitor-core           # any service's log
```

The containers restart by themselves after a crash or a reboot, unless stopped. `down -v` deletes the database; the
hourly backup sets in `deploy/backups` stay. Set an off-host folder for them in `deploy/.env`, and restore with
`deploy/restore.sh` ([deploy/README.md](deploy/README.md#backups-and-restore)).

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
