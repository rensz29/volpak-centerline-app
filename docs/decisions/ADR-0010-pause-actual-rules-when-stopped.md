# ADR-0010: Pause Actual rules while the machine is stopped

- **Status:** Accepted
- **Date:** 2026-09-29
- **Decider:** Szyrelle (system owner)
- **Closes:** O-20
- **URS:** ACT-01…04, MON-01, MNT-01. The URS doesn't mention machine stops, so **a URS change request is needed**
- **Related:** [ADR-0002](ADR-0002-default-delays.md) (delays and proposed limits)

## Context

The Phase 0 analysis replayed 28 days of Timebase history (1–28 Sep 2026) with
Actual limits proposed from routine running. Three findings:

- **The machine stops and starts about 100 times a day.** Most stops are short;
  some last hours.
- **During longer stops the zones cool down.** Temperatures fall towards
  30 °C, far outside any Critical limit.
- **With Actual rules running at all times**, the line would raise about
  **66 Warnings and 16 Criticals a day** at a 30 s delay. 90 % of the Criticals
  would start while the machine is stopped. Each Critical notifies at once and
  repeats every 15 minutes until a Manager acknowledges it (ACT-04), so every
  long stop would flood Teams and email.

## Decision

1. **Actual Warning/Critical rules run only while the machine runs.** A
   machine counts as running when `SPC.Machine_Run` = 1 (a register context
   tag, now a monitoring input).
2. **After a stop of 10 minutes or more, the first 30 minutes of running are a
   warm-up** and aren't judged. Short stops (jams) don't cool the zones, so
   rules resume at once after them. Both durations are configuration.
3. **While paused, Actual rules behave like the snapshot-gate pause** (OPC-03):
   - evaluation and their timers stop, including Critical repeats;
   - open Actual events stay open;
   - evaluation restarts from fresh values when the pause ends.
4. **HMI setpoint-mismatch monitoring is unaffected.** It continues while the
   machine is stopped.
5. **If `Machine_Run` itself is stale or missing**, the snapshot gate pauses
   everything, as for any other monitored field.

## Evidence (28 days, proposed limits, whole line)

| Actual rules | Warnings / day at 30 s | Criticals / day at 30 s | Criticals / day at 10 s |
|---|---|---|---|
| At all times (URS as written) | 66.4 | 16.1 | 19.3 |
| Paused while stopped, 30 min warm-up after stops ≥ 10 min | **6.9** | **2.1** | **4.0** |

## Consequences

- Monitoring stays quiet during stops and warm-ups, when deviations are
  expected rather than faults.
- **A real fault during a stop isn't flagged by the Actual rules**, for example
  a heater that fails to switch back on. It shows up once the warm-up ends. If
  that's too late, a later ADR can add a warm-up check, such as "not at
  setpoint within N minutes of starting".
- The monitoring engine now also needs `Machine_Run` in its snapshot.

## URS change request (owner to raise)

| URS | Proposed addition |
|---|---|
| ACT-01 | Actual Warning/Critical rules apply only while the machine is running. They pause while it is stopped and for a configurable warm-up (default 30 min) after stops of at least a configurable duration (default 10 min). |
| ACT-04 | Critical repeat notifications pause while Actual rules are paused. |
