# ADR-0006: Live acquisition over MQTT (replaces OPC UA)

> **Resumed 2026-09-29 (owner decision, Phase 0).** It was briefly on hold while Analytics was built
> ([ADR-0008](ADR-0008-analytics-on-timebase.md)). The per-area freshness thresholds are now measured
> on 28 days; the topic map and controls M1–M7 wait for the broker details (O-14).

- **Status:** Accepted. The tag mapping (decision 3) is built on the Configuration page ([ADR-0013](ADR-0013-tag-mappings.md)); the probe runs on the plant broker started 2026-09-30. Security controls M1–M5 are accepted as they are for now, and M7 waits for the owner ([ADR-0021](ADR-0021-g0b-revised.md))
- **Date:** 2026-09-29
- **Decider:** Szyrelle (system owner)
- **Supersedes:** [ADR-0004](ADR-0004-opcua-none-none-controls.md) and the OPC UA acquisition design in SDD §4–5
- **Affects:** O-02 (security part, now controls M1–M7), O-03, new O-14 and O-18
- **URS:** OPC-01…08, SEC-02, AT-01, PER-01. These are written for OPC UA, so **the URS needs the change request below**

## Context

The Volpak's data already reaches a plant MQTT broker (the UNS), and Timebase
subscribes to it. The Timebase tag names are the MQTT topic path with `/`
replaced by `.`, plus the JSON field. Every machine area (`SPC`,
`Dosing_Parameters`) also carries `_timestamp`, `_model`, `_name`, `plantID`,
`areaID`, `lineID` and `machineID`. That points to **one JSON message per
area, holding all of that area's fields**. Reading the same feed for live
monitoring means live values and history come from one source.

Measured through Timebase on 2026-09-29 (probe and 24 h analysis):

| Fact | Value | Design consequence |
|---|---|---|
| Dosing_Parameters message rate | ≈ 1/s; about 56 gaps of 25–60 s a day, and up to 34 min while stopped | Staleness must be judged per area |
| SPC message rate | last hour ≈ 1/s; previous 24 h irregular, with 308 gaps > 10 s and a longest gap of about 20–25 s | The SDD's fixed 10 s would pause monitoring ~300×/day with that publisher |
| Payload `_timestamp` vs real time | about **−114 s** (edge clock slow) | Never judge freshness or order by the payload clock |
| Timebase clock vs real time | about **−279 s** | History and live events disagree by ~4.6 min until NTP is fixed (O-18) |
| Timebase quality codes | always 192 | Quality comes from freshness and payload validity, not a code |
| Tags per area | SPC 43, Dosing_Parameters 17 | One message refreshes a whole area at once |

Measured on the plant broker on 2026-09-30 (`tools/mqtt-probe`, read-only):

| Fact | An hour running (08:50–09:51 Manila) | 30 min with short stops (10:51–11:21) |
|---|---|---|
| SPC | 54 msgs/min; gaps median 1.0 s, p99 7.5 s, max 11.3 s | 53/min; p99 7.7 s, max 27.0 s (during our own disconnects) |
| Dosing_Parameters | 53/min; p99 7.7 s, max 41.0 s | 49/min; p99 8.4 s, max 40.2 s |
| DFOS | 1/min: a Turck Banner counter (counts, speeds, running and stopped flags), not in the register | same |
| Payload clock | −113.4 s | −113.3 s |
| Tags that monitoring needs | all 30, under their Timebase field names | all 30 |
| SKU field, retained messages | none, none | none, none |
| Connection | no drops | seven keep-alive timeouts or errors in 50 s at 10:54 Manila, each followed by a reconnect |

- **Freshness limits hold:** SPC 30 s and Dosing 90 s sit above the largest
  regular gaps (11 s and 41 s).
- **The publisher kept sending through stops of up to about 4 minutes.**
- **Still to capture: a long stop** (10 minutes or more). Timebase showed
  Dosing silent for up to 34 minutes during long stops. If the broker does the
  same, the line-wide snapshot gate pauses everything during long stops,
  including HMI mismatch monitoring, which ADR-0010 keeps running while
  stopped (O-21).

## Decision

monitor-core **subscribes to the plant broker** in place of an OPC UA client.

1. **Client.** MQTT 5 (3.1.1 if the broker lacks 5), Python `aiomqtt` over
   paho-mqtt, TLS, a dedicated read-only account and client ID
   `centerline-monitor-<host>`. Keep-alive 5 s. **Clean start**, no
   persistent session: a backlog of old values replayed after a reconnect is
   worse than none, and the gate waits for fresh data anyway.
2. **Subscriptions.** QoS 1, on the area topics named in the active tag mapping.
3. **Tag mapping.** Each register tag maps to a (topic, JSON field) pair,
   produced by `tools/mqtt-probe` as `topic-map.json` and imported as a
   versioned, atomically activated `tag_mapping_version` (OPC-06/07 unchanged
   in spirit).
4. **Payload.** Parse JSON. A missing field, non-numeric value or NaN makes
   that tag unknown. `_timestamp` is stored with each reading as `source_ts`
   evidence.
5. **Time.** Evaluation and evidence use the **arrival time on monitor-core's
   NTP-synced clock** (`received_at`). If `|source_ts − received_at|` exceeds
   5 s, the health page shows a clock-skew warning. That doesn't pause monitoring.
6. **Freshness (replaces "10-second stale threshold", OPC-03).** An area is
   fresh while its last live message is younger than its threshold. The
   threshold is configured per area and set at ≥ 1.5 × the largest regular gap.
   The line's gate is open only when every mapped area is fresh, every
   monitored field is present and valid, and the SKU field is valid. The SDD's
   10 s can come back if the edge publishes each area at a fixed interval of
   5 s or less; that request is in O-14.

   **Measured on 28 days of message arrivals** (`_timestamp` in Timebase,
   1–28 Sep, `tools/timebase-analysis/cadence.py`):

   | Area | Messages | Pauses a day while running, by threshold | Proposed threshold |
   |---|---|---|---|
   | SPC | 0.19 / s | 10 s: 152 · 15 s: 7.0 · 20 s: 0.1 · 30 s: 0.1 | **30 s** |
   | Dosing_Parameters | 0.75 / s | 10 s: 113 · 30 s: 35 · 60 s: 1.8 · 120 s: 0.3 | **90 s** |

   Dosing goes quiet for 30–60 s about 35 times a day even while running, so a
   single 30 s default would pause monitoring that often. The real-broker probe
   confirms both values before G1. The same data showed real outages: 1.8 h on
   15 Sep while running, and 11–30 h gaps during long stops.
7. **Connection loss.** A broker disconnect (keep-alive or TCP) closes the
   gate at once. If the edge team provides a status/Last Will topic or
   heartbeat for the publisher, "offline" there closes it too. Reconnect every
   5 s for 1 min, then every 30 s (as before).
8. **Retained messages** are recorded but **never count as fresh**. Their age
   can't be trusted, since the payload clock is 114 s off.
9. **Resume (OPC-05).** After a reconnect or pause, evaluation restarts once
   every mapped area has delivered a live message since the reconnect, with
   all monitored fields valid and a valid SKU.
10. **Cross-check read (OPC-02).** MQTT has no direct read, so this is dropped.
    The health page may compare live values with Timebase's latest values as
    advice only, never as a gate.

### Security controls (replace ADR-0004 C1–C7)

| # | Control | Owner | Verified by | Status |
|---|---|---|---|---|
| M1 | TLS to the broker (8883) with the plant CA, hostname verified. If the broker offers only plain 1883, M5 becomes mandatory and TLS goes on the roadmap (the same risk class as the old None/None) | UNS admin | Probe report shows "TLS on" | Not met: 1883 without TLS. Accepted for now ([ADR-0021](ADR-0021-g0b-revised.md)) |
| M2 | Dedicated Centerline account and client ID; password mounted as a file secret | UNS admin | Config review | Not met: a shared account. Accepted for now ([ADR-0021](ADR-0021-g0b-revised.md)) |
| M3 | Broker ACL: **subscribe-only** on `Unilever_Ph_Nutrition/Dressings_Halal/Filling/Volpak/Filler/#`; no publish anywhere, explicitly not on command/write topics (e.g. Sparkplug `NCMD`/`DCMD`, `…/set`) | UNS admin | ACL export | Not checked. Accepted for now ([ADR-0021](ADR-0021-g0b-revised.md)) |
| M4 | Publish-rejection test with the Centerline account on a dedicated test topic `centerline/acl-test` | Developer + UNS admin | Test record ([mqtt-probe README §3](../../tools/mqtt-probe/README.md)) | Not run (task 0.7). Accepted for now ([ADR-0021](ADR-0021-g0b-revised.md)) |
| M5 | Firewall: the broker port is reachable from the Centerline VM; the broker isn't reachable from outside the plant network | OT/IT | Connection test | Not checked. Accepted for now ([ADR-0021](ADR-0021-g0b-revised.md)) |
| M6 | In code, the MQTT wrapper exposes subscribe only: no publish and no Last Will. A unit test fails if publish is reachable (as `tools/mqtt-probe` does today) | Developer | Unit test | ✅ Both clients refuse to publish and have no Last Will, and a scan finds no code that sends (`test_monitor_mqtt.py`, `test_config_api.py`) |
| M7 | The Timebase client sends GET only. Reads work **without a token** today, so the Timebase admin must confirm unauthenticated clients can't `POST` or `DELETE` (`DELETE /api/datasets/{ds}` erases all history) | Timebase admin | Admin confirmation | Not confirmed yet. The owner decides whether it stays in G0b ([ADR-0021](ADR-0021-g0b-revised.md)) |

## URS change request (owner to raise)

| URS | Current text | Proposed text |
|---|---|---|
| OPC-01 | Read one SKU tag, 11 HMI setpoints and 11 actual values through OPC UA with no write or method permissions. | Subscribe to the machine's MQTT area topics for the SKU field and every monitored zone's setpoint and actual (parameter register) with a subscribe-only account. |
| OPC-02 | Use 1-second subscriptions and sampling plus a 30-second direct verification read. | Use the machine's published messages (≈ 1 s); no direct verification read. |
| OPC-03 | 10-second stale threshold, connection loss after three failed keep-alives (~10 s), retries every 5 s for 1 min then every 30 s. | An area is stale when it has been silent longer than its configured threshold (default 30 s, set from measured gaps); connection loss on MQTT keep-alive failure; same retry timing. |
| OPC-04 | Use the current None/None endpoint with a dedicated read-only account, documented OT acceptance and network restrictions. | Use TLS and a dedicated subscribe-only broker account with network restrictions (controls M1–M7). |
| OPC-05 | After reconnect, validate a complete fresh 23-tag snapshot before evaluation resumes. | After reconnect, require a live message from every mapped area, all monitored fields valid and a valid SKU, before evaluation resumes. |
| OPC-06 | Manual mapping, read-only browsing and atomic activation. | Mapping of register tags to topic + JSON field, discovered from the broker (read-only), with atomic activation. |
| AT-01 | OPC UA 23-tag read-only acquisition, stale/reconnect and complete snapshot. | MQTT acquisition for all register zones, publish rejected (M4), stale area and reconnect, complete snapshot. |
| SEC-02 | Lists the OPC UA None/None limitation for pre-approval. | Replace with the MQTT broker dependency and controls M1–M7. |

OPC-07 and OPC-08 stand as written.

## Consequences

- **The broker becomes a monitoring dependency**, as the OPC UA server was. It's
  shared plant infrastructure, so its availability and maintenance windows
  count against AVL-01. Ask the UNS admin for both (O-14).
- A **new failure mode**: the edge publisher stops while the broker stays up.
  Freshness (area silent) catches it; a liveness topic catches it sooner.
- **Live monitoring and Analytics read the same data.** Only the Timebase clock
  offset separates them, until O-18 is fixed.
- `tools/opcua-sim` becomes [`tools/mqtt-sim`](../../tools/mqtt-sim/README.md)
  (built), and the OPC UA write test becomes control M4.
- Alarm latency depends on the edge: with on-change publishing a setpoint change
  arrives at once; with a fixed interval, within one interval.

## Tests to add

- An area silent past its threshold closes the gate. Evaluation resumes only
  after a live message from every area.
- A retained message on reconnect doesn't resume evaluation.
- A payload clock skewed by −114 s doesn't affect evaluation and raises the
  skew warning.
- A missing or non-numeric field closes the gate for the line (whole-line
  snapshot, as in the SDD).
- A broker disconnect closes the gate within 1.5 × keep-alive.
- Calling publish through the MQTT wrapper raises (M6).
