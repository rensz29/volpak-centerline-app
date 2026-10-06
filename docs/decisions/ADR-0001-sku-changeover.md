# ADR-0001 — Open events when the SKU changes

- **Status:** Superseded by [ADR-0027](ADR-0027-no-sku.md) on 2026-10-05: Centerline has no SKU, so nothing closes as a changeover
- **Date:** 2026-09-28
- **Decider:** Szyrelle (system owner)
- **Closes:** O-09
- **URS:** OPC-05, OPC-07, OPC-08, MON-01, SES-05, DAT-01

## Context

The URS doesn't say what happens to open events, running delays and open
workflows when the line changes to another SKU. Every event is judged against
the configuration of the SKU it was raised under (OPC-07). After a change, that
configuration no longer describes what the machine is making.

Options considered:

| Option | Behaviour | Why not |
|---|---|---|
| **A — close as "SKU changeover"** | Treat the change like a pause, close what is open and start fresh on the new SKU | — (chosen) |
| B — re-judge against the new SKU | Keep open events and apply the new SKU's config | Breaks OPC-07: an event would change the config it was judged against |
| C — keep open under the old SKU | Events stay open until closed by hand | Critical repeats keep firing for a SKU that is no longer running; confusing on screen |

## Decision

A **SKU changeover** is a change of the SKU tag from one valid SKU to a
**different** valid SKU. When monitor-core detects one:

1. **Close the evaluation gate** for the line and write a `pause_period` with
   reason `SKU_CHANGEOVER`, from the old SKU to the new one.
2. **Close every open event** for the line with a final transition
   `CLOSED_SKU_CHANGEOVER`, all in one transaction. Raw values and the config
   version stay on the event as recorded.
3. **Cancel dependent timers.** Pending mismatch and severity delays, Critical
   repeats and escalations, and the WF-03 workflow escalation are all
   cancelled. Pending delays leave no brief-change record; the pause period
   covers them.
4. **Cancel open workflow requests** as `CANCELLED_SKU_CHANGEOVER`. Anything
   the Operator already submitted stays on record. The server sends the
   `draft.purge` WebSocket message so unsent browser drafts are wiped (SES-05).
5. **Notifications.** Initial notifications already sent stay on record. **No
   recovery notices** are sent (as with MON-01). One **system notification**
   goes to Management listing the events that were closed, so an unresolved
   Critical doesn't disappear silently.
6. **Resume** only after a complete, fresh snapshot under the new SKU: a live
   MQTT message from every mapped machine area since the change, all monitored
   fields valid ([ADR-0006](ADR-0006-mqtt-acquisition.md), OPC-05). Evaluation
   then uses the new SKU's active configuration version.

**Not a changeover** (handled by the existing OPC-08 pause, open events stay open):

- The SKU tag becomes empty, invalid or stale.
- The SKU goes missing and comes back as the **same** SKU.
- The SKU changes to a code that isn't configured. This counts as a *missing
  SKU*: pause, keep events open, alert Management. It becomes a changeover as
  soon as a configured SKU appears.

## Consequences

- The SKU comes from a field in the machine's MQTT payload ([ADR-0007](ADR-0007-parameter-register.md));
  until the edge team publishes it, the real machine pauses (OPC-08) and changeovers
  can only be tested with `tools/mqtt-sim --sku-field`.

- An unresolved problem can close without an Operator reason. The Management
  system notification and the closed-event record keep that visible.
- Right after the change, HMI setpoints are often still on the old SKU's values
  while the operator dials in the new ones. Those mismatches are judged fresh
  under the new SKU with the normal mismatch delay. Whether that delay must cover
  the settling time is measured in [ADR-0002](ADR-0002-default-delays.md) (the
  analysis reports changeover dwells separately).
- New states to implement: `pause_period.reason = SKU_CHANGEOVER`, event
  transition `CLOSED_SKU_CHANGEOVER`, workflow status `CANCELLED_SKU_CHANGEOVER`,
  and notification type `SYSTEM_SKU_CHANGEOVER`.

## Tests to add

- Changeover with an open HMI event, an open Critical in its repeat sequence, and
  a pending Warning delay. All close or cancel; no recovery notice; one Management
  system notification.
- The SKU goes missing, then comes back as the same SKU: events stay open, no closes.
- The SKU changes to an unconfigured code, then to a configured one: pause first,
  changeover on the second change.
- An Operator with an unsent draft gets `draft.purge`, and the draft is gone from
  local storage.
- No evaluation until the fresh snapshot (every mapped area); then the new config version is used.
