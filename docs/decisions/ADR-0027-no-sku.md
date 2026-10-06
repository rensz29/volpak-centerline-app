# ADR-0027: No SKU: the rules give each zone its limits and its target

- **Status:** Accepted
- **Date:** 2026-10-05
- **Decider:** Szyrelle (system owner). First asked on 2026-10-02: remove the SKU completely, and make monitoring
  rely on the rules alone. That work was set aside when the configuration was reset again. Confirmed on
  2026-10-05: leave the SKU out of the code, the plan and the architecture.
- **Supersedes:** [ADR-0001](ADR-0001-sku-changeover.md) (the SKU changeover) and
  [ADR-0022](ADR-0022-placeholder-sku.md) (the placeholder SKU)
- **Amends:**
  - [ADR-0007](ADR-0007-parameter-register.md): no SKU entry in the register; O-15 dropped.
  - [ADR-0008](ADR-0008-analytics-on-timebase.md): no SKU filter in Analytics.
  - [ADR-0012](ADR-0012-rules-configuration-postgresql.md): targets per zone, not per SKU and zone.
  - [ADR-0013](ADR-0013-tag-mappings.md): a mapping names only tags.
  - [ADR-0014](ADR-0014-monitor-core.md): what the snapshot gate checks.
  - [ADR-0021](ADR-0021-g0b-revised.md) decision 1: the SKU field isn't deferred but dropped.
  - [ADR-0026](ADR-0026-real-app-on-the-real-machine.md) decision 3: no placeholder in the configuration.
- **URS:** OPC-01, OPC-05, OPC-08, HMI-05, ANA-05, ANA-10, §11.1, AT-ANA-01; the SDD's assumptions A-01 and A-06.
  See the change request below.

## Context

- **The SKU was meant to pick each zone's targets.** The machine was to publish the running SKU (O-15), and a
  rules version gave every SKU its target per zone (ADR-0012). A change of SKU closed the open events
  (ADR-0001).
- **The machine doesn't publish one**, and the owner deferred the field (ADR-0021). The SKU ended up being one
  of these, and none of them is a product:
  - a placeholder code in the mapping (ADR-0022);
  - an entry in the SKU list that matched it;
  - SKU rows in the rules that held the targets.
- **It confused more than it helped.** Setting up the real application meant entering the same code in three
  places, on two tabs. The owner asked for it to go, so that monitoring relies on the rules alone.

## Decision

1. **Centerline has no SKU.** Nothing below this point mentions it any more.
   - No SKU list on the Rules tab, and no SKU field or placeholder in a mapping.
   - Events, brief changes, messages, the live page, the Alarms pages and the reasons don't carry one.
   - Analytics has no SKU filter.
   - The register has no SKU entry. The api saves a register version without it at start-up, audited as any
     register change.
   - The simulator, the MQTT probe and the Timebase analyses no longer look for one.
2. **A rules version gives each zone its limits, delays and target.**
   - Each field resolves as this zone > every zone of the parameter > the line's defaults.
   - The editor has a **Targets by zone** table, which keeps "Fill empty targets from current HMI
     setpoints" as a starting point to check against the centerline sheet.
3. **The line is judged once every zone has its four limits.**
   - Until then the gate stays closed and gives the reason. Management gets one system message per pause
     ("Rules incomplete", OPC-08 as amended below).
   - A target is optional, zone by zone. A zone without one has its actual value judged against its setpoint
     as usual. Its HMI setpoint isn't judged, and the live page shows "Not judged".
4. **Nothing happens on a product change.**
   - No event closes as a changeover, and no changeover message is sent.
   - A product change that moves setpoints raises HMI mismatches against the targets in effect, until a
     Manager activates a version with the new product's targets. This is the risk ADR-0022 named for the
     placeholder's targets. It now applies to every target.
   - The Actual rules follow the setpoints, so they need nothing on a product change.
5. **What was saved about SKUs stays as history** (migration `0011`, DAT-01).
   - The SKU list's table is dropped. Its entries stay in the audit log.
   - `sku_parameter_rule` becomes `parameter_rule`. The SKU columns of rule rows, mappings, events and brief
     changes become `legacy_*`.
   - New rows can't fill those columns. Neither can a new transition `CLOSED_SKU_CHANGEOVER` or a new message of
     kind `changeover`. The checks are `NOT VALID`, so earlier rows keep what they hold.
   - Rule rows saved for a SKU stay in their version and its fingerprint, so every saved version still
     verifies. They judge nothing.
   - **Edit as new** on such a version starts from that SKU's rows as the zones' own rows, its targets
     included. It takes the SKU with the most rows if there were several. The version view says so.
   - Earlier events keep their SKU and their pinned rule. The pages show `CLOSED_SKU_CHANGEOVER` as
     "Closed: changeover (before ADR-0027)".

## URS change request (owner to raise)

"Today" is the wording of URS v1.1 (consolidated draft), or of [ADR-0006](ADR-0006-mqtt-acquisition.md)'s change
request where that already replaces it.

| URS | Today | Proposed |
|---|---|---|
| OPC-01 | "Subscribe to the machine's MQTT area topics for the SKU field and every monitored zone's setpoint and actual (parameter register) with a subscribe-only account." (ADR-0006) | Subscribe to the machine's MQTT area topics for every monitored zone's setpoint and actual (parameter register) with a subscribe-only account. |
| OPC-05 | "After reconnect, require a live message from every mapped area, all monitored fields valid and a valid SKU, before evaluation resumes." (ADR-0006) | After reconnect, require a live message from every mapped area and all monitored fields valid before evaluation resumes. |
| OPC-08 | "If SKU is unavailable, pause all parameter evaluation and timers, preserve open events, alert Management and resume only after a fresh valid snapshot." | If the rules in effect don't give every monitored zone its Warning and Critical limits, pause all parameter evaluation and timers, preserve open events, alert Management once and resume only after a fresh valid snapshot. |
| HMI-05 | "Default brief-change mode is Lightweight record; Managers may select Do not record, Lightweight, or Cleared-before-trigger by SKU/parameter." | … by parameter or zone. |
| ANA-05 | "Require one SKU; shift is optional as All shifts or one historian shift. Historical SKU and shift are filters/context only." | Shift is optional as All shifts or one shift derived from the timestamp (ADR-0008); there is no SKU filter. |
| ANA-10 | "Use separate Analytics-valid engineering ranges, not SKU alarm limits. …" | Use separate Analytics-valid engineering ranges, not the monitoring limits. … |
| §11.1 | "Select SKU, optional shift, date/time, X, Y, bucket, aggregation and grouping; …" | Select optional shift, date/time, X, Y, bucket, aggregation and grouping; … |
| AT-ANA-01 | "Verify only 11 actual parameters, required SKU, optional shift and different X/Y selection." | Verify the allowed variables (ADR-0009), optional shift and different X/Y selection. |

The URS's own OPC-01, OPC-05 and AT-01 count a SKU tag among "23 tags" (one SKU, 11 setpoints, 11 actuals). ADR-0006's
proposals already replace them with the register's zones; the rows above take the SKU out of those proposals. HMI-01
doesn't mention the SKU, so it stands. The SDD's assumptions A-01 and A-06 are updated in
[ARCHITECTURE.md §17](../ARCHITECTURE.md#17-assumptions-and-open-decisions-to-close).

## Consequences

- **The targets are the line's, not a product's.** One set judges whatever runs. When a product needs other
  targets, a Manager activates another version. Activation can be scheduled for the changeover time.
- **Configuring the real machine takes two tabs:** the mapping (Administrator) and the rules (Manager).
- **The real database after migration 0011**, checked on 2026-10-05 after a verified backup
  (`config/history/centerline-2026-10-05-before-no-sku.dump`):
  - rules v3, in effect, gives every zone its limits, so the line is judged;
  - none of its 14 zones has a target of its own: the targets were SKU `12345`'s, so HMI is "Not judged";
  - "New version from v3" carries those targets over, and activating it judges the HMI setpoints again;
  - every saved version still matches its fingerprint, and the audit chain verifies.
- **The URS and the SDD still mention the SKU** until the owner raises the change request above.

## Verification

- `test_rules_unit.py`:
  - zone > parameter > defaults;
  - rows saved for a SKU ignored;
  - the carry-over;
  - readiness and the limits check.
- `test_rules_api.py`: the gaps, and the legacy carry-over.
- `test_mapping_api.py`: a mapping names only tags; the database refuses a SKU.
- `test_monitor_engine.py`:
  - incomplete rules pause the line and alert once;
  - a zone without a target is judged on its actual value only.
- `test_db.py`: migration `0011` in order.
- Client: `npm run lint` and `npm run build`.
