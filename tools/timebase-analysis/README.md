# Timebase analysis: Phase 0 (O-03 probe, O-08 delays)

Read-only scripts for the Timebase Historian REST API. They only send GET
requests and can't write to or delete from the historian. Python 3.10+, no
installs. The Timebase client itself lives in
[`services/common/centerline_common/historian.py`](../../services/common/centerline_common/historian.py),
shared with the api service; `timebase.py` here re-exports it. The tags come from
[`config/parameter-register.json`](../../config/parameter-register.json); the
scripts hold no tag list of their own.

## 1. Configure

```bash
cp config.example.json config.json      # config.json is git-ignored
```

The example is already set for the plant server (`http://10.156.116.179:4516`,
dataset `dressings`, found from the Postman request). On 2026-09-29 reads
worked **without** a token. If the server starts enforcing its bearer token,
keep `"type": "bearer"` and put the token in `~/.secrets/timebase-token`
(`chmod 600`), never in `config.json`.

## 2. Probe the API

```bash
python probe.py config.json            # → data/probe-report.md
```

It shows:
- whether every register tag exists, with its latest value;
- one hour of samples per tag;
- how often each machine area publishes (from its `_timestamp` field);
- the clock offsets between this PC, the Timebase server and the machine.

## 3. Download history

```bash
python fetch.py config.json 2026-09-22 2026-09-29     # Manila dates, end exclusive
```

Tags are requested per machine area, 10 at a time, one hour per request.
7 days took 70 s on 2026-09-29. Interrupted downloads resume.

## 4. Analyse delays (O-08)

```bash
python analyse_delays.py config.json [--targets targets.csv] [--limits limits.csv]
```

Output: `data/delay-report.md`. Each zone (e.g. `P02.V3`) is analysed on its
own and rolled up per parameter and for the line. Every shift is a run;
without `targets.csv` its target is the setpoint held longest in that shift.

`targets.csv` and `limits.csv` are optional; `zone_id` may be `*`:

```csv
parameter_id,zone_id,target
P02,V1,220
```

```csv
parameter_id,zone_id,warn_low,warn_high,crit_low,crit_high
P02,*,3,3,6,6
```

Add `--running-only` to judge Actual severity the way
[ADR-0010](../../docs/decisions/ADR-0010-pause-actual-rules-when-stopped.md)
decides: only while the machine runs, skipping a warm-up after long stops
(`--long-stop-min 10 --warmup-min 30`). With limits, the report adds a
line-wide Warning/Critical table split by whether the machine was running.

### Reading the report

- **Suggested delay** is the *knee* of the events-per-delay curve: the
  shortest delay after which a longer one removes less than 10 % more events.
  Shorter dwells are quick transients (stepping through values); longer ones
  are deliberate setpoint changes, which monitoring should catch. When events
  keep falling steadily with the delay (as for Warning/Critical), there's no
  knee; read the table instead.
- **Setpoint changes / day** above 100 means the "setpoint" tag behaves like a
  live value. Such zones are left out of the line totals and flagged.
- **Data quality** lists spans Timebase couldn't return (see below).

## 5. Propose Actual limits

```bash
python propose_limits.py config.json       # → data/limits-proposed.csv, data/limits-report.md
```

It measures actual − setpoint during routine running, meaning the machine
running, without warm-ups after long stops and without 15 min after setpoint
changes. It proposes Warning offsets at the 0.25th / 99.75th percentiles,
rounded outward, and Critical at twice the Warning offset. The output is a
**starting point for process engineering**, not approved limits. Feed it back
with `analyse_delays.py --limits data/limits-proposed.csv --running-only`.

## 6. Publish cadence (freshness thresholds)

```bash
python cadence.py config.json              # → data/cadence-report.md
```

It reads each machine area's `_timestamp` arrivals for the downloaded range and
shows how often monitoring would pause at each freshness threshold, while
running and while stopped ([ADR-0006](../../docs/decisions/ADR-0006-mqtt-acquisition.md)).

## Server quirks the client handles

Seen on the plant server on 2026-09-29, and reproduced by `tests/mock_timebase.py`:

| Behaviour | Handling |
|---|---|
| One unknown tag rejects the whole request (`404 Error.TagNotFound`) | `fetch.py` checks every tag against the tag list first and skips missing ones |
| The first point returned is the value in force at the window start | Kept once; repeats across windows are dropped |
| Some one-minute spans on SPC tags answer `HTTP 500`; inside a multi-tag request the same span gives a **truncated body or an empty HTTP 200** | Every response is validated. On failure the client retries per tag, then halves the window down to 60 s, and records what it still can't read in `data/raw/gaps.csv` (12 such minutes in the week of 22–28 Sep) |
| The tag list comes back as `{"User": [...], "System": [...]}` | Parsed |
| The Timebase clock runs about 279 s behind real time | Reported by the probe (O-18); timestamps are kept as the server gives them |

## Tests

```bash
python tests/test_against_mock.py      # starts the mock, runs probe → fetch → analyse, 13 checks
```
