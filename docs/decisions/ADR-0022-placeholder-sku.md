# ADR-0022: A placeholder SKU, judged on actual values (and on HMI where it has targets), until the machine publishes its SKU

- **Status:** Accepted. Decision 2 amended by the owner on 2026-10-02: targets given to the placeholder are judged
- **Date:** 2026-10-01
- **Decider:** Szyrelle (system owner)
- **Amends:** [ADR-0013](ADR-0013-tag-mappings.md) (a mapping version may name a placeholder instead of the SKU
  field) and [ADR-0021](ADR-0021-g0b-revised.md) decision 1 (what the real machine shows without the field)
- **Related:** [ADR-0001](ADR-0001-sku-changeover.md) (changeover), [ADR-0002](ADR-0002-default-delays.md)
  (the limits), [ADR-0007](ADR-0007-parameter-register.md) (O-15), [ADR-0014](ADR-0014-monitor-core.md) (the gate)
- **URS:** OPC-01, OPC-08, HMI-01, ACT-01…04

## Context

- **The SKU field isn't ready** (O-15), and the owner deferred it (ADR-0021). Without it
  monitor-core judges nothing: the gate stays closed (OPC-08).
- **The SKU does two jobs:**
  - It picks the **targets**. HMI mismatch compares each HMI setpoint with the SKU's target,
    which needs process engineering's numbers.
  - Through the SKU, it also picks the **limits**. Actual Warning and Critical are offsets
    around the HMI setpoint itself (A-02). The proposal has limits for every zone and every
    SKU, measured on 28 days of history (ADR-0002).
- **So the actual values can be judged without a SKU.** That catches a heater, a nozzle or
  the pressure drifting from its setpoint. Only HMI mismatch needs the real SKU.

## Decision

1. **A placeholder SKU code can stand in for the SKU field.**
   - The Administrator sets it on the Mappings tab: a mapping version has the machine's SKU
     field, or a placeholder, never both (migration `0007` enforces it).
   - The code follows the SKU list's format, e.g. `PLACEHOLDER`. It goes into the version's
     content hash, so versions saved earlier keep their hashes.
   - The CSV export leaves it out: it isn't a place on the broker.
2. **Under the placeholder, only actual values are judged** (owner's choice, 2026-10-01).
   - Warning and Critical work as usual, against each zone's setpoint with the limits in
     effect.
   - HMI mismatch isn't judged: there's no target. The live page shows "Not judged".
   - The placeholder needs no entry in the SKU list and no targets. The rules in effect
     must give every zone its limits, as the Phase 0 proposal does. Otherwise the gate says
     so and Management gets the usual single alert (OPC-08).
   - Not chosen: placeholder targets typed in by a Manager. On a different product they
     would raise false mismatch events.

   **Amended 2026-10-02 (owner: show and judge).** A zone the Rules tab gives a target for
   the placeholder is judged on its HMI setpoint too, like any SKU's. Its HMI mismatches open
   events, notify and ask the operator for a reason.
   - To give it targets, a Manager adds the placeholder's code to the SKU list and fills them
     in. "Fill empty targets from current HMI setpoints" starts them from what runs now.
   - A zone without a target stays as above: its HMI setpoint isn't judged, and the live page
     says "Not judged". The SKU list shows the placeholder as not ready until every zone has
     one, though the line is judged meanwhile.
   - The plant trial (ADR-0024) gave the placeholder its targets once: each zone's HMI
     setpoint when the trial first started. The trial was removed on 2026-10-03.
   - The risk named above remains, so Managers must keep the targets current: after a
     product change, every setpoint that moves raises a mismatch against the old targets
     until they're updated.
3. **It's visible wherever it matters.**
   - Events and notifications carry the code as their SKU, and the rule pinned to each
     event says `sku_placeholder: true`.
   - The live page says "Judging actual values under the placeholder SKU …".
   - The Mappings tab and the version view name it.
4. **When the machine publishes its SKU:**
   - The Administrator maps the field in a new mapping version. monitor-core then waits for
     the SKU's next message: no false "SKU unavailable" alert in between.
   - The new SKU differs from the placeholder, so this is an ordinary changeover
     (ADR-0001). Open events close as "SKU changeover" with no recovery notice, Management
     gets one changeover message, and judging resumes on a fresh snapshot with HMI mismatch
     back.

## Consequences

- **The real machine can be judged** once G0b allows connecting (the control-room PC test
  and M7), without waiting for the edge team.
- **HMI mismatch is the gap** without targets. An operator changing a setpoint away from the
  standard isn't caught until the placeholder has targets (since 2026-10-02) or the SKU field
  and process engineering's targets exist.
- **Events under the placeholder don't say which product ran.** The Analytics SKU filter
  can't use them either.
- **URS change request (owner to raise):**

  | URS | Today | Proposed addition |
  |---|---|---|
  | OPC-08 | Without a valid SKU, monitoring pauses | Unless the Administrator has set a placeholder SKU: then actual values are judged against their setpoints, and HMI mismatch waits for the SKU |

## Tests

- `services/monitor_core/tests/test_monitor_placeholder.py`:
  - actual values judged and HMI not, under the placeholder, with the status the page reads;
  - the placeholder's targets judge their zones' HMI setpoints, and only theirs (amendment);
  - missing limits keep the gate closed, with one alert;
  - mapping the field later ends in a changeover, with no false alert;
  - the pinned rule survives a restart;
  - monitor-core reads the placeholder from the mapping in effect.
- `services/monitor_core/tests/test_monitor_e2e.py`: a simulator without a SKU field, on a
  local Mosquitto, is judged under the placeholder end to end.
- `services/api/tests/test_mapping_api.py`:
  - the field and a placeholder together, or a malformed code, are refused;
  - a placeholder version saves, activates, reads back intact and is audited;
  - it's left out of the CSV;
  - the database refuses both even from the owner.
