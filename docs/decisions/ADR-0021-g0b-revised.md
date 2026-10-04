# ADR-0021: Gate G0b revised: the SKU field deferred, the broker's security accepted as it is for now

- **Status:** Accepted, except decision 3 (M7), which waits for the owner. Decision 1 amended by
  [ADR-0022](ADR-0022-placeholder-sku.md) the same day: under a placeholder SKU, the real machine's actual values are judged.
  Amended by [ADR-0026](ADR-0026-real-app-on-the-real-machine.md) on 2026-10-02: G0b no longer gates the real application on
  the development laptop, only the control-room PC
- **Date:** 2026-10-01
- **Decider:** Szyrelle (system owner)
- **Amends:** [ADR-0005](ADR-0005-split-gate-g0.md) (what G0b needs) and [ADR-0006](ADR-0006-mqtt-acquisition.md)
  (controls M1–M5 and M7)
- **Related:** [ADR-0002](ADR-0002-default-delays.md) (accepted the same day), [ADR-0003](ADR-0003-host-runtime.md),
  [ADR-0007](ADR-0007-parameter-register.md) (the SKU field, O-15), [ADR-0014](ADR-0014-monitor-core.md) (the gate)
- **URS:** OPC-01, OPC-05, OPC-08, SEC-02

## Context

G0b decides when Phase 1 connects to the real broker, and G1 needs it too. It asked for four
things. On 2026-10-01 they stood like this:

| G0b needed | State |
|---|---|
| ADR-0002 accepted | Accepted by the owner on 2026-10-01 |
| The host test on the control-room PC (ADR-0003) | Not run (task 0.8) |
| Controls M1–M5 and M7 | The probe on 2026-09-30 found port 1883 without TLS and a shared account, so M1 and M2 aren't met. M3–M5 aren't checked. M7 is a question for the Timebase admin |
| The SKU field in the machine's messages (O-15) | Missing: the edge team's tag isn't ready |

## Decision

1. **The SKU field is deferred until its tag is ready.** Connecting no longer needs it.
   - Without it, monitor-core shows every zone's live setpoint and actual value, but no
     targets or limits, and judges nothing. Its gate stays closed with the SKU as the reason,
     and Management gets one `system` notice (OPC-08). The real machine raises no events.
   - Judging the real machine still needs the field, and process engineering's SKUs and
     targets in an active rules version.
   - *Amended by [ADR-0022](ADR-0022-placeholder-sku.md):* an Administrator can set a placeholder SKU in the mapping.
     The actual values are then judged against their setpoints, and HMI mismatch waits for the field.
   - Not chosen: a Manager picking the running SKU on the live page. It would allow judging
     before the tag exists. But a changeover without that step would judge the line against
     the wrong targets, and OPC-01 would need changing. The owner can take it up later.
2. **The broker's security is accepted as it is, for now.** Connecting no longer needs M1–M5.
   The owner accepts:
   - port 1883 without TLS: the account's password and the data cross the plant network
     unencrypted (M1);
   - the shared account, not a dedicated one (M2), with no check that it can't publish (M3, M4);
   - no firewall check (M5). ADR-0006 made M5 mandatory without TLS; this sets that aside for now.

   **What still protects the machine is Centerline's own code (M6).** monitor-core and the
   Configuration page's connection test can't publish and set no Last Will. Tests check both
   clients, and scan the services' code for any call or import that could send.

   The password stays in a file secret (`config/secrets/mqtt-password`, 0600). The requests to
   the UNS team stay open: TLS on 8883 with the plant CA, and a dedicated subscribe-only account.
   When they're met, the controls are verified as ADR-0006 says and this acceptance is reviewed.
3. **M7 waits for the owner.**
   - Centerline only reads Timebase: its client sends GET only. M7 is about Timebase itself.
   - Timebase answers reads without a token, so it may also accept an unauthenticated delete,
     from anyone on the plant network. One `DELETE /api/datasets/{ds}` erases all history.
   - Checking it is one question to the Timebase admin. Never test it by sending a delete: if
     it works, the test erases the history.
   - **Recommended:** take M7 out of the gate, since the risk is there with or without
     Centerline, and still ask. Until the owner decides, it stays in.

**G0b now needs:**
- ADR-0002 accepted (done);
- the host test passed on the control-room PC;
- M7 confirmed, unless the owner takes it out.

## Consequences

- Connecting to the real broker, and G1, now wait on the host test (task 0.8) and M7.
- Once connected, the live page shows the real machine's values but raises no events, until
  the SKU field arrives.
- The publish-rejection test (task 0.7, M4) and the SKU field (task 0.11) are deferred, not
  dropped.
- The shared account's password now also sits on the Centerline host. If the broker lets that
  account publish, anyone who reads the password off the network or from the host can publish
  to the machine's topics. Centerline's code can't publish, but it can't stop that either.

## Tests

- `services/monitor_core/tests/test_monitor_mqtt.py`:
  - monitor-core's subscriber refuses to publish and has no Last Will;
  - no code in `centerline_monitor` calls `publish`, `will_set` or `_send_publish`, or imports
    `paho.mqtt.publish`.
- `services/api/tests/test_config_api.py`: the same for the connection test's client, and for
  `centerline_api` and `centerline_common`.
