# ADR-0004 — Accepting the OPC UA None/None endpoint with compensating controls

> **Superseded by [ADR-0006](ADR-0006-mqtt-acquisition.md) on 2026-09-29.** Live data now comes from the plant MQTT broker; controls M1–M7 there replace C1–C7. Kept for the record.

- **Status:** Superseded by ADR-0006 (was: accepted for development and testing)
- **Date:** 2026-09-28
- **Decider:** Szyrelle (system owner). OT/IT must carry out and confirm the network controls
- **Closes:** O-02 (security part)
- **URS:** SEC-02, OPC-01

## Context

The machine's OPC UA endpoint offers security policy **None** and mode **None**:
no signing, no encryption. Readings and possibly the user password cross the
network in clear, and a device on the same network could spoof values. This is
the system's largest accepted risk.

## Decision

Accept None/None for this project on the condition that these controls are in place:

| # | Control | Owner | Verified by | Status |
|---|---|---|---|---|
| C1 | Workstation and OPC UA server on a restricted network segment | OT/IT | Network diagram | _tbd_ |
| C2 | Firewall allows **only** the Centerline VM's IP to reach the OPC UA port (4840 unless stated otherwise) | OT/IT | Connection attempt from another PC fails | _tbd_ |
| C3 | Dedicated **read-only** OPC UA account used by Centerline only | OT | Account config screenshot | _tbd_ |
| C4 | Write **and** method call rejected for that account (AT-01) | Developer + OT | Test record (procedure below) | _tbd_ |
| C5 | User-token policy reviewed; if the password crosses in clear, the account is treated as exposed and has no rights beyond reading | OT/IT | Review note | _tbd_ |
| C6 | Unexpected OPC UA sessions logged and alerted | OT/IT | Alert test | _tbd_ |
| C7 | Plan to move to a Sign & Encrypt endpoint with certificates | Owner | Roadmap entry | _tbd_ |

### Safe procedure for C4 (write rejection test)

A write test against a live machine must not be able to change anything, even
if it unexpectedly succeeds:

1. Do it **with OT present**, during a planned stop or on a line that isn't producing.
2. Pick one HMI setpoint tag. **Read** its current value.
3. Try to **write the exact same value** back. Expected result:
   `BadUserAccessDenied` or `BadNotWritable`.
4. Try to call one harmless method (if the server exposes any). Expected result:
   `BadUserAccessDenied` / `BadNotExecutable`.
5. If either succeeds, **stop**. The account isn't read-only; OT must fix it
   before Centerline connects again.

In code, monitor-core never calls write or method-call services. The OPC UA
client wrapper exposes only read, browse and subscribe, and a unit test fails
if a write or call service appears.

## Consequences

- Development against the **simulated** OPC UA server (`tools/opcua-sim`) can
  proceed now. Connecting to the real machine requires C1–C4.
- Go-live (G5) is blocked until C1–C6 are verified. C7 stays on the roadmap.
