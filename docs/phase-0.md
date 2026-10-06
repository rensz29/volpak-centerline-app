# Phase 0: foundations and spikes (tracker)

Status on **2026-10-01**. Phase 0 proves what the design assumes before
Phase 1 builds on it. Gates come from [ADR-0005](decisions/ADR-0005-split-gate-g0.md).
Evidence files under `tools/*/data/` are plant data: they stay on this laptop
and out of git.

## Tasks

| # | Task | Owner | Status | Evidence | Next step |
|---|---|---|---|---|---|
| 0.1 | Timebase probe (O-03) | Developer | ✅ Done | `tools/timebase-analysis/data/probe-report.md` | Report the unreadable spans and the open auth to the Timebase admin (M7) |
| 0.2 | HMI mismatch delay (O-08) | Developer → owner | ✅ All five delays accepted by the owner on 2026-10-01 | `data/delay-report.md`, [ADR-0002](decisions/ADR-0002-default-delays.md) | Measure again after the first month in production |
| 0.3 | Actual limits and Warning/Critical delays | Developer → process engineering | ✅ Delays accepted (0.2); limits proposed | `data/limits-proposed.csv`, `data/limits-report.md`, ADR-0002 | **Process engineering:** review the limits (shown on the Rules tab) and send each zone's target (the centerline sheet) |
| 0.4 | Actual rules during stops (O-20) | Owner | ✅ Decided: pause while stopped | [ADR-0010](decisions/ADR-0010-pause-actual-rules-when-stopped.md) | Add to the URS change request |
| 0.5 | Publish cadence and freshness thresholds | Developer | ✅ Measured via Timebase | `data/cadence-report.md`, [ADR-0006](decisions/ADR-0006-mqtt-acquisition.md) | Confirm with 0.6 |
| 0.6 | MQTT probe on the plant broker (O-14) | Developer + UNS team | ✅ Two runs on 2026-09-30: an hour running, and 30 min with short stops (longest about 4 min). Port 1883 without TLS, shared account (M1, M2 not met; accepted for now, [ADR-0021](decisions/ADR-0021-g0b-revised.md)) | `tools/mqtt-probe/data/running-2026-09-30/`, `…/stopped-2026-09-30/`, [ADR-0006](decisions/ADR-0006-mqtt-acquisition.md) | Capture a long stop (10 min or more), e.g. at a break or changeover (O-21). The real application's mapping has all 30 tags |
| 0.7 | Publish-rejection test (control M4) | Developer + UNS admin | ⏸ Deferred: the broker's security is accepted as it is for now ([ADR-0021](decisions/ADR-0021-g0b-revised.md)) | [mqtt-probe README §3](../tools/mqtt-probe/README.md) | When the UNS team gives Centerline its own account |
| 0.8 | Host runtime on the control-room PC (O-02) | IT + owner | ⏳ Not run | [deploy/host-check](../deploy/host-check/README.md) | Run `Test-CenterlineHost.ps1`, then the boot test |
| 0.9 | AI model benchmark (O-01) | Developer | ⏸ Deferred by the owner | — | When resumed: sample OCAPs (English and Filipino), bge-m3 plus 2–3 small models |
| 0.10 | Plant clocks (O-18) | OT/IT | ⏳ Open | probe report: Timebase −4 min 39 s, edge publisher −1 min 54 s | NTP on both |
| 0.12 | P09 tags swapped? (O-19) and comparison rule (O-17) | OT, then owner | ⏳ Open | ADR-0007 | Check the HMI screen |
| 0.13 | URS v1.1 approval and change requests | Owner | ⏳ Open | Change requests in ADR-0006, 0009, 0010, 0027 | Approve and raise them |

## Gates

| Gate | Unlocks | Needs | State |
|---|---|---|---|
| **G0a** | Phase 1 on the simulator | URS approved · ADR-0001, 0003, 0006, 0007 accepted · ADR-0002 proposed | Phase 1 started on the simulator on 2026-09-30 by owner decision ([ADR-0014](decisions/ADR-0014-monitor-core.md)); **URS approval** still open |
| **G0b** | Connecting to the real broker; exit gate G1 | ADR-0002 accepted ✅ · host test passed · M7 confirmed, unless the owner takes it out ([ADR-0021](decisions/ADR-0021-g0b-revised.md)) | Waiting on 0.8 and the owner's M7 decision. M1–M5 are no longer needed |
| **G0c** | Phase 3 (OCAP and AI) | O-01 closed | Deferred (0.9) |

## What Phase 0 found

- **Timebase stores values only on change** and has no aggregation. Some spans
  can't be read: 42 one-minute spans on the SPC temperature tags in 28 days.
  One unknown tag fails a whole request. The tools and the api handle all of
  this ([ADR-0008](decisions/ADR-0008-analytics-on-timebase.md)).
- **The Timebase server clock is 4 min 39 s slow, and the edge publisher's 1 min 54 s.**
  Monitoring uses its own clock, but history lines up with events only after NTP.
- **HMI mismatch:** about 21 events a day for the line at 10–30 s; 30 s recommended.
- **Temperatures hold their setpoints tightly in routine running.** The
  vertical zones stay within about ±0.1 °C and the top jaws within about
  ±10 °C. The machine stops about 100 times a day, and long stops cool every zone.
- **Actual rules at all times would raise about 66 Warnings and 16 Criticals a
  day**, mostly during stops. Paused while stopped, that's 7 and 2 (ADR-0010).
- **SPC publishes at least every ~20 s; Dosing goes quiet for 30–60 s about 35
  times a day.** Freshness thresholds are therefore 30 s and 90 s, not the SDD's 10 s.
- **No usable shift tag for the Volpak.** P09's two tags behave as if swapped.
- **The plant broker (2026-09-30):**
  - one JSON message per machine area, carrying every field, about once a
    second: far more often than Timebase shows, since it stores only changes;
  - SPC's largest gap was 11 s and Dosing's 41 s, so the 30 s and 90 s limits hold;
  - publishing carried on through stops of up to about 4 minutes; a long stop
    hasn't been captured yet (O-21);
  - a third topic, DFOS, is a Turck Banner counter, not in the register;
  - all 30 tags that monitoring needs appear under their Timebase names;
  - at 10:54 Manila the probe's connection dropped seven times in 50 s
    (keep-alive timeouts). It was the only such burst in 90 minutes.

## Messages to send

- **UNS / edge team:**
  - the questions in [tools/mqtt-probe/README.md](../tools/mqtt-probe/README.md):
    broker, subscribe-only account, payload shape, publish mode, liveness topic;
  - TLS on 8883 with the plant CA, and a dedicated subscribe-only Centerline
    account instead of the shared one (ADR-0006 M1, M2). Accepted without them
    for now (ADR-0021), but still asked;
  - can Dosing_Parameters publish at a fixed interval (≤ 5 s)?
  - are P09's setpoint and actual names swapped?
  - please NTP-sync the edge publisher.
- **Timebase admin:**
  - the unreadable spans (`tools/timebase-analysis/data/raw/gaps.csv`);
  - reads work without a token: please confirm `POST`/`DELETE` are refused (M7);
  - please NTP-sync the server.
- **Process engineering:**
  - each zone's target (the centerline sheet). Until a zone has one, only its
    actual value is judged, not its HMI setpoint ([ADR-0027](decisions/ADR-0027-no-sku.md));
  - review the proposed limits in ADR-0002;
  - each parameter's Analytics-valid range: the template is on Configuration → Analytics ranges
    ([ADR-0029](decisions/ADR-0029-analytics-ranges-and-g4-acceptance.md)). Until then Analytics excludes no value
    as out of range;
  - Actual rules pause while the machine is stopped and for 30 min after long
    stops (ADR-0010). Is that acceptable?
- **OT / IT:**
  - the control-room PC: Windows 11 Pro or LTSC, Hyper-V, about 200 GB free,
    wired LAN;
  - a firewall rule from that PC to the broker;
  - NTP.
