# monitor-core: the monitoring engine

The SDD's monitor-core (§5), Phase 1's first slice
([ADR-0014](../../docs/decisions/ADR-0014-monitor-core.md)). It subscribes to
the machine's MQTT messages and judges every monitored zone. It writes events,
their evidence and outbox notifications to PostgreSQL.

- **Read-only to the plant:** publishing is disabled in the code and it sets no
  Last Will.
- **Judges only a complete, fresh snapshot** (OPC-03, OPC-05, OPC-08).
- **HMI mismatch** (HMI-01…05) and **Actual Warning/Critical** (ACT-01…04),
  following the SDD's two diagrams. Actual rules pause while the machine is
  stopped (ADR-0010).
- **Every event is pinned** to the rules, mapping and register versions it was
  judged under (OPC-07).
- **Every HMI mismatch asks that shift's operator why**
  ([ADR-0025](../../docs/decisions/ADR-0025-shifts-and-reasons.md)). The request is
  made with the event and closes with it. One still open after 15 min alerts
  Management once, and an unfinished one closes as not answered when its shift ends.

## What it needs

It takes everything from the Configuration page:

| From | What |
|---|---|
| Connections | The broker, its topic filters, and each area's freshness limit (`config/connections.json`) |
| Tags | The register: which zones are monitored and with which tags |
| Mappings | The mapping in effect: each tag's topic and field |
| Rules | The rules in effect: each zone's target, limits and delays, and the stop pause (ADR-0027) |
| Live page, Maintenance page | Zones a Manager switched off, and maintenance windows not ended (read every 2 s, ADR-0017) |

A zone switched off isn't judged: its open events close as "Monitoring disabled", with no
recovery notice. Switched on again, it's judged on fresh values with delays from zero. In a
maintenance window on chosen zones, their delays and repeats wait and open events stay open.
A whole-line window closes the gate. Past its planned end a window stays in force, overdue,
and Management gets one `system` alert.

If a piece is missing, it keeps running but doesn't judge. The heartbeat says why,
and so does `GET /api/v1/health` under `monitor`. For example: "No rules are in
effect", or "The rules in effect don't give every zone its Warning and Critical
limits". That last one, alone, also alerts Management once (OPC-08). A zone without a
target is judged on its actual value only; the live page shows its HMI as "Not judged".

## Run

```bash
cd services
PYTHONPATH=common:monitor_core .venv/bin/python -m centerline_monitor
```

Start the api once first, so the database schema is up to date. Settings come
from `CENTERLINE_MONITOR_CONFIG`, or `monitor_core/config.json` if present:

```json
{ "database": { "dbname": "centerline" }, "config_dir": "../../config", "instance": "control-room-pc" }
```

Without a file it uses the development database and `config/`.

> **On this laptop the saved broker is the plant broker.** Since 2026-10-02 the real
> application judges the real machine from here, on the real database, read-only
> ([ADR-0026](../../docs/decisions/ADR-0026-real-app-on-the-real-machine.md)). What it writes is
> permanent. G0b still gates the control-room PC: the host test, and M7 unless the owner
> takes it out ([ADR-0021](../../docs/decisions/ADR-0021-g0b-revised.md)).
>
> For development, point it at a scratch config folder whose `connections.json`
> names a local Mosquitto fed by `tools/mqtt-sim`, and at a scratch database.
> That's what the end-to-end test does.

## Its database role

It connects as `centerline_app`, which can add and read evidence but not change it, switch
the triggers off, or touch the schema ([ADR-0020](../../docs/decisions/ADR-0020-database-roles.md)).
Give another account with a `database` block in its config.

## When the database is away

monitor-core keeps judging. Each step it can't write goes to the disk journal,
`data/journal/<instance>.jsonl` (0600, folder 0700; `journal_dir` in its config), flushed before it
carries on. Every 5 s it tries the database again; when it answers, the journal is written in order
and emptied. A restart replays the last run's journal before anything else. Past `journal_limit_s`
(30 min) the gate closes with the reason and nothing new is judged, so nothing is ever dropped
([ADR-0018](../../docs/decisions/ADR-0018-disk-journal.md), RES-01).

## What it writes

| Table | Holds |
|---|---|
| `event`, `event_transition` | Each event, pinned to its versions, and every change of state (append-only) |
| `event_state` | Each event's current state |
| `lightweight_change` | Brief setpoint changes (HMI-05) |
| `notification` | The outbox: initial, escalation, repeats, recovery, system alerts, overdue reason requests. Delivered by the notifier (ADR-0023) |
| `shift_instance`, `workflow_request` | Each shift with something on record; a reason request per HMI mismatch per shift, opened and closed with its event, escalated after 15 min, closed as not answered at the shift's end (ADR-0025) |
| `scheduled_action` | Every delay, repeat and warm-up timer. Pending ones are abandoned on a restart, because timers restart from zero (MNT-02) |
| `pause_period` | When judging stopped (`line`), or Actual rules paused for a stop (`actual`), and why |
| `event_acknowledgment` | Written by the api when a Manager acknowledges; stops a Critical's repeats (ACT-04). Each counts for the Critical period it was given in; one given while monitor-core is down is applied when it restarts, and none twice (ADR-0016) |
| `monitor_heartbeat` | Every 2 s: whether it's judging, why not, and each zone's values, bands, states and pending delays, with the rules version each check judges by. The Digital Centerline page reads it (ADR-0015) |

## Tests

```bash
cd services && .venv/bin/python -m pytest monitor_core/tests   # 65 tests; the database and Mosquitto ones need them running
```

| File | Covers |
|---|---|
| `test_monitor_rules.py` | HMI truncation and the Actual boundaries, from the URS examples |
| `test_monitor_engine.py` | The AT-01…03 scenarios against a simulated line and clock; the stop pause, rule pinning; incomplete rules, and a zone without a target (ADR-0027) |
| `test_monitor_store.py` | One transaction per step and safe replays; append-only evidence; restart; acknowledgment; database outage |
| `test_monitor_control.py` | Zones switched off and on again; zone and line maintenance windows, overdue, and the resume on fresh data (ADR-0017) |
| `test_monitor_journal.py` | The disk journal: every effect kept exactly and in order, permissions, a torn last line, the pause past 30 min (ADR-0018) |
| `test_monitor_config.py` | The rules in effect, read from the database; targets optional, limits not; a rule pinned before ADR-0027 still loads |
| `test_monitor_mqtt.py` | The subscriber can't publish and leaves no Last Will, and no code in monitor-core sends (ADR-0006 M6) |
| `test_monitor_workflow.py` | Reason requests: made with an HMI mismatch and closed with it, none for Actual events, the 15-min escalation once, not answered at the shift's end (ADR-0025) |
| `test_monitor_e2e.py` | Mosquitto, the simulator, the service loop and PostgreSQL |
