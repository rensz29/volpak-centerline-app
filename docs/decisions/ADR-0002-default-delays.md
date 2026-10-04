# ADR-0002 — Default mismatch, Warning and Critical delays

- **Status:** Accepted on 2026-10-01: the owner accepted the delays measured on 28 days (1–28 Sep 2026); see [Acceptance](#acceptance-2026-10-01). The proposed limits aren't part of it: they wait for process engineering. Both are the Rules tab's starting proposal (`db/seed/rules-proposal.json`, [ADR-0012](ADR-0012-rules-configuration-postgresql.md))
- **Date:** 2026-09-28; accepted 2026-10-01
- **Decider:** Szyrelle (system owner)
- **Closes:** O-08 (closed 2026-10-01)
- **URS:** HMI-02, HMI-05, ACT-01…04, CAP-01

## Context

The URS gives a default only for the **Recovery delay (15 s, ACT-02)**, and
says the Critical → Warning downgrade uses the Warning delay. The HMI mismatch,
Warning and Critical delays are unspecified. Too short, and every
routine panel tweak becomes an event with an Operator workflow. Too long, and
real drift goes unreported. Choose them from measured plant behaviour, not
guesswork.

## Decision

1. **All delays are configuration.** Each has a global default plus an optional
   override per SKU × parameter, versioned in `config_version` like every other
   rule. None is a code constant.
2. **Defaults are chosen from 2–4 weeks of Timebase history** using
   [`tools/timebase-analysis`](../../tools/timebase-analysis/README.md). The
   tool replays the SDD rules (integer truncation, restart on a new integer,
   boundaries to the milder state) against each candidate delay.
3. **Selection rule:** take the smallest candidate where line-wide events per
   day stop falling sharply (the tool's "knee": a longer delay removes less
   than 10 % more events) and that stays well inside CAP-01. Adjust a single
   parameter only when its own table clearly differs. Leave out zones whose
   setpoint behaves like a live value (more than 100 changes a day).
4. **Until the analysis runs**, Phase 1 development and tests use the
   placeholders below. They're marked `PLACEHOLDER` in the seed data and must
   not reach production.

| Delay | Placeholder | Measured (28 days, 1–28 Sep) | Accepted (2026-10-01) |
|---|---|---|---|
| HMI mismatch | 30 s | Knee at 10 s; 10–30 s give the same result: 21.8 vs 20.9 events a day for the line (936 dwells; 13 zones, P09 left out for O-17/O-19). The 7-day run agreed | **30 s**, for margin against late messages |
| Warning (Normal → Warning) | 30 s | 6.9 Warning events a day at 30 s, 27.4 at 10 s. No clear knee: events keep falling as the delay grows | **30 s** |
| Critical (→ Critical) | 10 s | 4.0 Critical events a day at 10 s, 2.1 at 30 s | **10 s**, to react fast; the count stays small |
| Warning downgrade (Critical → Warning) | 30 s | Same as Warning | **30 s** |
| Recovery (→ Normal) | **15 s** | URS default (ACT-02); configurable | **15 s** |

The Warning and Critical figures use the proposed limits below. Actual rules
are paused while the machine is stopped and for 30 min after stops of 10 min
or more ([ADR-0010](ADR-0010-pause-actual-rules-when-stopped.md)). Without that
pause the line would raise 66 Warnings and 16 Criticals a day at 30 s.

### Proposed Actual limits, for process engineering to confirm

Offsets around the setpoint (A-02), derived by `propose_limits.py` from routine
running:
- the machine running, excluding 30 min of warm-up after stops of 10 min or
  more, and 15 min after each setpoint change;
- Warning at the 0.25th / 99.75th percentile of (actual − setpoint), rounded
  outward to 1 °C or 0.05 bar;
- Critical at twice the Warning offset.

| Parameter | Routine hours | Warning (−/+) | Critical (−/+) |
|---|---|---|---|
| P02 Vertical Temperature | 2,184 | −2 / +1 °C | −4 / +2 °C |
| P03 Bottom Temperature | 728 | −5 / +5 °C | −10 / +10 °C |
| P04 Top Temperature | 726 | −10 / +9 °C | −20 / +18 °C |
| P06 Discharge Point | 957 | −9 / +9 | −18 / +18 |
| P09 Pressure | 41 | −0.05 / +0.05 bar | −0.1 / +0.1 bar (tags under review, O-19) |

These describe how the process normally behaves, not what the product can
tolerate. Process engineering should widen or tighten them where quality
requires. The vertical zones, for instance, hold within about ±0.1 °C during
steady running.

## Acceptance (2026-10-01)

- **The owner accepted the delays** in the table above: HMI mismatch 30 s, Warning 30 s,
  Critical 10 s, Warning downgrade 30 s, Recovery 15 s. They equal the placeholders, so no
  seed value changes.
- **Evidence:** `tools/timebase-analysis/data/delay-report.md` (plant data, kept out of git).
- **The limits aren't part of it.** They stay proposed until process engineering confirms or
  changes them (Phase 0 task 0.3).
- **In effect:** the delays apply once a rules version with them is activated on the Rules
  tab. The proposal the first version starts from already has them. Nothing is judged on
  the real machine until the SKU field exists ([ADR-0021](ADR-0021-g0b-revised.md)).

## Procedure

1. Fill in `tools/timebase-analysis/config.json` (URL, dataset, auth). The tags come from `config/parameter-register.json`.
2. `python probe.py config.json`, then check all tags exist.
3. `python fetch.py config.json <from> <to>`, covering 2–4 weeks with changeovers.
4. `python analyse_delays.py config.json` for the mismatch delay.
5. `python propose_limits.py config.json`, then have process engineering review
   `data/limits-proposed.csv` and adjust it.
6. `python analyse_delays.py config.json --limits <limits.csv> --running-only`
   for the Warning/Critical delays under ADR-0010.
7. Copy the chosen values into the table above, attach `delay-report.md`
   (outside git, it's plant data), and change the status to **Accepted**.

## Consequences

- One Timebase download settles the defaults for all 11 parameters. Re-run the
  analysis after the first month in production to confirm them.
- If changeover dwells (reported separately) exceed the chosen mismatch delay,
  every changeover will raise a burst of mismatch events. Decide then between a
  longer delay and a per-SKU changeover grace period, and amend
  [ADR-0001](ADR-0001-sku-changeover.md).
