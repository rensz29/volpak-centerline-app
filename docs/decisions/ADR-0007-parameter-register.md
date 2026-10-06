# ADR-0007: Parameter register with zones; SKU from the machine payload

- **Status:** Accepted. P09 items O-17 and O-19 are open. Decision 1 amended by
  [ADR-0012](ADR-0012-rules-configuration-postgresql.md): the database holds the register, and the file is its export.
  Amended by [ADR-0027](ADR-0027-no-sku.md) (2026-10-05): the register has no SKU entry, and O-15 is dropped
- **Date:** 2026-09-29
- **Decider:** Szyrelle (system owner)
- **Adds:** O-15, O-16, O-17, O-19
- **URS:** OPC-01, OPC-08, HMI-01, ACT-01, ANA-01, AT-ANA-01, A-01, A-11

## Context

- The URS lists P01–P11, each with one setpoint and one actual. The machine
  has **several zones per parameter**, each with its own setpoint:
  Vertical 1–6, Top Front/Rear, Bottom Front/Rear, Nozzles 1–3.
- Timebase has **no SKU or recipe tag for the Volpak**. Only the process lines
  have `SKU_Code`.
- The machine tag list covers P02, P03, P04, P06 and P09.
  - `SPC.Feed` (P10) and `SPC.Film_Reel` (P11) appeared in Timebase on
    2026-09-29 at 02:26 UTC, one tag each.
  - P01, P05, P07 and P08 have no tags. `Machine_Speed` exists, but only as an actual.

## Decision

1. **One register file.** [`config/parameter-register.json`](../../config/parameter-register.json)
   is the single source of truth. The Phase 0 tools read it, and Phase 1 seeds
   it into the database as versioned configuration.
2. **Zones under URS parameters.** Parameters keep their URS IDs. A zone is one
   setpoint/actual pair with channel ID `<parameter>.<zone>`, e.g. `P02.V3`.
   - **Each zone has its own state machines, events, workflow requests and
     notifications**, so an event says which zone drifted.
   - Targets, limits, delays and brief-change mode are set **per parameter with
     an optional per-zone override**.
3. **Scope: monitor what the machine publishes today.** That's 14 zones across
   P02, P03, P04, P06 and P09. P01, P05, P07, P08, P10 and P11 stay in the
   register as `awaiting_tag` and join when their setpoint/actual pairs exist.
4. **SKU from the machine payload.** The edge/UNS team adds the running
   SKU/recipe as a field in the machine's MQTT message. Until it exists, the
   real machine can't be monitored: OPC-08 pauses evaluation when the SKU is
   missing. Development and G1 use `tools/mqtt-sim --sku-field`.
5. **HMI comparison rule per parameter.** The default is the URS rule (truncate
   to whole numbers, HMI-01). The register can set a different method and
   number of decimals for one parameter. All parameters use the default for
   now; P09 is under review (O-17).

## Evidence: 7 days of Timebase history, 22–28 Sep 2026

`tools/timebase-analysis`, shift runs (no SKU yet), targets inferred per shift:

| Parameter | Zones | Setpoint changes / day | Off-target dwells / day | Knee of the delay curve |
|---|---|---|---|---|
| P02 Vertical Temperature | 6 | 36.3 | 16.6 | 10 s |
| P03 Bottom Temperature | 2 | 12.0 | 5.4 | 10 s |
| P04 Top Temperature | 2 | 13.3 | 6.4 | 10 s |
| P06 Discharge Point | 3 | 11.9 | 11.3 | 5 s |
| P09 Pressure (as named) | 1 | **21,013.6** | **1,614.0** | none |
| P09 Pressure, tags swapped, 1-decimal rule | 1 | 34.4 | 21.0 | 30 s |

Without P09, the line raises **27.9 events a day at a 10 s delay and 27.3 at
30 s**, far inside CAP-01's 1,000 a day. P09 as named would create about
21,000 lightweight records a day on its own, twice CAP-01's 10,000.

## Open items

| ID | Item | Owner |
|---|---|---|
| O-15 | SKU/recipe field published in the machine payload | Edge/UNS team |
| O-16 | Missing tags: P01, P05, P07; P08 setpoint; P10 actual; P11 setpoint | Edge/UNS team, OT |
| O-17 | P09 comparison rule: whole numbers can't tell 1.2 from 1.3 bar. Proposed: 1 decimal (deviates from HMI-01) | Owner |
| O-19 | P09 tags look **swapped**: `Pressure_Setpoint` behaves like a sensor (213 values, 0 when stopped), `Pressure_Actual` like an operator setting (clean one-decimal values). Confirm on the HMI screen, then fix at the edge (preferred) or swap in the register | OT, then owner |

## Consequences

- **More tags than the URS.** 14 zones means 28 tags plus the SKU field, against
  22 in the URS. The load is still trivial.
- **Data model.** A `parameter_zone` table joins `parameter`. Events, workflow
  requests, rules and Analytics selections carry `zone_id`.
- **UI.** The Digital Centerline table shows one row per zone, grouped by
  parameter; alarm cards say "P02 Vertical Temperature, Vertical 3".
- **Analytics.** X and Y are chosen from active zones. That changes ANA-01
  ("the 11 actual-value parameters") and AT-ANA-01 ("only 11 actual
  parameters") to "active zones in the register", which needs a URS change
  request alongside ADR-0006's.
- **Real-machine gate.** G0b now needs the SKU field (O-15) as well as the
  ADR-0006 controls.
