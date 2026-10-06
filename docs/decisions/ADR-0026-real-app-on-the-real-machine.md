# ADR-0026: The real application judges the real machine from the development laptop, before G0b

- **Status:** Accepted. Decision 3 amended by [ADR-0027](ADR-0027-no-sku.md) (2026-10-05): no placeholder SKU or SKU list; the targets are
  each zone's, in the rules
- **Date:** 2026-10-02
- **Decider:** Szyrelle (system owner), on 2026-10-02: "5173 on the real machine", chosen over a development
  copy on the simulator, to show the rules working and the alarms on the real application
- **Amends:** [ADR-0021](ADR-0021-g0b-revised.md): G0b no longer gates connecting the real application on the
  development laptop. It still gates the control-room PC, the production host.
- **Related:** [ADR-0006](ADR-0006-mqtt-acquisition.md) (M6: subscribe only), [ADR-0022](ADR-0022-placeholder-sku.md)
  (the placeholder SKU and its targets), [ADR-0023](ADR-0023-notifier.md) (the notifier),
  [ADR-0024](ADR-0024-plant-trial.md) (the trial, until now the only connection to the plant broker)
- **URS:** OPC-01…08, HMI-01…05, ACT-01…04, NOT-01…07; DAT-01 (everything it writes is permanent)

## Context

- **The trial shows real values, but in its own database** (ADR-0024). The real application on :5173 had no
  monitor-core: its Digital Centerline page showed no data, and no rule or alarm could be seen working there.
- **Its configuration couldn't judge anything:**
  - mapping v2 has neither the SKU field nor a placeholder, so the gate stays closed (OPC-08);
  - rules v2, saved as "test", has absolute values typed where the limits are offsets around the setpoint
    (Vertical: Warning −223/+215 °C), so no value would ever leave its band.
- **Asked how to show the rules and the alarms**, the owner chose the real application on the real machine.
  The options also included a development copy of the real database on the simulator.

## Decision

1. **monitor-core and the notifier run on the real `centerline` database**, from the development laptop, with
   their default settings.
   - monitor-core subscribes, read-only, to the plant broker saved on the Connections tab. It uses the shared
     account, accepted for now in ADR-0021 (M1–M5), and its own client ID, `centerline-monitor-<host>`.
   - It can't publish or leave a Last Will (M6, tested).
   - The notifier delivers by the routing in effect. There's none yet, so messages are recorded as not sent.
     Teams and email aren't set up (O-05), so nothing leaves the laptop.
2. **What they write is real history:** events, pauses and outbox messages, all append-only (DAT-01).
   - The first start recorded the line paused for want of a SKU, with one "SKU unavailable" alert, unrouted.
   - A TEST email waiting since 1 Oct became a permanent failure: email isn't set up. An Administrator can
     re-drive it once the relay is set.
3. **The configuration is the owner's to save, under their own account on :5173** (permanent, audited):
   - a mapping version with the placeholder SKU `PLACEHOLDER` (ADR-0022);
   - `PLACEHOLDER` in the SKU list;
   - a rules version from the Phase 0 proposal, the accepted delays and the proposed limits, replacing the test
     values, with the placeholder's targets filled from the current HMI setpoints (Timebase answers on this
     network). The Rules tab now offers "New version from the Phase 0 proposal" even when versions exist.
4. **The trial stays a separate thing.** It can run at the same time, with its own client ID and database.
   *(Removed on 2026-10-03 with the simulator demo, before the first push: the real application replaces it.)*

## Consequences

- **Alarms come only from the real line.** An Actual Warning or Critical needs the running machine to leave its
  band. Its rules pause while the machine is stopped (ADR-0010). An HMI mismatch needs a setpoint changed away
  from its target for 30 s. Nothing is simulated.
- **The targets are a snapshot of what ran when they were filled.** They stand until process engineering's
  targets replace them (ADR-0022): after a product change, every setpoint that moves raises a mismatch.
- **This is the development laptop, not the production host:**
  - the services run from the working session, and stop when it ends or the laptop sleeps (DEP-05 isn't met
    here);
  - the api stays on 127.0.0.1 until the HTTPS proxy exists.
- **G0b now gates only the control-room PC:** the host test and M7 there, before the system moves to it.
- **The real history now begins on this laptop.** Moving it to the control-room PC means moving this database
  with it, or starting there afresh. The owner decides when the time comes.

## Reset on 2026-10-02

- **The owner had the real database started over** the same day, to clear its test configuration:
  - three rules versions and three mappings, all saved as "test";
  - the SKU `LCM`, the accounts `szyrelle` and `sample`;
  - 63 audit entries and two messages.
- **First, a full backup:** `config/history/centerline-2026-10-02-before-reset.dump` (0600, `pg_dump -Fc`). It
  was restored into a scratch database to prove it: every count matched and the audit chain verified.
- **Then the database was dropped and recreated.** The api migrated it and imported the register file, which
  matched the last register version (2026-09-30.2). The old pre-database audit entries were imported as before.
- **`szyrelle` was created again** on the server's command line, with a temporary password.
- **Everything starts unconfigured:** no mapping, rules or SKUs. monitor-core waits for them.
- **Started over a second time** at the owner's request, after another verified backup:
  `config/history/centerline-2026-10-02-before-reset-2.dump`.
  - It held a mapping with the placeholder `123456`, three rules versions, and the owner's first test alarms:
    7 events and 11 messages.
  - `szyrelle` was created again. The api and monitor-core start from an empty configuration.

## Reset on 2026-10-06

- **The owner had the real database started over a third time**, to test from the start without the SKU
  (ADR-0027). It held:
  - three rules versions and two mappings;
  - 14 events, 27 messages and 29 audit entries;
  - the account `szyrelle`.
- **First, a full backup:** `config/history/centerline-2026-10-06-before-reset.dump` (0600). It was restored into a
  scratch database to prove it: every count matched, the audit chain verified, and the scratch copy was dropped.
- **The owner dropped and recreated the database** with the command they were given: the permission check doesn't
  let the assistant drop the real database.
- **The api migrated it and imported the register file:** 2026-10-05.1, without the SKU entry. The two old
  pre-database audit entries (the MQTT broker, 2026-09-30) were imported as before.
- **`szyrelle` was created again** on the server's command line, with a temporary password the owner replaced at
  first sign-in.
- **The owner configured it again from :5173 the same morning:**
  - mapping v1, all 30 tags, filled from the broker;
  - rules v1 to v3: v3 gives the zones their targets.
