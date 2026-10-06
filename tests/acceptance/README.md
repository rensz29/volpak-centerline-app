# Acceptance suites

The URS v1.1 acceptance tests (§13) that the phase gates run, as automated pytest suites. Built so far:
- **AT-04, AT-05 and AT-06, for gate G2**
  ([ADR-0028](../../docs/decisions/ADR-0028-polling-idempotency-g2-acceptance.md)). All 19 of their requirements
  passed on 2026-10-06.
- **AT-08's deterministic part, for gate G3** ([ADR-0031](../../docs/decisions/ADR-0031-ocap-library-deterministic-path.md)): the OCAP library, the
  top three sections with their exact source, a Manager's guidance and the scanned uploads, with no AI running. Its
  seven requirements passed on 2026-10-06. G3 also needs AT-08's AI part.
- **AT-ANA-01…10, for gate G4**, on an independently calculated dataset
  ([ADR-0029](../../docs/decisions/ADR-0029-analytics-ranges-and-g4-acceptance.md),
  [../fixtures/analytics](../fixtures/analytics/README.md)). ANA-01…21 all passed on 2026-10-06.

## Run

```bash
cd services && .venv/bin/python -m pytest                                    # with every other test
cd services && .venv/bin/python -m pytest -c pyproject.toml ../tests/acceptance   # these alone
```

They need the development database ([deploy/dev](../../deploy/dev/README.md)). Each test makes its own database and
drops it; nothing touches the real `centerline` database, the plant broker or Timebase. The run ends with the URS
requirements shown, grouped as passed, failed or skipped.

## How they work

As black-box as the system allows:
- **the api** in-process, called as the web app calls it, with the CSRF header and an `Idempotency-Key` on every
  POST. The line is configured through it as the owner would (mapping v1, rules v1 from the Phase 0 proposal
  with each zone's target);
- **monitor-core's** engine and its database writer, judging a simulated line. Its clock starts at the real time, so
  it agrees with the api's shifts, and moves only when a test says so: 15 minutes of escalation take a second;
- **the notifier**, delivering to stand-ins for the Teams flow and the SMTP relay, with the flow's URL and the relay
  saved through the api's Connections endpoint, and the routing activated through the api;
- **a stand-in Timebase** for Analytics (`timebase_stub.py`), serving the reference dataset, recording every request
  and answering GET only. Each number the api returns is compared with the independent calculation's, within 10⁻⁹.

Each test names the requirements it shows with `@pytest.mark.urs(...)`.

## What each suite shows

| Suite | URS | Test |
|---|---|---|
| [AT-04](test_at04_accounts_and_sessions.py): local account, roles, password policy, staged handover, workstation restriction and takeover | IAM-01, IAM-02 | An Administrator makes accounts with their roles; each signs in by username, email or Employee ID; a 24 h temporary password, changed first |
| | IAM-03 | 12 characters at least, no known-breached ones, not the last five; five failures lock for 15 min; Argon2id hashes only |
| | IAM-04 | New roles, disabling or a password reset end every session at once |
| | SES-01, SES-02 | One operator session for the line; up to 10 others, which time out after 15 min with a warning 2 min before; operators never |
| | SES-03 | The operator's session ends with its shift (06:00, 14:00, 22:00) after a 5-min warning; the next operator signs in |
| | SES-04 | Operators only at the line's desks; a session silent 5 min is taken over; the same desk resumes its own |
| [AT-05](test_at05_reason_workflow.py): one reason workflow per shift, two clarifications at most, 15-min escalation | WF-01 | A mismatch gets one reason (kept as typed), its questions, a Manager's guidance and the operator's acknowledgment; an Actual event asks no one |
| | WF-01 | At most two follow-up questions; with none, the reason goes straight to guidance |
| | WF-02 | A finished request isn't asked again in its shift; the next shift's comes at the operator's sign-in |
| | WF-03 | A request still open after 15 min alerts Management once |
| | SES-05 | A request closes when its mismatch is resolved or superseded, so the browser drops the unsent text |
| [AT-08](test_at08_ocap_deterministic.py), deterministic part: top three approved OCAP sections, the exact source, the path without AI | OCP-01, OCP-02, WF-01, AI-01 | monitor-core judges a mismatch; after the reason and answers, up to three Active sections are offered, best first, a Draft never. The operator reads the chosen one exactly as it was read from the file, and the file byte for byte, then acknowledges it. No model runs |
| | OCP-03 | A Manager uploads PDF and Word versions and activates them with no second approval, keeping the earlier one or retiring it; each step is audited |
| | GDE-01, WF-01 | None apply: a Manager guides with one file and keeps the guidance as a reusable OCAP, which the next mismatch with those words is offered |
| | SEC-01 | Every upload is scanned first: an infected OCAP or guidance file is refused and audited, and with no scanner answering nothing is saved |
| [AT-06](test_at06_notifications.py): Teams Flow bot and SMTP delivery, retry, deduplication, Administrator re-drive | NOT-01…04, NOT-06 | A Warning, then a Critical, reach Teams through the flow's signed trigger and email through the relay, each tried within 10 s |
| | NOT-03, NOT-06 | A Teams outage doesn't hold up email; a replayed step is still one message; what the relay accepted is never sent again |
| | NOT-04, NOT-05 | Retries at 30 s, 1, 5, then every 15 min for 24 h; then a permanent failure, re-driven only by an Administrator with a reason |
| | NOT-07 | Routing by type and severity per channel; only Administrators send TEST messages |
| [AT-ANA-01](test_at_ana_analytics.py): the variables, optional shift, different X and Y | ANA-01, -04, -05 | The zones' actuals and setpoints (ADR-0009); X ≠ Y; shift All or one; no SKU (ADR-0027) |
| AT-ANA-02: six buckets, three aggregations, 1-minute Average by default | ANA-06, -07 | All 18 bucket × aggregation results match the independent ones |
| AT-ANA-03: exclusion counts, no zero substitution | ANA-08, -09 | One sample of each excluded kind counted by reason, a 185 s data gap; missing buckets absent, never 0 |
| AT-ANA-04: the ranges CSV, atomic and versioned | ANA-10, -11 | An incomplete file rejected whole; versions applied to queries; a rollback; the original kept byte for byte |
| AT-ANA-05: r, the least-squares equation, R², the statistics | ANA-12, -13 | Within 10⁻⁹ of the independent calculation; strength and direction; fewer than 3 pairs not computable |
| AT-ANA-06: Scatter and Trend on the same result | ANA-15 | One set of pairs in UTC milliseconds, with gaps and both units; both charts built from it |
| AT-ANA-07: groups, group statistics, sample sizes, 10 groups | ANA-16, -17, -20 | By shift across 14:00 Manila; by production date: 10 shown, 2 hidden, insufficient and low sample sizes |
| AT-ANA-08: 30-day maximum, 10,000 pairs | ANA-18, -19 | Too long or future ranges refused; 87,452 pairs at 10 s: no chart, 5 minutes recommended |
| AT-ANA-09: read-only historian access from the backend, no copy of the series | ANA-02, -03, -21 | Timebase only asked with GET; no table changed by a query; the browser calls the api only |
| AT-ANA-10: correlation is not causation | ANA-14 | Every result carries the wording, the page shows it |

## Not shown yet

- **AT-06 against the real channels.** The stand-ins answer as the flow and the relay do. G2's sign-off runs the suite
  once more against the real Power Automate flow and SMTP relay, when IT gives them (O-05). Teams posting as Flow bot
  (NOT-02) is the flow's part.
- **AT-04 behind the HTTPS proxy.** The cookie's `Secure` flag and the workstation addresses the proxy passes on are
  checked here on the api alone. On the control-room PC they go through the proxy.
- **AT-ANA-06's and AT-ANA-10's look on the page.** The tooltips, zoom, pan and reset of the two tabs, and the
  wording as shown, are checked in a browser; the suite shows the data and the code they come from. Exports (also
  AT-ANA-10) wait for O-04.
- **AT-08's AI part.** The clarification questions, the summary beside the source, translation and embedding search
  come with the ai-worker once the model is chosen (O-01). Then AT-08 runs with Ollama up and again with it stopped.
  The sample OCAPs are generated (`services/api/tests/ocap_samples.py`): the plant's real ones are needed before G3.
  Scanning uses a stand-in for clamd. The real one is checked by `services/api/tests/test_ocap_units.py` with
  `CENTERLINE_TEST_CLAMD` set.
- **The other suites:**
  - AT-01…03: tested in `services/monitor_core/tests` for G1;
  - AT-07: Phase 5.

  They move here as their gates come.
