# ADR-0025: Shifts, the handover and the reason workflow (Phase 2, second slice)

- **Status:** Accepted. Amended by [ADR-0028](ADR-0028-polling-idempotency-g2-acceptance.md) (2026-10-06): polling stays instead of the WebSocket, and a closed
  request's status is the purge. Amended by [ADR-0031](ADR-0031-ocap-library-deterministic-path.md) (2026-10-06): after the answers, up to three OCAP
  sections are offered, and a Manager guides only when none apply; the guidance can carry one file or become a reusable OCAP
- **Date:** 2026-10-01
- **Decider:** Szyrelle (system owner), on 2026-10-01:
  - an unfinished request at the shift's end closes, and the next shift gets a new one;
  - the handover warns 5 min before, then hands over;
  - only HMI mismatches ask for a reason;
  - the follow-up questions are two fixed ones that an Administrator can edit.

  The rest follows guide §7.1 and §12.
- **Related:** [ADR-0014](ADR-0014-monitor-core.md) (events), [ADR-0016](ADR-0016-accounts-sign-in-and-roles.md)
  (sessions and roles), [ADR-0020](ADR-0020-database-roles.md) (the role), [ADR-0022](ADR-0022-placeholder-sku.md)
  (no HMI judging on the placeholder SKU), [ADR-0023](ADR-0023-notifier.md) (the escalation is routed and delivered)
- **URS:** WF-01…03, SES-03, SES-05, A-05, A-07, GDE-01 (in part), PER-01; closes O-11

## Context

- **The notifier is built** (ADR-0023). Next in Phase 2 come the shift handover (SES-03) and the reason workflow
  (WF-01…03). The guide left two things open (O-11): the handover's steps, and what happens to a request still
  unfinished when the shift ends.
- **Guide §7.1** describes the full workflow:
  1. a request;
  2. a reason;
  3. at most two follow-up questions from the AI, with fixed questions when the AI is slow or down;
  4. up to three OCAP sections to choose from;
  5. the operator acknowledges having read the section;
  6. with no match, a Manager writes guidance (GDE-01).

  There is no OCAP library or ai-worker yet.
- **Shifts** are A 06:00–14:00, B 14:00–22:00 and C 22:00–06:00, Asia/Manila. A shift's production date is the
  date it starts (A-07).

## Decision

1. **Shift instances.** Each shift that has something on record is a row in `shift_instance`: its code, start,
   end and production date. It is made when first needed and never changed (`centerline_common.shifts`).
2. **One request per HMI mismatch per shift** (WF-01). The database enforces it with
   `UNIQUE (event_id, shift_instance_id)`. A request is made:
   - with the event, in the same transaction, when monitor-core opens an HMI mismatch. Replaying the journal
     makes no second request.
   - when an operator signs in, for each HMI mismatch still open from before. Signing in again in the same shift
     makes no second one.

   Actual Warning and Critical events ask for no reason (owner). Acknowledging a Critical stays the Manager's (ADR-0016).
3. **The steps** (`workflow_request.status`): the operator's reason, then the operator's answers to the follow-up
   questions, then a Manager's guidance, then the operator's acknowledgment, then done.
   - With no follow-up questions set, the reason goes straight to guidance.
   - Each step is an entry in `workflow_entry`: who, when, and the text exactly as typed, in English or Filipino.
     An answer also keeps the question as it was asked. Entries can't be changed or deleted, even by the
     database's owner.
   - Only the operator of the request's shift writes its reason, answers and acknowledgment. Only a Manager
     writes guidance.
   - The api refuses a step out of order (`wrong-step`), a request of another shift (`other-shift`) and a closed
     one (`request-closed`, saying why it closed).
4. **No OCAP yet.** Every request takes guide §7.1's "no match" path: a Manager writes the guidance for that event
   (GDE-01), and the operator acknowledges reading it.
   - Matching OCAP sections, the AI's questions and the AI summary come with the OCAP library and the ai-worker
     (Phase 3).
   - The fixed questions stay as the AI's fallback.
5. **The follow-up questions** are two fixed ones to start with (owner): "What was changed, and why?" and "Is the
   product affected?".
   - An Administrator edits them on Configuration → Reasons: at most two, with a reason, audited.
   - Every set is kept with who changed it and when (`workflow_settings`, append-only).
   - A change applies to every request whose answers aren't in yet.
6. **A request closes:**
   - when its event closes: back on target (resolved), replaced by a newer mismatch (superseded), or cancelled by
     a SKU changeover or monitoring switched off;
   - when its shift ends with the request unfinished (owner): closed as **not answered**, at the shift's end.
     If the mismatch is still open, the next shift's operator gets a new request when they sign in.

   monitor-core closes ended shifts' requests every 2 s, as it does its other timed checks.
7. **The escalation** (WF-03, A-05): a request still open 15 min after it was made alerts Management once.
   - monitor-core writes a `workflow_escalation` notification to the outbox, with the dedup key
     `workflow:<request>:escalation`. The notifier routes it as **Reason overdue (15 min)**.
   - The message says which step the request waits for, and links to it on the Reasons page.
   - The clock starts when that shift's request is made, so a carried-over mismatch gives the new operator a full
     15 min.
8. **The handover** (SES-03, O-11; owner: warn, then hand over):
   - **The warning.** From 5 min before 06:00, 14:00 and 22:00, the operator's screen shows a bar under the header
     with the time left. The bar corrects for the browser's clock skew.
   - **At the boundary**, the operator's session ends. The next request from that browser gets `401 shift-over`,
     audited as `auth.shift_over`, and the page signs out with "Your shift ended at 14:00".
   - **A left-over session.** If the browser was closed, nothing looks the session up again. The next operator
     sign-in then ends it the same way, so it never blocks the incoming operator, at either workstation.
   - **The incoming operator** signs in as usual, and their sign-in opens the shift's requests (decision 2).
   - Manager and Administrator sessions don't end with the shift.
9. **Unsent text stays in this browser only** (SES-05, guide §7.1), under `centerline.draft.<request>.…`. It is
   cleared:
   - on every sign-out, including the shift's end, a takeover and an expired session;
   - when the browser next talks to the api after its session ended;
   - when the request closes.

   The server's WebSocket purge comes with the WebSocket.
10. **The Reasons page** (Alarms → Reasons; the sidebar badge counts what waits for you):
    - Operators see their shift's requests. Managers and Administrators see every open one and those closed in the
      last day.
    - The requests are grouped as waiting for you, waiting for someone else, and closed.
    - An event's detail lists its requests with every entry, as evidence.
11. **The pop-up** (PER-01: within 3 s of the event). An operator's browser asks for the requests every 2 s, like
    the live page (ADR-0015), and shows a pop-up for each new one. Other browsers ask every 5 s. The WebSocket
    replaces both later.
12. **Migration `0009_workflow`** adds the tables and their guards:
    - The guide's data model names a table per step (`operator_input`, `clarification`, `acknowledgment`,
      `manager_guidance`). They are one table here, `workflow_entry`, with the step as its kind: the same
      evidence, in the order it was written. `ocap_recommendation` comes with OCAP.
    - `shift_instance`, `workflow_entry` and `workflow_settings` are append-only.
    - On a `workflow_request`, only its status, escalation and closing move, and only while it's open. It is
      escalated at most once.
    - `centerline_app` may add and read them, and update only a request.

## Consequences

- **The real line asks no one for reasons yet.** HMI mismatches need the SKU field and its targets (O-15). On the
  placeholder SKU (ADR-0022), HMI isn't judged, so there are no mismatches and no requests. The workflow was
  shown on the simulator demo, which had an operator account for it; the demo was removed on 2026-10-03.
- **A shift where no operator signs in** gets no requests for the mismatches carried over, so nothing escalates
  for them. They stay on the Alarms pages, and new mismatches in that shift still get requests and escalations.
- **The boundary is the server's clock.** An operator in the middle of typing at 14:00 loses the unsent text, as
  the owner decided. The bar has warned them for 5 min.
- **The escalation reaches Management only through the routing.** The proposal sends Reason overdue to Management
  on both channels, still to placeholder recipients until O-05.
- **Still to come:** in Phase 2, the WebSocket for pop-ups and purges, and G2's acceptance tests (AT-04…06). In
  Phase 3, the OCAP library and the ai-worker: the AI's questions and summaries, and OCAP matching.

## Tests

- `services/api/tests/test_workflow_api.py`:
  - the whole flow, with who may write each step, the text kept as typed, and the entries never changed;
  - the Administrator's questions, and with none the reason going straight to guidance;
  - a sign-in opening a request for each HMI mismatch still open, once per shift;
  - another shift's request and a closed one taking nothing;
  - the operator session ending with its shift (`401 shift-over`, audited);
  - a session left over from the last shift blocking no one at the other workstation.
- `services/api/tests/test_shifts_unit.py`: every moment belongs to one shift, dated by its start, and labelled in
  Manila time.
- `services/monitor_core/tests/test_monitor_workflow.py`:
  - an HMI mismatch asks that shift's operator, and the request closes with the event;
  - Actual events ask nothing;
  - the 15-min escalation, sent once;
  - an unfinished request closing as not answered when its shift ends.
- `services/notifier/tests/test_notifier_units.py`: the Reason overdue message says which step it waits for and
  links to the request.
- `test_access.py`, `test_roles.py` and `test_db.py` cover the new routes, grants and migration.
- **Checked in a browser on the simulator demo, 2026-10-01 13:53–14:01:**
  - an operator's reason in Filipino and the two answers; a Manager's guidance; the operator's acknowledgment;
  - at the 14:00 boundary: the bar from 13:55; the sign-out at 14:00:00; the unsent draft cleared; two
    unfinished requests closed as not answered; the next operator's sign-in opening shift B's requests.
