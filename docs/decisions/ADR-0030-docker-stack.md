# ADR-0030: The application in Docker, judging the real plant on its own database: a rehearsal for the control-room PC

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decider:** Szyrelle (system owner), on 2026-10-06. Asked what the Docker stack should run against while the
  features are tested, the owner chose "the real plant in Docker". The other options were a simulator test stack
  and both as profiles.
- **Related:** [ADR-0003](ADR-0003-host-runtime.md) (the control-room PC's runtime), [ADR-0020](ADR-0020-database-roles.md)
  (the services' role), [ADR-0021](ADR-0021-g0b-revised.md) (G0b), [ADR-0026](ADR-0026-real-app-on-the-real-machine.md)
  (the real application on this laptop), [ADR-0028](ADR-0028-polling-idempotency-g2-acceptance.md) (the proxy for AT-04)
- **URS:** DEP-01…06, SEC-01, SES-04; OPC-01 (subscribe only)

## Context

- **The plan has nine containers on one Docker host** (SDD §3, §4 `deploy/compose.yaml`). Until now only the
  development database ran in Docker. The services ran from terminals, and the web app from Vite on :5173.
- **Five containers exist as code:** proxy, api, monitor-core, notifier and postgres. The other four come with
  their phases: ai-worker, ollama and clamav in Phase 3, backup-agent in Phase 5.
- **The owner wants to test the features as they'll run in production,** and chose the real plant for it.

## Decision

1. **`deploy/compose.yaml` runs the five containers** from two images:
   - `centerline-services`: Python 3.12, the api, monitor-core and the notifier, one command each. It runs as an
     unprivileged user, with the repository's layout at `/app`.
   - `centerline-web`: the web app built with Node, served by Caddy.

   The containers restart by themselves unless stopped. The api has a health check, and the other services start
   only once it's healthy: it migrates the database first.
2. **Each host has its settings and secrets in `deploy/config`** (git-ignored, 0700), mounted at `/app/config`. It
   holds the services' settings, the connections, the register's export, the query log and `secrets/`.
   - The api mounts it read-write; monitor-core and the notifier read-only.
   - `deploy/setup.sh` seeds it once from `config/`: the register, the plant connections with the secrets they
     name, and the old history. It makes a new database password and never overwrites a file.
   - No image contains a setting or a secret (`.dockerignore`).
3. **The proxy is the only way in:** Caddy with its own local CA, on `https://localhost:6040`, this PC only. It
   moved there from 8443 at the owner's request the same day.
   - It serves the web app and passes `/api` on. It overwrites `X-Forwarded-For`.
   - The api trusts that header only from the proxy, so the session cookie's `Secure` flag and the workstation rule
     (SES-04) work as designed. It finds the proxy by its service name, `proxy`, through Docker's DNS, looked up every
     30 s. Docker picks the stack's network range on each host. A fixed range, 172.31.247.0/24 at first, clashed
     with another network on the second machine the same day.
   - The api and the database aren't published.
   - Each host sets in `deploy/.env` the names and addresses browsers use (the certificate covers each), the
     address and port it listens on, and the services' user id. This laptop listens on 127.0.0.1:6040; another
     machine opens it to the plant LAN (README, "Deploy on another machine").
4. **It judges the real machine on its own database,** as the control-room PC will. That database starts empty:
   the owner's account is created on the command line, and the configuration is entered again. Or the development
   database is copied in while the new one is still empty; `deploy/README.md` has the commands, tested on
   2026-10-06. monitor-core subscribes read-only with the client ID `centerline-monitor-centerline-docker`.
5. **One monitor-core judges the line at a time.** The development services are stopped before this stack's
   monitor-core and notifier start.

## Consequences

- **What it writes is permanent history,** as on the development setup (ADR-0026). There are now two databases of
  real history on this laptop. The owner decides which one moves to the control-room PC, or whether it starts afresh
  there.
- **Docker Desktop can't show two things** that wait for the control-room PC (G0b):
  - starting without a Windows session (DEP-05), which is why the SDD rejects it for production;
  - the browsers' real addresses (SES-04), because it presents every browser on this PC as one address. To test an
    operator sign-in, that address goes into `auth.operator_workstations`.
- **The control-room PC runs the same files** on Docker Engine in the Hyper-V VM (ADR-0003), with the proxy opened to
  the plant LAN and the real workstation addresses configured.
- **A code change means rebuilding:** `docker compose … up -d --build`.
- **The browser warns about the certificate** until the proxy's CA is trusted on the PC. On the plant, the CA is
  installed on the workstations, or IT issues a certificate.

## Verification

- 2026-10-06:
  - both images built;
  - the services image imports all three services, runs as uid 1000, and holds no setting or secret;
  - the api migrated the new database (13 migrations) and imported register 2026-10-05.1;
  - `https://localhost:8443` answered from WSL and from Windows;
  - the owner's account was created on the command line;
  - copying the development database into a scratch database of the new server restored every table with its
    grants, and the audit chain verified.
