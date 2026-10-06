# ADR-0028: Polling instead of the WebSocket, Idempotency-Key and `Z` timestamps, and G2's acceptance suites

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decider:** Szyrelle (system owner), on 2026-10-06: the recommendations for O-22 and O-23 approved, and Phase 2
  closed out with the AT-04…06 suites
- **Amends:** SDD §5 step 5, §11 (the WebSocket, conventions) and invariant 3 (wake-ups);
  [ADR-0015](ADR-0015-live-centerline-page.md) ("WebSocket later") and [ADR-0025](ADR-0025-shifts-and-reasons.md)
  (the purge "until the WebSocket")
- **Closes:** O-22, O-23
- **URS:** PER-01 (the popup in 3 s), SES-05 (purges), IAM-04 (sessions ended at once); AT-04, AT-05, AT-06 (gate G2)

## Context

- **The SDD has one WebSocket** at `/api/v1/ws`, woken by `LISTEN/NOTIFY`, for popups, draft purges and closing
  revoked sessions. The pages poll instead: every 2 s for the live page and an operator's requests, 5–20 s
  elsewhere. The notifier polls its outbox every second.
- **The SDD's API conventions** ask for an `Idempotency-Key` on every POST that creates a record, and times ending in
  `Z`. Neither was built: the api wrote `+00:00`, and only versions (`expectedLatest`) and events (UUIDv7, dedup keys)
  were protected against a repeat.
- **G2 needs AT-04…06**, and no acceptance suite existed. The tests covered each requirement one by one.

## Decision

1. **Polling stays; no WebSocket for one line** (O-22).
   - An HMI mismatch already pops up for the operator within the 3 s PER-01 allows: the request appears on the next
     2 s ask.
   - A revoked session ends on its next request (IAM-04). The server deletes its rows at once, so nothing more is
     answered for it.
   - The purges SES-05 needs are on the request: a closed request's status tells the browser to drop its draft.
   - Ten sessions at most, asking every few seconds, are no load for the api or PostgreSQL.
   - The WebSocket and `LISTEN/NOTIFY` come back only with a second line or a measured need. That will be an ADR of
     its own.
2. **Every POST that creates a record needs an `Idempotency-Key`** (O-23, migration `0012`).
   - The api claims the key before the request runs and keeps the answer for 24 h. The same key again, from the
     same session and for the same request, gets that answer, marked `Idempotent-Replayed: true`, and nothing is
     saved twice.
   - A key is one session's: another browser can't replay it.
   - The answers to refuse:
     - the key reused for a different request: 422;
     - the first request still running: 409, `Retry-After: 1`;
     - the first request cut off before it answered: 409, outcome unknown.
   - An answer of 500 or more, or an exception, releases the key, so the request can be tried again.
   - **Exempt:** signing in and out, and the POSTs that save nothing:
     - Analytics queries;
     - the connection tests;
     - draft checks;
     - the latest values;
     - the mapping import and broker discovery.

     A test lists the 15 exempt routes and counts the 22 others, so a new POST route is a decision.
   - **Never kept:** the account answers that carry a temporary password. A repeat is refused with 409 rather than
     replayed.
   - **The web app** sends a new key with each POST, and sends it once more with the same key if the answer is lost
     on the way.
   - Not evidence: the services' role may update and delete these rows.
3. **Every time the api answers ends in `Z`** (O-23).
   - It's one formatter, `centerline_common.isotime`, also used by what monitor-core and the notifier store for the
     api to pass on: the heartbeat, payloads and the inputs of new transitions.
   - Records written before keep the `+00:00` they were stored with. Dedup keys and monitor-core's journal keep
     theirs: they're identifiers and an internal file.
   - The api tests' client fails on any `+00:00` in an answer.
4. **G2's acceptance suites are in `tests/acceptance/`** and run with the services' tests.
   - The api is called as the web app calls it. monitor-core's engine and its database writer judge a simulated line
     whose clock starts at the real time. The notifier delivers to stand-ins for the Teams flow and the SMTP relay.
   - Each test names its URS requirements (`@pytest.mark.urs`), and the run ends with which passed:
     - AT-04: IAM-01…04, SES-01…04;
     - AT-05: WF-01…03, SES-05;
     - AT-06: NOT-01…07.

## Consequences

- **G2 can be signed off on two runs still to make:**
  - AT-06 against the real Power Automate flow and SMTP relay, once IT gives them (O-05);
  - AT-04's cookie and workstation-IP checks behind the HTTPS proxy on the control-room PC (production).
- **AT-05 shows WF-01 on its guidance branch.** The OCAP branch is added with Phase 3, and AT-05 runs again then.
- **Restart the api to take migration `0012` and the new conventions.** Restart monitor-core and the notifier too,
  so the times they store end in `Z`. A browser still on the old page sends no key and gets 400 until it reloads.
- **A WebSocket isn't missed by the pages:** what they show is at most one polling interval old.

## Verification

- `services/api/tests/test_idempotency.py`:
  - which POSTs need a key;
  - a repeat replayed, and nothing saved twice;
  - a key reused for another request;
  - a key one session's own;
  - a temporary password never kept;
  - a request still running, or cut off;
  - keys past 24 h removed;
  - a failure releasing the key.
- The api tests' `Browser` client: a key on every POST, and no `+00:00` in any answer.
  `test_monitor_engine.py`: none in the heartbeat.
- `tests/acceptance/`: 15 tests, all 19 requirements of AT-04…06 passed on 2026-10-06.
- Every suite run together: 241 tests passed. The web app lints and builds.
