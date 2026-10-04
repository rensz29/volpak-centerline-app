# ADR-0023: The notifier: Teams and email from the outbox (Phase 2, first slice)

- **Status:** Accepted (decision 6 amended by [ADR-0025](ADR-0025-shifts-and-reasons.md): a ninth kind, Reason overdue (15 min))
- **Date:** 2026-10-01
- **Decider:** Szyrelle (system owner): Phase 2 now, notifications first. The design follows SDD §8; the
  channels' details are placeholders until IT answers O-05
- **Related:** [ADR-0014](ADR-0014-monitor-core.md) (the outbox monitor-core writes),
  [ADR-0016](ADR-0016-accounts-sign-in-and-roles.md) (roles), [ADR-0020](ADR-0020-database-roles.md) (the role),
  [ADR-0021](ADR-0021-g0b-revised.md) (G0b), [ADR-0022](ADR-0022-placeholder-sku.md)
- **URS:** NOT-01…07, ACT-03, ACT-04, MNT-01, OPC-08; SDD §8

## Context

- **Phase 1 is built on the simulator.** G1 waits on G0b: the control-room PC test and M7.
  On 2026-10-01 the owner moved on to Phase 2 meanwhile, notifications first. The shift
  handover and the reason workflow follow.
- **monitor-core already writes every message to the outbox** (`notification`), in the same
  transaction as its event (NOT-03): first notices, escalations to Critical, the Critical
  reminders and the 75-minute escalation, recoveries, SKU changeovers and system alerts.
  Nothing delivers them yet.
- **The channels aren't known yet** (O-05): the Teams flow, how its trigger authenticates,
  and the relay.

## Decision

1. **A notifier service** (`services/notifier`) connects as `centerline_app`.
   - It routes each new message once, by the routing in effect, and freezes what matched
     (`notification_route`).
   - Each channel × recipient is a delivery (`notification_delivery`) that holds the message
     as sent. Every retry sends exactly that.
   - One lane per channel claims its due deliveries (`FOR UPDATE SKIP LOCKED`), so a Teams
     outage never holds up email.
   - Every attempt is kept (`delivery_attempt`) with what the provider said, never a secret.
   - Its heartbeat, every 2 s, shows on `GET /api/v1/health` with each lane and the backlog.
2. **The retry schedule (NOT-04/05):** first within about a second, then 30 s, 1 min and
   5 min after each failure, then every 15 min. No attempt is made later than 24 h after the
   delivery was created: it becomes a permanent failure. A message already over 24 h old
   when it's routed is marked expired and not sent.
3. **Teams, through one Power Automate flow** with an HTTP trigger.
   - Centerline POSTs the `centerline.notification/1` JSON below, including a ready Adaptive
     Card for the flow to post. Any 2xx (the trigger answers 202) is Delivered.
   - The flow's URL carries its signature, so it's a write-only secret
     (`config/secrets/teams-flow-url`, 0600) and never appears in an outcome or a log.
   - If IT requires Entra ID tokens instead of the signed URL (O-05), only this channel changes.
4. **Email, through the plant's relay:** one message per recipient, with no security,
   STARTTLS or TLS, and an optional sign-in whose password is write-only.
   - Submitted means the relay answered 250 after the body. After that the message is
     never sent again (NOT-06). The database enforces it: a finished delivery can't change.
   - A connection dropped before that 250 is retried with the same Message-ID.
5. **Leases.** A claimed delivery is leased for 2 minutes. If its attempt is cut short (the
   notifier stops, or the database goes away), the attempt is recorded as interrupted and the
   delivery is tried again, unchanged. This is the only way a message can arrive twice, and
   then with the same Message-ID and dedup key for the receiver to spot.
6. **Routing**, versioned like the rules and the mappings, on Configuration → Notifications.
   It's the Administrator's to change, like the other connection settings.
   - A rule has a name, a channel, the kinds of message it sends, and its recipients.
   - The kinds fold the SDD's type and severity together: HMI mismatch, Actual Warning,
     Actual Critical, Critical reminder, Critical escalation (75 min), back to normal, SKU
     changeover, system alert. There's one line today, so a rule has no line field yet.
     ADR-0025 added Reason overdue (15 min), the reason workflow's escalation.
   - A version that leaves any kind of Critical with nobody to tell can be saved but not
     activated (ACT-03).
   - Messages raised while no routing is in effect are marked not sent, and never sent later.
   - The proposal: Management gets every kind on both channels, with placeholder recipients
     the page warns about, until IT gives the real ones.
7. **The Notifications page**, for Managers and Administrators, shows every message, how it was
   routed, each delivery's status and attempts, and what was sent. Only an Administrator:
   - sends a "TEST - NO PRODUCTION EVENT" message to one named recipient, outside the routing,
     to try an address or the flow first (NOT-07);
   - re-drives a permanent failure, saying why (NOT-05): a new delivery, with the old one
     marked re-driven.

   Both are audited.
8. **Watching the watcher (SDD §8):** if monitor-core's heartbeat is silent for 60 s, one
   Critical system alert goes out, and one notice when it's back. Both are ordinary outbox
   rows, routed like the rest.
9. **The outbox is append-only now.** Its unused `status` column is gone: the state lives in
   the route and the deliveries (migration `0008`).
10. **For development, `tools/notify-sink`** stands in for the flow and the relay on
    127.0.0.1 and keeps what it receives. A plain-http flow URL is accepted only for
    127.0.0.1 or localhost.

## Consequences

- **No message reaches anyone for real until IT answers O-05** and real recipients replace the
  placeholders. The sink shows each message as it would arrive.
- **IT builds the flow to the input below.** Its "When a HTTP request is received" trigger
  posts `card` to the channel or chat named in `target`.
- **Operating it:** the notifier is its own process, like monitor-core. Stopping it doesn't
  lose anything: messages wait in the outbox, and deliveries resume where they stopped,
  within the 24 h.
- **Still to come in Phase 2:** the shift handover (SES-03, O-11), the reason workflow
  (WF-01…03, A-05), and the WebSocket for pop-ups and purges.

### The flow's input (`centerline.notification/1`)

| Field | What it carries |
|---|---|
| `schema` | `centerline.notification/1` |
| `dedupKey` | One per message × channel × recipient; the same on every retry |
| `messageId` | The delivery's id, the same on every retry |
| `type`, `severity` | The routing kind, and CRITICAL, WARNING, MISMATCH, OK, INFO or TEST |
| `test` | True for a TEST message |
| `target` | The recipient the routing named: a channel or chat the flow knows |
| `title`, `text`, `facts`, `link`, `footer` | The message: subject, sentence, name/value facts, the link into Centerline, the reference |
| `card` | The same as an Adaptive Card 1.4, ready to post |

## Tests

- `services/notifier/tests/test_notifier_units.py`:
  - the retry schedule;
  - routing types, validation, the ACT-03 guard and matching;
  - what each kind of message says, in email and on Teams.
- `services/notifier/tests/test_notifier_store.py`:
  - routing once, with what matched frozen, and expiry;
  - the retry schedule with the same message, up to the permanent failure;
  - a finished delivery is never sent again, even against the database's owner;
  - leases and restarts;
  - the monitor-core watcher.
- `services/notifier/tests/test_notifier_service.py`, the service against a fake flow and a fake relay:
  - a message reaches both channels;
  - a Teams outage doesn't hold up email, and the flow's signature never shows;
  - a relay that drops before its 250 gets the same Message-ID again;
  - a channel not set up says so.
- `services/api/tests/test_notifications_api.py`:
  - routing versions and the ACT-03 guard;
  - the write-only channel settings;
  - TEST messages, and re-driving only a permanent failure with a reason;
  - who may do each.
- `test_access.py` and `test_roles.py` cover the new routes and tables.
- Checked in a browser on a scratch stack with the sink: the routing editor, the channel
  settings, a TEST message and a system alert followed to delivery.
