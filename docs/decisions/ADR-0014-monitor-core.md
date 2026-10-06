# ADR-0014: monitor-core, the monitoring engine (Phase 1, first slice)

- **Status:** Accepted. Decision 6 amended by [ADR-0015](ADR-0015-live-centerline-page.md): the heartbeat is written
  every 2 s and carries every zone's values and states for the Digital Centerline page
  Decision 1 corrected on 2026-10-01: the retry timing and the payload clock in the evidence.
  Amended by [ADR-0027](ADR-0027-no-sku.md) (2026-10-05): the gate checks no SKU, and there's no changeover
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner)
- **Related:** [ADR-0001](ADR-0001-sku-changeover.md) (changeover), [ADR-0006](ADR-0006-mqtt-acquisition.md) (MQTT),
  [ADR-0010](ADR-0010-pause-actual-rules-when-stopped.md) (stop pause), [ADR-0012](ADR-0012-rules-configuration-postgresql.md)
  (rules), [ADR-0013](ADR-0013-tag-mappings.md) (mappings)
- **URS:** OPC-01…08, HMI-01…05, ACT-01…04, MNT-02, DAT-01, OPC-07; acceptance tests AT-01…03 (gate G1)

## Context

- The Configuration page now defines everything the engine judges against:
  - the connection;
  - the register;
  - the mapping in effect;
  - the rules in effect.
- The owner started Phase 1 on 2026-09-30, on the simulator (gate G1). As with
  Phase 4, this is ahead of the URS approval that gate G0a still lists.
- The SDD fixes the architecture and the two state diagrams, but leaves some
  details to design. Those are decided below.

## Decision

1. **A service of its own**: `services/monitor_core`, run as `python -m centerline_monitor`.
   - One thread judges. The MQTT client's thread only queues each message with
     our arrival time; the payload clock is kept as evidence only (invariant 13).
   - The subscriber can't publish and sets no Last Will (M6). It retries the
     broker every 5 s for one minute, then every 30 s (OPC-03).
   - It uses paho-mqtt 2 and its own network thread. ADR-0006 named `aiomqtt`, a
     wrapper over paho for asyncio, which the judging loop doesn't use.

   **Corrected in the review of 2026-10-01:**
   - The retries used to back off 5, 10, 20, 30 s, against OPC-03. They now keep to it.
   - The payload clock was only held in memory. Each transition's evidence now keeps
     it (`payload_clock`, each area's `_timestamp`) beside our time. The heartbeat and
     `GET /api/v1/health` carry each area's skew, with a warning past 5 s (guide §6.1).
2. **Pure core, tested without broker or database** (DD-01): the rules, the zone
   state machines, the snapshot gate and the stop pause. The engine gets the
   clock and the store passed in.
3. **Inputs**:
   - the latest register version, and the mapping and rules versions in effect;
   - the saved broker and per-area freshness from `connections.json`;
   - the SKU from the mapped SKU field.

   Anything missing keeps the gate closed, with the reason in the heartbeat. The
   engine never guesses. It reloads within 5 s when another version takes effect.
4. **The snapshot gate** is as in the guide (§6.2). Judging needs:
   - the broker connected;
   - every mapped topic heard within its area's limit;
   - every needed tag holding a number;
   - a SKU whose rules are complete.

   Retained messages don't count. After a pause it reopens only when every topic
   has sent a message since the pause (OPC-05). A missing or unconfigured SKU
   alerts Management once per pause, and only when the data is otherwise complete
   (OPC-08).
5. **The machines follow the SDD diagrams.** Details decided here:
   - **Superseded events** close without a recovery notice. The next event links
     back to the one it superseded, and if the new value returns to target within
     its delay, that's a brief change (no alert), as the diagram shows.
   - **Brief changes:**
     - *lightweight*: a minimal row;
     - *cleared-before-trigger*: the row plus the values seen;
     - *do not record*: nothing.
   - **An Actual event** opens on leaving Normal and closes on returning to it.
     Warning ↔ Critical are transitions within the same event.
     - It notifies at opening if Warning notifications are on, or if it opens as
       Critical.
     - Escalating to Critical always notifies.
     - A recovery notice goes out only if something was sent before.
   - **Critical repeats** come at +15, +30, +45 and +60 min, with a final
     escalation at +75 min: at most six messages per Critical period.
     - A Manager's acknowledgment stops them.
     - A new Critical period after a downgrade starts a new sequence.
   - **Pauses** stop the timers; delays restart from zero afterwards (MNT-02). An
     unacknowledged Critical's next repeat restarts from zero but keeps its count.
   - **The stop pause** follows ADR-0010. A stop already going on at start-up
     counts as long, so the warm-up applies.
   - **SKU changeover** follows ADR-0001.
   - **An open event** keeps the rule it opened under until it closes (OPC-07).
     The rule is stored with the event, so a restart continues under it.
6. **Tables** (migration `0003`):
   - append-only evidence: `event`, `event_transition`, `lightweight_change`,
     `event_acknowledgment`;
   - `event_state`, a projection of each event's current state;
   - `scheduled_action`, the timers; `pause_period` rows can be ended once;
   - `notification`, the outbox, delivered by the notifier in Phase 2;
   - `monitor_heartbeat`, every 10 s (every 2 s since ADR-0015, carrying the live
     values). The api's health shows it, and it counts as stale after 60 s.

   Each event records the rules, mapping and register versions it was judged under.
7. **Writing:**
   - Each step is one transaction: event, transition and outbox rows together
     (invariant 6).
   - Every write is safe to repeat (UUIDv7 keys, dedup keys). During a database
     outage, steps wait in memory in order and are written when it returns. Since
     [ADR-0018](ADR-0018-disk-journal.md) they wait in the disk journal instead, which a restart also replays.
   - On a restart:
     - unfinished timers are marked abandoned and restart from zero;
     - open events carry on under their pinned rules;
     - a Critical carries on counting the repeats already sent.

## Consequences

- The G1 scenarios run as tests:
  - AT-01: fresh complete snapshots, silent areas, lost connection, bad values, SKU;
  - AT-02: truncation, delay, brief changes, supersede, recovery;
  - AT-03: boundaries, escalation, downgrade, the 15 s recovery, repeats and
    acknowledgment.

  They run at the engine level, against PostgreSQL, and end to end on a local
  Mosquitto with the simulator.
- **The real machine still isn't judged**, and needs:
  - a SKU field in the machine's messages (O-15);
  - SKUs and targets from process engineering, and a rules version in effect;
  - controls M1–M5 before connecting monitor-core to the plant broker (G0b).
- **Still to come in Phase 1:**
  - the events api and the live Digital Centerline page (built, ADR-0015);
  - login and roles, with the Manager's acknowledgment endpoint (built, ADR-0016);
  - the disk journal that survives a restart of monitor-core (RES-01; built, ADR-0018);
  - monitoring disable (MON-01) and maintenance windows (MNT-01) (built, ADR-0017);
  - the database roles `app_rw` and `purge`.

  Delivery of the outbox rows is Phase 2.

## Tests

`services/monitor_core/tests/`:
- `test_monitor_rules.py`: HMI truncation and the Actual boundaries from the URS examples.
- `test_monitor_engine.py`: the AT-01…03 scenarios, the stop pause, changeover and rule pinning.
- `test_monitor_store.py`: one write per step, append-only, restart, acknowledgment, outage.
- `test_monitor_e2e.py`: Mosquitto, the simulator, the service loop and PostgreSQL.
