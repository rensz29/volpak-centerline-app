# ADR-0029: Analytics-valid ranges as versions, and G4's acceptance suite on an independently calculated dataset

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decider:** Szyrelle (system owner), on 2026-10-06: proceed with Phase 4's close-out, as the plan describes it
- **Amends:** [ADR-0008](ADR-0008-analytics-on-timebase.md) (the ranges file named in the api config)
- **Related:** [ADR-0009](ADR-0009-setpoints-in-analytics.md) (setpoints as variables), [ADR-0012](ADR-0012-rules-configuration-postgresql.md)
  (versions and activations), [ADR-0028](ADR-0028-polling-idempotency-g2-acceptance.md) (the acceptance suites)
- **URS:** ANA-10, ANA-11; AT-ANA-01…10 (gate G4)

## Context

- **G4 needed two things** (SDD §16). One is ANA-11: "version the active range file, retain original CSV/hash, validate
  units/min/max/completeness, require Administrator reason and preserve rollback/audit". The other is AT-ANA-01…10,
  passing "on an independently calculated dataset".
- **The ranges were a file named in the api config.** It was checked as a whole and identified by its SHA-256, but it
  had no versions, no reason and no rollback. They waited for the database. The real api config names no file, so
  no ranges were applied.
- **Analytics had unit tests for each rule,** and one check of r against `statistics`, but no acceptance suite.

## Decision

1. **The ranges are versions in the database** (migration `0013`), like the rules, mappings and routing.
   - An Administrator uploads the CSV on Configuration → **Analytics ranges**: one row per register parameter,
     `parameter_id, unit, valid_min, valid_max`.
   - The file is accepted or rejected as a whole:
     - every parameter once;
     - the register's unit;
     - finite numbers, with min below max.
   - An accepted file is a version: the file kept byte for byte as uploaded (sent as base64), its SHA-256, the
     register version it was checked against, the reason and who saved it. Its rows are kept beside it.
   - It takes effect now or at a set time, and an older version again is a rollback. Every step is audited, and
     nothing is changed or deleted.
   - Managers read the tab and Administrators change it (ADR-0016). Saving needs an `Idempotency-Key` (ADR-0028).
   - The tab offers a template, built from the register, and each version's original file for download.
   - Queries use the version in effect, checked against the register as it is now. If the register has changed
     so that it no longer fits, it isn't applied, and every result says so (`RANGES_REJECTED`). Each result names
     the version applied and each variable's range.
   - A range applies to the parameter's actual values and setpoints alike, inclusive at both ends.
   - The `analytics.ranges_csv` setting is retired. A leftover one is ignored, with a warning in the log.
2. **AT-ANA-01…10 run in `tests/acceptance/`** against a reference dataset in `tests/fixtures/analytics/`:
   - **`dataset.py`** generates two weeks of samples for Front bottom's temperature (°C, SPC) and the nozzle
     pressure (bar, Dosing_Parameters), seeded and on a 1/8 s grid. It has:
     - twelve production dates, two of them with small groups;
     - a dense two hours across a shift change, with one sample of each excluded kind;
     - a data gap.
   - **`independent.py`** calculates the expected results from the URS and SDD text. It uses Python's standard
     library only: exact fractions for times and 50-digit decimals for values. It shares no code with the api,
     which uses numpy and 64-bit floats. 22 queries go into `expected.json`.
   - A stand-in Timebase serves the dataset and records every request. The suite compares each number the api
     returns with the expected one, within 10⁻⁹, and checks that `expected.json` is still what `independent.py`
     gives.
   - `expected-pairs-dense-PT1M-AVG.csv` lets anyone check the statistics in a spreadsheet: CORREL, SLOPE,
     INTERCEPT, RSQ, AVERAGE, STDEV.S.
3. **One correction the suite found.** A value in force until exactly the start of the range was still counted as
   a sample, together with its exclusion reason. It's never in force inside the range, so it no longer counts
   (ANA-09).
4. **The query log names who ran each query, and under which ranges version.** It still keeps only the query's
   description and counts, never the data (ANA-21).

## Consequences

- **G4 is met.** All ten AT-ANA suites pass on 2026-10-06: ANA-01…21.
- **Two parts remain checks in the browser:**
  - AT-ANA-06's look: the tooltips, zoom, pan and reset of the two tabs. The suite shows that both draw the same
    pairs, with gaps and two axes;
  - AT-ANA-10's wording on the page. The suite shows that every result carries it and the page renders it.

  "Future exports" (AT-ANA-10) wait for O-04.
- **No ranges are in effect on the real database yet.** Until process engineering gives each parameter's valid
  range, every result says that out-of-range samples aren't excluded (`NO_RANGES`).
- **The independent calculation is a second implementation by the same team.** The spreadsheet file is there for
  someone outside it to check the statistics.

## Verification

- `services/api/tests/test_ranges_api.py`:
  - the template;
  - whole-file rejection, the Administrator only, a reason required;
  - the file kept byte for byte, and its hash;
  - queries using the ranges;
  - versions activated later, cancelled and rolled back, with their audit;
  - ranges that no longer fit the register.
- `test_series_buckets.py`: a value superseded right at the start isn't counted.
- `tests/acceptance/test_at_ana_analytics.py`: AT-ANA-01…10, and the expected results against a fresh run of
  `independent.py`. Changing one expected r by 10⁻⁶, or one count by 1, fails it.
- Every suite run together: 258 tests passed. The web app lints and builds.
