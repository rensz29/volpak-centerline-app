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
| [services/api/](services/api/README.md) | The api (FastAPI): sign-in, configuration, live monitoring, alarms, reasons, notifications, Analytics |
| [services/monitor_core/](services/monitor_core/README.md) | monitor-core: subscribes to the broker, judges every zone, writes events and the outbox |
| [services/notifier/](services/notifier/README.md) | The notifier: delivers the outbox to Teams and email |
| `services/common/` | Code the services share, with no web framework in it |
| `db/` | Plain SQL migrations, applied in order by the api, and the seed proposals |
| [deploy/dev/](deploy/dev/README.md) | The development database: PostgreSQL 17 with pgvector, in Docker |
| [deploy/host-check/](deploy/host-check/README.md) | Checks for the control-room PC (G0b) |
| `config/` | The parameter register. Connection settings, secrets and backups stay here too, git-ignored |
| `tools/` | Phase 0 probes and analyses, the MQTT simulator and a local stand-in for Teams and SMTP |

## Run it on a development PC

1. Start the database: [deploy/dev/README.md](deploy/dev/README.md).
2. Start the api, and create the first Administrator: [services/api/README.md](services/api/README.md#run).
3. Start the web app: `cd client && npm install && npm run dev`, then open <http://localhost:5173>.
4. To judge a line, run monitor-core and the notifier: [services/monitor_core/README.md](services/monitor_core/README.md)
   and [services/notifier/README.md](services/notifier/README.md). For development, point monitor-core at a local
   Mosquitto fed by [tools/mqtt-sim](tools/mqtt-sim/README.md) and a scratch database, never the plant broker.

## Tests

```bash
cd services && .venv/bin/python -m pytest   # api, monitor-core and notifier; the database tests need deploy/dev running
cd client && npm run lint && npm run build
```

## Secrets

Passwords, tokens and keys live in files under `config/secrets/` (0600), never in code, configuration files or
logs. That folder, `config/connections.json`, `config/history/`, `services/api/config.json` and the
monitor-core journal (`data/`) are git-ignored. The api stays on 127.0.0.1 until the HTTPS proxy exists.
