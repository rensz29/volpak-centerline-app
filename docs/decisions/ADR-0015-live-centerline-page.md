# ADR-0015: The live Digital Centerline page

- **Status:** Accepted. Decision 5 amended by [ADR-0016](ADR-0016-accounts-sign-in-and-roles.md): with login, a
  Manager acknowledges a Critical from the event's sheet. Amended by [ADR-0028](ADR-0028-polling-idempotency-g2-acceptance.md) (2026-10-06): the page keeps polling;
  there's no WebSocket for one line. Decision 4 amended by [ADR-0033](ADR-0033-line-view-3d.md) (2026-10-06): the counts
  move into a line view that shows the machine in 3D above the zone table
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner)
- **Related:** [ADR-0014](ADR-0014-monitor-core.md) (monitor-core), [ADR-0012](ADR-0012-rules-configuration-postgresql.md)
  (rules), [ADR-0013](ADR-0013-tag-mappings.md) (mappings), [ADR-0010](ADR-0010-pause-actual-rules-when-stopped.md)
  (stop pause)
- **URS:** OPC-05, OPC-07, HMI-05, ACT-03, PER-01; guide §5 (time budget), §6.7 (heartbeat), §11 (api), §15 (prototype gaps)

## Context

- monitor-core (ADR-0014) judges every zone and writes its events to PostgreSQL,
  but no page showed them.
- `/centerline` was still the prototype. It showed sample data and judged in the
  browser, which contradicts the SDD (§15):
  - a percentage tolerance around the target;
  - a raw `HMI ≠ target` check;
  - no pause gate.
- The guide's target design pushes changes over a WebSocket (§11), behind login
  and roles (§12). Neither exists yet.
- The page must show what monitor-core decided and never judge again.

## Decision

1. **monitor-core puts its live state in its heartbeat.** The heartbeat is written
   every 2 s (ADR-0014 had 10 s), as one row per instance updated in place.
   - For each zone it carries:
     - the latest setpoint and actual;
     - the target;
     - the Warning and Critical bands around the HMI setpoint;
     - the HMI and Actual states;
     - the due time of any pending delay;
     - the open events;
     - the rules version each check judges by.
   - For the line it carries:
     - whether it's judging, or the pause reasons;
     - the SKU;
     - the stop state and warm-up;
     - the versions in effect.
   - Each check shows the rule it actually judges by: an open event's pinned rule
     (OPC-07), otherwise the rule in effect. So a zone's target and its bands can
     come from different versions.
2. **The api only reads** (invariant 3: services talk through the database). New
   read-only endpoints:
   - `GET /api/v1/monitoring/live`: the heartbeat, named and grouped by parameter
     from the register, plus the open events and their counts;
   - `GET /api/v1/events?open=&limit=`;
   - `GET /api/v1/events/{id}`: the pinned rule, the versions it was judged under,
     every change of state with its inputs, and its outbox rows;
   - `GET /api/v1/monitoring/brief-changes` (HMI-05).

   A heartbeat older than 60 s means monitor-core isn't running, and every zone
   shows No data (§6.7).
3. **The page polls every 2 s** while it's visible.
   - A failed refresh keeps the last view on screen and puts the problem in the
     banner.
   - Countdowns run on the server's clock.
   - The banner warns when the last heartbeat is more than 10 s old.
4. **What the page shows:**
   - **A banner first**, in one of these states:
     - judging, with the SKU and the rules, mapping and register versions;
     - paused, with the reasons (OPC-05);
     - Actual rules paused while stopped or warming up (ADR-0010);
     - monitor-core not running, or never run;
     - the api unreachable.
   - **Counts:** zones, HMI mismatches, Warnings, Criticals.
   - **The zone table,** grouped by URS parameter:
     - Target, HMI setpoint and Actual;
     - the HMI check, with the countdown to an event;
     - the Actual check, with any pending change and its countdown.

     The tooltips give the bands and the rules version. Status is never shown by
     colour alone. A check without a valid value shows No data, because a state
     machine's starting state isn't a judgement. An open event keeps its badge,
     because it's on record.
   - **Open events:** Criticals first, then Warnings, then HMI mismatches, each with
     its values at opening.
   - **An event's evidence** in a side sheet:
     - the rule and versions it was judged under;
     - every change of state with its inputs;
     - its notifications, which stay pending until the Phase 2 notifier.
   - **Recent activity,** refreshed every 10 s: recently closed events and brief
     changes.
5. **Read-only until login.** There's no acknowledge button, because acknowledging is
   the Manager's and needs login and roles. The api stays on 127.0.0.1.
6. **Polling now, the WebSocket later,** with login. The page will then treat
   WebSocket messages as hints and refetch over REST, so these endpoints stay.
7. The prototype `DigitalCenterlinePage` stays in `client/src/` unrouted, like the
   prototype Analytics page.

## Consequences

- There's one judge. The browser only names and colours monitor-core's states.
- **Timing:**
  - A new event appears on the next poll, within 2 s of its transaction, because
    the open events are read from the event table. That's within the 3 s popup
    budget (§5, PER-01) even before the WebSocket.
  - The zone states come from the heartbeat, so a zone's badge can trail its event
    by up to 2 s.
  - Judging isn't affected: monitor-core judges each message as it arrives.
- **Load:** each open page makes one small request every 2 s. That's fine for the few
  screens on one line. The WebSocket replaces the polling later.
- **Still showing the prototype's sample data:** the sidebar alarm badge, the bell and
  the Active Alarms and Alarm History pages. They move to these events in the alarms
  slice, with login and the Manager's acknowledgment.

## Tests

- `services/monitor_core/tests/test_monitor_engine.py`:
  - the status carries each zone's values, bands and pending timers;
  - the target and the bands each come from their own rule.
- `services/api/tests/test_monitoring_api.py`:
  - without monitor-core, every zone is unknown;
  - the live state combines the heartbeat with the open events;
  - a stale heartbeat means nothing is known;
  - event lists, event details and brief changes.
- Checked in headless Edge against a scratch stack (Mosquitto, the simulator,
  monitor-core and a scratch database):
  - judging, with HMI mismatches, Warnings and Criticals;
  - the event sheet;
  - the pause when the simulator stopped;
  - a restart that restored the open events under their pinned rules.
