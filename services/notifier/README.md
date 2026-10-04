# notifier: Teams and email from the outbox

The SDD's notifier (§8), Phase 2's first slice ([ADR-0023](../../docs/decisions/ADR-0023-notifier.md)).
monitor-core writes each message to the outbox with its event (NOT-03). The notifier:

- **routes each message once**, by the routing in effect (Configuration → Notifications), and
  freezes what matched;
- **delivers** each channel × recipient on its own lane, so a Teams outage never holds up email:
  - Teams: a POST to the Power Automate flow's HTTP trigger; any 2xx (it answers 202) is Delivered;
  - email: the plant's SMTP relay, one message per recipient; Submitted means the relay answered
    250, and the message is never sent again after that (NOT-06);
- **retries** within about a second, then after 30 s, 1 min, 5 min, then every 15 min for 24 h
  (NOT-04/05), with the same message, dedup key and Message-ID; after that the delivery is a
  permanent failure, which an Administrator can re-drive (NOT-05);
- **watches monitor-core**: its heartbeat silent 60 s sends one Critical system alert, and one
  notice when it's back;
- **writes its own heartbeat** every 2 s: each lane's last success and error, and the backlog.

Messages raised while no routing is in effect are marked not sent, and never sent later. A
message over 24 h old when it's routed is expired.

## Run

```bash
cd services
PYTHONPATH=common:notifier .venv/bin/python -m centerline_notifier
```

Settings come from `CENTERLINE_NOTIFIER_CONFIG`, or `notifier/config.json` if present:

```json
{ "database": { "dbname": "centerline", "user": "centerline_app", "password_file": "../../config/secrets/postgres-app-password" },
  "config_dir": "../../config", "instance": "control-room-pc" }
```

Without a file it uses the development database as `centerline_app` and `config/`. The
channels (the Teams flow's URL, the relay, the link base) are read from `config/` before
each batch, as the Connections tab saved them, so a change there applies at once.

> **What it sends goes out for real.** Until IT gives the flow and the relay (O-05), point
> the Connections tab at [tools/notify-sink](../../tools/notify-sink/README.md), which keeps
> each message instead of sending it.

## Its tables (migration 0008)

| Table | |
|---|---|
| `notification` | The outbox monitor-core writes; append-only |
| `notification_route` | How each message was routed, written once: its kind, the routing version, the rules that matched |
| `notification_delivery` | One per message × channel × recipient: the message as sent, its status, attempts, next try, last error. A finished one can't change |
| `delivery_attempt` | Every attempt, with what the provider answered; append-only |
| `notifier_heartbeat` | Every 2 s: each lane and the backlog; on `GET /api/v1/health` |

A claimed delivery is leased for 2 min. If its attempt is cut short (the notifier stops or the
database goes away), the attempt is recorded as interrupted and the delivery is tried again.

## Tests

```bash
cd services && .venv/bin/python -m pytest notifier/tests   # 19 tests; the database ones need it running
```

| File | Covers |
|---|---|
| `test_notifier_units.py` | The retry schedule; routing kinds, checks, the ACT-03 guard and matching; what each message says |
| `test_notifier_store.py` | Routing once, expiry, the retries up to a permanent failure, a finished delivery never sent again, leases, restarts, the monitor-core watcher |
| `test_notifier_service.py` | The service against a fake flow and a fake relay: both channels, a Teams outage, a relay that drops before its 250, a channel not set up |
