# ADR-0009: Setpoints in Analytics; zone names instead of parameter IDs

- **Status:** Accepted
- **Date:** 2026-09-29
- **Decider:** Szyrelle (system owner)
- **Amends:** [ADR-0008](ADR-0008-analytics-on-timebase.md) decision 7 (variables)
- **URS:** ANA-01, ANA-04, AT-ANA-01. They limit X and Y to actual values, so **a URS change request is needed**

## Context

ADR-0008 offered only actual values as X or Y, as ANA-04 requires ("Only the 11
actual-value parameters may be X or Y variables"). The owner wants two changes:

- **Setpoints available as well.** Setpoint against actual shows whether a zone
  holds its setpoint, and when the setpoint was changed.
- **The picker listing zones by name** (Vertical 1, Vertical 2, …) instead of
  "P02 · Vertical 1".

## Decision

1. **Every zone offers its actual value and, where the register has one, its
   setpoint.** Today that's 29 variables: 14 zones × 2, plus P08 Machine Speed,
   which has no setpoint tag.
2. **Channel IDs** become `<parameter>.<zone>.actual` and
   `<parameter>.<zone>.setpoint`, e.g. `P02.V1.setpoint`. A bare zone channel
   (`P02.V1`, the form before this ADR) still means the actual value, so older
   links keep working.
3. **People see zone names, never parameter IDs.**
   - The picker lists zones by name, grouped under the parameter name
     ("Vertical Temperature (°C)").
   - An **Actual / Setpoint** toggle sits beside each picker; its Setpoint side
     is disabled for zones without a setpoint tag.
   - Charts, captions, cards and warnings use labels such as
     "Vertical 1 · Setpoint". The api builds the label, so there's one wording.
4. **Everything else is unchanged.** Setpoints go through the same pipeline:
   - they hold until the next sample, because Timebase stores on change;
   - machine silences count as gaps;
   - the Analytics-valid ranges of their parameter apply;
   - same buckets and statistics.
5. **In Trend, a setpoint is drawn dashed and on top**, so it stays visible where
   the actual tracks it.
6. **X and Y must still differ.** Actual against setpoint of the same zone is
   allowed.

## Consequences

- **Setpoints are usually constant for hours.** A setpoint that doesn't change in
  the range gives "Not computable: X is constant", which is correct. Trend is
  then the useful view.
- **P09 cautions apply to both of its variables** (O-19: the tags look swapped),
  shown once per result.

## URS change request (owner to raise)

| URS | Current | Proposed |
|---|---|---|
| ANA-01 | Analytics page for the 11 actual-value parameters | Analytics page for the actual values and setpoints of the register's zones |
| ANA-04 | Only the 11 actual-value parameters may be X or Y; X and Y differ | Any zone's actual value or setpoint may be X or Y; X and Y differ |
| AT-ANA-01 | Verify only 11 actual parameters, required SKU, optional shift, different X/Y | Verify the register's actual and setpoint variables, optional SKU until the tag exists (ADR-0008), optional shift, different X/Y |
