# ADR-0024: A read-only look at the real machine from the development laptop, before G0b

- **Status:** Superseded by [ADR-0026](ADR-0026-real-app-on-the-real-machine.md): the real application now judges the
  real machine. The trial and its script (`deploy/demo/`) were removed on 2026-10-03, before the first push.
  Decision 2 had been extended by the owner on 2026-10-02: the trial gave the placeholder targets
- **Date:** 2026-10-01
- **Decider:** the system owner, in the working session ("yes, I want to see the actual value")
- **Amends:** [ADR-0021](ADR-0021-g0b-revised.md) for this trial only: G0b still gates connecting the real
  Centerline to the plant broker
- **Related:** [ADR-0006](ADR-0006-mqtt-acquisition.md) (M6: subscribe only),
  [ADR-0020](ADR-0020-database-roles.md), [ADR-0022](ADR-0022-placeholder-sku.md) (the placeholder SKU)
- **URS:** OPC-01, OPC-08, SEC-02

## Context

- **The owner wants to see the real machine's actual values** on the Digital Centerline page now. The
  demo on the simulator (`deploy/demo`) shows everything working, but on made-up values.
- **G0b asks for the control-room PC test (and M7) first** before connecting to the real broker. The
  owner chose not to wait for it for this look.

## Decision

1. **A trial on this laptop, started with `deploy/demo/demo.py start --plant`.**
   - monitor-core subscribes to the plant broker saved on the real Configuration page, with the
     shared account. It only subscribes: its client can't publish or leave a Last Will (M6, tested).
   - It uses its own client ID, so it can't take over anyone else's connection.
   - The password stays where it is in `config/secrets`; the trial refers to that file and never
     copies it.
2. **What it judges:**
   - the real mapping in effect, copied with the placeholder SKU, so the actual values are judged
     (ADR-0022);
   - the Phase 0 rules proposal: the accepted delays and the proposed limits;
   - since 2026-10-02, the placeholder's targets (owner: show and judge, ADR-0022 amended):
     - on its first start with no targets, the trial adds the placeholder to its SKU list;
     - it saves a rules version whose targets are each zone's HMI setpoint at that moment;
     - so the Digital Centerline page shows each zone's target, and HMI mismatch is judged against it;
     - they're edited on the trial's Configuration → Rules.
3. **Kept apart:**
   - its own database (`centerline_plant_trial`), so none of its events become real history;
   - its own api on 127.0.0.1:8011, and the web app on :5175;
   - no notifier, so no message is sent.
   `demo.py reset --plant` deletes its database and files.
4. **It needs the laptop on the plant network.** It checks that the broker answers before starting,
   and refuses otherwise.

## Consequences

- **The owner sees the real values judged on the live page**, with the placeholder SKU's limits:
  Warnings and Criticals against each setpoint, and the machine's stops pausing the Actual rules.
- **The trial's events aren't evidence:** they live in the trial's database only. The real Centerline
  still waits for G0b and runs on the control-room PC.
- **The shared account is used from this laptop**, as the probe did on 2026-09-30 (ADR-0021 accepted
  that risk for now).
- **First start on 2026-10-01:** the laptop was on another Wi-Fi, from which neither the broker nor
  Timebase answers. The trial is ready for when it's on the plant network.
