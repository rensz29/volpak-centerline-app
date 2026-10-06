# ADR-0008: Analytics & Correlation on Timebase, built first

- **Status:** Accepted. Amended by [ADR-0027](ADR-0027-no-sku.md) (2026-10-05): no SKU filter. Amended by
  [ADR-0029](ADR-0029-analytics-ranges-and-g4-acceptance.md) (2026-10-06): the Analytics-valid ranges are versions in the database, not a file in the api config
- **Date:** 2026-09-29
- **Decider:** Szyrelle (system owner)
- **URS:** ANA-01…21, SEC-01; affects O-06, O-10, O-15, O-18, O-19
- **Related:** [ADR-0006](ADR-0006-mqtt-acquisition.md) (live acquisition, resumed the same day), [ADR-0007](ADR-0007-parameter-register.md)

## Context

Timebase is used only for Analytics & Correlation. The owner put that feature
first, ahead of the monitoring core, and parked the MQTT live acquisition.
Probing the plant's Timebase (`http://10.156.116.179:4516`, dataset `dressings`)
turned up six facts the SDD didn't anticipate:

1. **Values are stored only on change.** A steady temperature can go 12 minutes
   without a sample. The SDD's bucketing ("aggregate the samples in each
   bucket") would leave those buckets empty and bias the correlation toward
   moments of change.
2. **No aggregation parameters.** Raw samples must be fetched.
3. **Some spans can't be read.** Single-tag requests answer HTTP 500; the same
   span inside a multi-tag request comes back truncated or as an empty 200.
   There were 12 one-minute spans on the SPC temperature tags in one week.
4. **No SKU tag and no usable shift tag for the Volpak.** `Volpak_Shift` is a
   counter, not a shift.
5. **The Timebase server clock runs about 4 min 38 s behind real time** (O-18).
6. **Each machine area's `_timestamp` field arrives with every message**, so its
   samples show when the machine was publishing.

## Decision

1. **Build order.** The api service (FastAPI, Python 3.12) starts with only the
   Analytics area: `GET /api/v1/analytics/options`, `POST /api/v1/analytics/query`
   and `GET /api/v1/health`. There's no database and no login yet. The Timebase
   client lives in `services/common/centerline_common/historian.py`, shared with
   the Phase 0 tools.
2. **Step series (sample-and-hold).** Each value holds until the next sample,
   and the first sample of a read is the value in force at the start.
   - **AVG** is the time-weighted average over the known part of a bucket.
   - **MIN / MAX** are the smallest / largest values in force during the bucket.
   - A bucket counts only when **at least 50 % of it is known**; otherwise it's
     missing, never zero (ANA-08).
3. **Data gaps from the machine's heartbeat.** When a machine area sends no
   message for more than **120 s**, its values count as unknown from then until
   the next message. The time is reported as "no data from the machine".
4. **Unreadable Timebase spans** are found by splitting the request down to
   60 s, marked unknown, reported, and remembered for the life of the process
   so later queries skip them.
5. **SKU is optional until a SKU tag exists** (deviation from ANA-05, owner
   decision). Every result says it covers all products. The api rejects a SKU
   filter until the register names a SKU tag. The filter comes on without code
   changes once `sku.tag` is set.
6. **Shift comes from the Manila time of day** (06:00 / 14:00 / 22:00). The
   Production Date is the Manila date the shift starts (A-07). This closes
   **O-06**.
7. **Variables** are the actual values of active zones, plus parameters with an
   actual tag but no setpoint (`analytics_only`): P08 Machine Speed today. P09
   carries its O-19 caution into every result. *Amended by
   [ADR-0009](ADR-0009-setpoints-in-analytics.md): setpoints are variables too,
   and people see zone names rather than parameter IDs.*
8. **Strength bands follow ANA-13 on unrounded |r|**: below 0.20 very weak/none,
   below 0.40 weak, below 0.70 moderate, below 0.90 strong, otherwise very
   strong. These replace the prototype's bands.
9. **Size guard (ANA-19).** Above 10,000 paired buckets the api returns no chart
   and recommends the smallest larger bucket, computed exactly on the data it
   already fetched.
10. **Groups (ANA-16/17).** None, Shift or Production Date, with at most 10
    visible. For Production Date these are **the 10 most recent** (proposed
    default for O-10).
11. **Analytics-valid ranges (ANA-10).** A CSV named in the api config,
    validated as a whole file: every register parameter, matching units,
    min < max, identified by SHA-256. Versioning, the Administrator's reason and
    rollback (**ANA-11**) need the database and come with Phase 1.
12. **Audit.** Query metadata (never the paired data, ANA-21) is appended to
    `logs/analytics-queries.jsonl`. There's no user until login exists.
13. **Charts.** Apache ECharts 6, lazy-loaded with the page: scatter with a
    least-squares line, and trend with dual axes when units differ, gaps,
    zoom, pan and reset (ANA-15).

## Measured on the plant Timebase (2026-09-29)

| Range | Variables | Response |
|---|---|---|
| 24 h (default) | P02 V1 vs P02 V2, 1 min | **0.4 s** |
| 7 days | P02 V1 vs P03 Front, 5 min | 1.3 s |
| 30 days (maximum) | two SPC variables, 15 min | 4.8 s |
| 30 days | with a Dosing variable, 15 min | 13–14 s: the Dosing area publishes ~1 message/s, so ~2 million heartbeat points |

## Consequences

- **The api has no login yet.** Bind it to 127.0.0.1 only. Role checks
  (Manager, Administrator; O-13) and the audit's "who" arrive with Phase 1.
- **Results carry the Timebase clock.** Bucket times and shift boundaries are
  off by the server's clock error until O-18 is fixed; every result warns when
  the offset is over 30 s.
- **The 24 h results show warm-ups and stops.** Temperatures ramp together, so
  r is near 1 while nothing is being "caused". The causation note (ANA-14) is
  on every result. A "running only" filter would be a sensible addition later
  (not in the URS).
- **ANA-11 is partly met** until ranges move into the database.
