# Centerline api: Analytics, Configuration, Monitoring, Notifications, Reasons and OCAPs

The api service from the SDD (§3, §10). So far it contains:

- **Analytics & Correlation over Timebase history**
  ([ADR-0008](../../docs/decisions/ADR-0008-analytics-on-timebase.md)). The
  browser calls this service; the service calls the read-only Timebase REST API
  (ANA-02). Nothing is written to Timebase, and paired data isn't stored
  (ANA-03, ANA-21).
- **The Configuration page's endpoints**
  ([ADR-0011](../../docs/decisions/ADR-0011-configuration-page.md),
  [ADR-0012](../../docs/decisions/ADR-0012-rules-configuration-postgresql.md)):
  - the MQTT broker and historian connections;
  - versioned edits of the parameter register;
  - the monitoring rules: each zone's target, limits and delays, as immutable
    versions activated now or at a set time (ADR-0027: no SKU).

  They live in PostgreSQL.
- **The live Digital Centerline page's data**
  ([ADR-0015](../../docs/decisions/ADR-0015-live-centerline-page.md)), read-only:
  - monitor-core's heartbeat, with every zone's values and states;
  - the events, each with its transitions, notifications and the rule it was judged by;
  - the brief setpoint changes.

- **The Notifications log, TEST messages and re-drives, the routing versions and the
  Teams and email settings** ([ADR-0023](../../docs/decisions/ADR-0023-notifier.md)).
  The notifier service delivers; this one shows and configures it.

  monitor-core decides every state; this service only reads what it wrote. A
  Manager's acknowledgment of a Critical is the one thing written here.
- **Accounts, sign-in and roles** ([ADR-0016](../../docs/decisions/ADR-0016-accounts-sign-in-and-roles.md)): local accounts, server-side sessions,
  and the owner's decisions on who may do what, checked on every call. An operator's session ends with its shift ([ADR-0025](../../docs/decisions/ADR-0025-shifts-and-reasons.md)).
- **The reason workflow** ([ADR-0025](../../docs/decisions/ADR-0025-shifts-and-reasons.md), [ADR-0031](../../docs/decisions/ADR-0031-ocap-library-deterministic-path.md)). monitor-core makes a request for every HMI mismatch, one per shift. Here:
  - the operator gives the reason and answers the follow-up questions;
  - up to three sections of the Active OCAPs are offered; the operator chooses one and acknowledges it, or says none
    of them apply;
  - then a Manager gives guidance, with one PDF or Word file and, if they like, kept as a reusable OCAP; the operator
    acknowledges it;
  - an Administrator sets the questions.
- **The OCAP library** ([ADR-0031](../../docs/decisions/ADR-0031-ocap-library-deterministic-path.md)), without AI for now:
  - a Manager uploads a PDF or Word file (20 MB at most), scanned by ClamAV before it's kept;
  - it's read into sections with their pages, as a Draft;
  - the Manager activates it, keeping or retiring the earlier version, or suspends one;
  - every role reads the library and searches the Active versions by keyword (PostgreSQL full-text search,
    English or Filipino).

> **Sign in first.** Every endpoint except signing in and `/api/v1/health/live`
> needs an account. The HTTPS proxy isn't in place yet, so keep the api on
> 127.0.0.1 for now.

## Run

```bash
docker compose -f deploy/dev/compose.yaml up -d  # the database; see deploy/dev/README.md (password file first)
cd services
uv venv .venv --python 3.12                     # once
uv pip install --python .venv/bin/python -r requirements.txt
cp api/config.example.json api/config.json      # git-ignored; see "Configure"
PYTHONPATH=common:api .venv/bin/uvicorn centerline_api.main:create_app --factory --host 127.0.0.1 --port 8000
```

On start the api applies `db/migrations`. On the first start it also imports
the register file and the old `config/history/audit.jsonl`. Without the
database it still starts, but nobody can sign in: everything except
`/api/v1/health/live` answers 503 until the database is back.

The first Administrator is created on the server, once:

```bash
PYTHONPATH=common:api .venv/bin/python -m centerline_api.auth create-admin \
    --username szyrelle --name "Szyrelle" --out ../config/secrets/first-admin-password
```

This writes a temporary password to that file (0600). It works for 24 h. Sign in
with it, choose your own password, then delete the file. Without `--out` the
command prints the password instead. It makes the account Manager and
Administrator unless `--roles` says otherwise. `temporary-password --username …`
issues a new temporary password, for example for a locked-out Administrator. Both
are audited as done on the server's command line.

Then start the client (`cd client && npm run dev`) and open
<http://localhost:5173/analytics> or <http://localhost:5173/configuration>.
Vite proxies `/api` to this service.
Interactive API docs are at <http://127.0.0.1:8000/api/docs>.

## Configure (`api/config.json`)

| Key | Meaning |
|---|---|
| `timebase.base_url`, `timebase.dataset` | `http://10.156.116.179:4516`, `dressings`. Used until a historian is saved on the Configuration page, which then takes precedence |
| `timebase.auth` | `none` works today; `bearer` + `token_file` (a file outside the repo) if the server starts enforcing tokens |
| `register` | The parameter register (`config/parameter-register.json`) |
| `config_dir` | Where the Configuration page keeps its files (default `config/`): `connections.json`, `secrets/`, `history/` |
| `database` | `host`, `port`, `dbname`, `user`, `password_file`. Leave it out to use the development database as the services' role: `centerline_app` with `config/secrets/postgres-app-password` (ADR-0020) |
| `migrate_database` | The owner, for the migrations and the role's password at start. Without a `database` block it's the development owner (`centerline`, `config/secrets/postgres-password`); with one, give it here or migrate separately |
| `migrate_on_start` | Apply `db/migrations` when the api starts (default true) |
| `analytics.max_range_days` | Longest range a user may query (ANA-18, default 30) |
| `analytics.pair_limit` | Paired-bucket limit (ANA-19, default 10,000) |
| `analytics.min_coverage` | Share of a bucket that must be known (default 0.5) |
| `analytics.heartbeat_gap_s` | Machine silence that counts as a data gap (default 120 s) |
| `analytics.fetch_window_s`, `fetch_workers` | 6 h per Timebase request, 3 in parallel |
| `auth.operator_workstations` | `[{"name": "Line desk", "ip": "10.0.0.5"}, …]`: operators sign in only there (SES-04). Empty (the default): no operator can sign in yet |
| `auth.trusted_proxies` | The proxy's address: from it, `X-Forwarded-For` gives the browser's address |
| `auth.secure_cookie` | Mark the session cookie `Secure` (default true). Left out, it's false when `CENTERLINE_SCHEME=http`, as the Docker stack's plain-HTTP proxy sets it ([ADR-0032](../../docs/decisions/ADR-0032-docker-stack-over-http.md)) |
| `auth.*` (others) | The URS values, for tests only: 15 min Manager/Administrator inactivity (warned at 13), 5 min operator takeover, 10 privileged sessions, 5 failures lock for 15 min, 24 h temporary passwords, 12-character minimum, last 5 blocked, Argon2id cost |
| `scanner` | The malware scanner for uploads (SEC-01, ADR-0031): `{"type": "clamd", "host": "clamav", "port": 3310, "timeout_s": 60}` in the Docker stack. Default `{"type": "none"}`, for a development PC only: uploads are kept marked *not scanned*. With `clamd` and no answer, uploads are refused |
| `cors_origins` | Browser origins allowed to call the api directly |
| `audit_log` | JSON-lines log of query metadata (no data) |

The Analytics-valid ranges (ANA-10/11) aren't configured here any more: an
Administrator uploads the CSV on Configuration → Analytics ranges, and each
accepted file is a version in the database
([ADR-0029](../../docs/decisions/ADR-0029-analytics-ranges-and-g4-acceptance.md)). The tab's
template lists the register's parameters with their units; `analytics-ranges.example.csv`
shows the format, with placeholder values, not engineering ranges. A file that fails
validation is rejected as a whole. A leftover `analytics.ranges_csv` is ignored, with a
warning in the log.

## Endpoints

Every endpoint's roles are in [ADR-0016](../../docs/decisions/ADR-0016-accounts-sign-in-and-roles.md), and `tests/test_access.py` checks each route
against that list. State-changing calls need the `X-Centerline-CSRF: 1` header.

Every POST that saves something also needs an `Idempotency-Key` header: a new random value per action, the same one
when retrying it ([ADR-0028](../../docs/decisions/ADR-0028-polling-idempotency-g2-acceptance.md)). The answer is kept
24 h for that session and key. A repeat gets it again, marked `Idempotent-Replayed: true`, and nothing is saved twice.
Reusing a key for a different request answers 422; reusing it while the first request is still running answers 409.
Exempt: signing in and out, and the POSTs that save nothing (`…/check`, connection tests, the latest values,
Analytics queries, the mapping import and discovery). The account answers that carry a temporary password are never
kept: a repeat answers 409. Times in answers are ISO 8601 UTC ending in `Z`.

| Method | Path | Returns |
|---|---|---|
| POST | `/api/v1/auth/login`, `/auth/takeover` | Sign in with a username, email or Employee ID (any case); sets the session cookie. Takeover: at an operator workstation, when the line's operator session has had no heartbeat for 5 min |
| GET | `/api/v1/auth/session` | Who is signed in, their roles, the session's inactivity limit, and the shift (an operator's session ends with it, warned 5 min before); doesn't count as activity |
| POST | `/api/v1/auth/activity`, `/auth/password`, `/auth/logout` | Still here (restarts the 15 min limit); change your own password (your other sessions sign out); sign out |
| GET, POST | `/api/v1/users` | Administrator: the accounts; create one (its temporary password is in this answer only) |
| PUT | `/api/v1/users/{id}` | Administrator: name, email, Employee ID, roles, enabled. New roles or disabling sign it out everywhere |
| POST | `/api/v1/users/{id}/temporary-password` | Administrator: a new temporary password, shown once; unlocks the account and signs it out |
| POST | `/api/v1/events/{id}/acknowledge` | Manager: acknowledge an open Critical, once per Critical period; monitor-core stops its repeats within 2 s |
| GET | `/api/v1/events?open=&kind=&severity=&reached=&channel=&since=&until=&before=&limit=` | Events newest first, filtered; `next` pages further back (ADR-0019) |
| GET | `/api/v1/events/counts` | Open events by kind and severity, and the Criticals not acknowledged: the sidebar badge and the bell |
| GET | `/api/v1/events/export.csv` | Manager, Administrator: the matching events as UTF-8 CSV, Manila times, up to 10,000; audited (EXP-01) |
| GET | `/api/v1/monitoring/control` | Zones switched off (who, when, why) and maintenance windows not ended, each scheduled, active or overdue |
| POST | `/api/v1/monitoring/switch` | Manager: switch zones off (a reason is required) or on again; only zones that change are recorded (MON-01) |
| GET, POST | `/api/v1/maintenance` | Every window, newest first; Administrator: open one for the line or chosen zones, now or at a set time, with a planned end (MNT-01) |
| POST | `/api/v1/maintenance/{id}/extend`, `/end` | Administrator: move the planned end; end it now (before its start: cancel it) |
| GET | `/api/v1/health/live` | `{"status": "ok"}` without signing in, for container health checks |
| GET | `/api/v1/health` | Service status, register version and where it came from, database (reachable, rules, mapping and routing in effect, audit chain intact), monitor-core's last heartbeat (alive, judging, why not), the notifier's (each lane, the backlog), Timebase reachability and clock offset |
| GET | `/api/v1/analytics/options` | Variables (each active zone's actual and setpoint, plus analytics-only actuals), buckets, aggregations, shifts, groupings, defaults, limits, the ranges version in effect |
| POST | `/api/v1/analytics/query` | One analysis: pairs, statistics, groups, exclusion counts, bucket counts, the ranges applied, size guard, warnings. The query log keeps who ran it and its description, never the data |
| GET | `/api/v1/config/connections` | Broker and historian settings. Secrets are never returned, only whether each is set |
| PUT | `/api/v1/config/connections/historian`, `/mqtt` | Save a connection with a reason. A typed secret goes to `secrets/` (0600); an empty one keeps the saved one |
| POST | `/api/v1/config/connections/historian/test`, `/mqtt/test` | Try the form's settings without saving: datasets, tag count and clock offset; or connect, listen 3–30 s and report topics and register tags found |
| GET | `/api/v1/config/historian/tags?q=` | Timebase tags under the machine namespace, with the zone already using each |
| POST | `/api/v1/config/historian/latest` | Latest value of up to 100 tags |
| GET | `/api/v1/config/register` | The register and its 15 most recent changes |
| PUT | `/api/v1/config/register/parameters/{id}` | Replace a parameter's status and zones. Needs `baseVersion` (409 if stale) and a reason; tags are checked against Timebase |
| GET | `/api/v1/config/rules` | Rules in effect, scheduled activations, every version with its status, and what the rules in effect leave each zone without (`gaps`: limits, or a target) |
| GET | `/api/v1/config/rules/proposal` | The Phase 0 starting point: ADR-0002 delays and limits, the ADR-0010 stop pause |
| GET | `/api/v1/config/versions/{n}` | Rules v*n*: settings, rows, gaps, and whether its content still matches its hash. A version saved for a SKU before ADR-0027 also has `carryOver`: that SKU's rows as the zones' own, for a new version to start from |
| POST | `/api/v1/config/versions/check` | Validation and gaps for a draft, without saving |
| POST | `/api/v1/config/versions` | Save a new version. Needs `expectedLatest` (409 if another was saved) and a reason; `activate` = `no`, `now` or `at` |
| POST | `/api/v1/config/versions/{n}/activate` | Activate now or `at` a future time; an older version is a rollback. Needs `expectedActive` and a reason |
| POST | `/api/v1/config/activations/{id}/cancel` | Cancel a scheduled activation before it takes effect |
| GET | `/api/v1/config/mappings` | Mapping in effect and its coverage, scheduled activations, versions, the tags monitor-core needs, the connection's topic filters |
| GET | `/api/v1/config/mappings/versions/{n}`, `/versions/{n}/export.csv` | Mapping v*n* with coverage, warnings and whether it's intact; or as `tag,topic,field` CSV |
| POST | `/api/v1/config/mappings/versions/check`, `/versions` | Check a mapping, or save it (`expectedLatest`, reason, `activate`); activation needs a place for every tag |
| POST | `/api/v1/config/mappings/versions/{n}/activate`, `/activations/{id}/cancel` | Activate now or later (older = rollback), or cancel a scheduled one |
| POST | `/api/v1/config/mappings/import` | Rows from a probe `topic-map.json` or a CSV, for the editor; nothing is saved |
| POST | `/api/v1/config/mappings/discover` | Listen 3–30 s on the saved broker (read-only) and return each tag's place |
| GET | `/api/v1/monitoring/live` | monitor-core's latest heartbeat (alive after < 60 s, judging or why not, versions), every zone's values, bands, states and pending delays grouped by parameter, the open events and their counts |
| GET | `/api/v1/events/{id}` | One event: the rule pinned to it, the rules, mapping and register versions it was judged under, every transition with its inputs, its notifications, its reason requests |
| GET | `/api/v1/monitoring/brief-changes?limit=` | Setpoints back on target before the delay ended (HMI-05), newest first |
| GET | `/api/v1/notifications?state=&before=&limit=` | Manager, Administrator: messages newest first (all, on their way, failed, not sent, TEST) with their deliveries, and the counts waiting and failed |
| GET | `/api/v1/notifications/{id}` | One message: its payload, how it was routed, each delivery with what was sent and every attempt |
| POST | `/api/v1/notifications/test` | Administrator: a TEST - NO PRODUCTION EVENT message to one recipient, outside the routing; audited (NOT-07) |
| POST | `/api/v1/deliveries/{id}/redrive` | Administrator: send a permanent failure again, with a reason; audited (NOT-05) |
| GET | `/api/v1/config/routing`, `/routing/proposal`, `/routing/versions/{n}` | Who gets which messages: the routing in effect, the Phase 2 proposal, one version with its warnings |
| POST | `/api/v1/config/routing/versions/check`, `/versions`, `/versions/{n}/activate`, `/activations/{id}/cancel` | Administrator: check, save, activate (not while a kind of Critical reaches nobody, ACT-03), cancel a scheduled one |
| GET | `/api/v1/config/analytics-ranges`, `/template.csv`, `/versions/{n}`, `/versions/{n}/original.csv` | The Analytics-valid ranges in effect, scheduled activations and every version; a template to fill in; one version's rows and whether it still fits the register; the file exactly as uploaded (ADR-0029) |
| POST | `/api/v1/config/analytics-ranges/versions/check`, `/versions`, `/versions/{n}/activate`, `/activations/{id}/cancel` | Administrator: check a file (base64, as uploaded), save it whole as a new version with a reason, activate now or later (an older one: rollback), cancel a scheduled one |
| PUT | `/api/v1/config/connections/notifications` | Administrator: the link base, the Teams flow URL and the SMTP relay; the URL and the password are write-only |
| POST | `/api/v1/config/connections/notifications/email-test` | Administrator: connect to the relay and sign in, sending nothing |
| GET | `/api/v1/workflow/requests`, `/workflow/requests/{id}` | Reason requests with every entry, the follow-up questions in effect and the counts per step: an operator sees the shift's, others the open ones and the last day's |
| POST | `/api/v1/workflow/requests/{id}/reason`, `/answers`, `/ocap`, `/acknowledge` | The shift's operator: the reason (kept as typed), the answers in the questions' order, the OCAP section chosen among those offered (`sectionId`, or `null`: none of these apply), the acknowledgment of the section or the guidance. 409 out of order, for another shift, or closed |
| POST | `/api/v1/workflow/requests/{id}/guidance` | Manager: the guidance for the operator (GDE-01); `attachment` (one PDF or Word file, base64, scanned) and `reusable` (`code`, `title`, `language`: also kept as an OCAP, active at once) are optional |
| GET | `/api/v1/workflow/attachments/{id}` | A guidance's file, as uploaded |
| GET | `/api/v1/ocaps`, `/ocaps/search?q=`, `/ocaps/versions/{id}`, `/ocaps/versions/{id}/original`, `/ocaps/sections/{id}` | Every OCAP with its versions and their status; the Active sections that match the words, with an excerpt («…» around the matches); one version read into sections, with its history and whether the stored file still matches its SHA-256; the file as uploaded; one section with its citation |
| POST | `/api/v1/ocaps`, `/ocaps/{id}/versions` | Manager: a new OCAP (`code`, `title`, `language` `en` or `fil`, the file as base64, a reason), or a new version of one. Scanned, then read; a Draft. 422 for an infected or unreadable file (an old `.doc`, a scan without text), 503 with no scanner answering |
| POST | `/api/v1/ocaps/versions/{id}/activate`, `/suspend` | Manager: search it from now on (`earlier`: `keep` the OCAP's other Active versions or `supersede` them), or stop searching it; with a reason, audited |
| GET, PUT | `/api/v1/config/workflow` | The follow-up questions and their changes; Administrator: change them (up to two, with a reason; audited) |

Variables are `<parameter>.<zone>.actual` or `<parameter>.<zone>.setpoint`
([ADR-0009](../../docs/decisions/ADR-0009-setpoints-in-analytics.md)). Each
comes with a `label` such as "Vertical 1 · Setpoint", which is what the page
shows. A bare zone (`P02.V1`) still means its actual value.

```http
POST /api/v1/analytics/query
{ "from": "2026-09-28T00:00:00Z", "to": "2026-09-29T00:00:00Z",
  "x": "P02.V1.setpoint", "y": "P02.V1.actual", "bucket": "PT1M", "aggregation": "AVG",
  "shift": "ALL", "groupBy": "NONE", "groupStats": false }
```

Errors are RFC 9457 problem documents (`application/problem+json`). Invalid
queries return 422 with `errors: [{field, message}]`; Timebase failures return 502.

## How a query is computed

1. **Validate:** variables exist and differ, the range is in the past and
   within the maximum.
2. **Fetch** X and Y, plus each involved machine area's `_timestamp`, in 6 h
   windows with kept-alive connections. Unreadable Timebase spans are split
   down to 60 s and remembered.
3. **Clean:** every sample failing a check (bad quality, empty, not a number,
   NaN, infinite, outside the valid range) is counted, and the value is unknown
   until the next sample.
4. **Step series:** a value holds until the next sample, because Timebase stores
   on change. A machine area silent for more than 120 s is a data gap.
5. **Bucket:** time-weighted AVG, or the MIN / MAX in force, on buckets aligned
   to floor(t ÷ width) × width. A bucket counts when ≥ 50 % of it is known.
6. **Pair** where X and Y are both valid (and in the chosen shift). Above
   10,000 pairs, return no chart and the smallest larger bucket that fits.
7. **Compute** Pearson r, least squares, R², min, max, mean and SD (n − 1) with
   a two-pass method, per group when asked.

## Where configuration is kept (ADR-0011, ADR-0012)

| Where | Holds |
|---|---|
| Database `register_version` | Every register version, `<Manila date>.<n>`; numbers are never reused |
| Database `config_version`, `parameter_rule`, `config_activation` | Rules versions and their rows, activations |
| Database `mapping_version`, `tag_mapping`, `mapping_activation` | Tag mapping versions (each tag's topic and field) and their activations |
| Database `routing_version`, `routing_activation` | Notification routing versions and their activations (ADR-0023) |
| Database `audit_log` | Every save: time, action, summary, reason, versions, before and after; hash-chained |
| `config/parameter-register.json` | The current register, rewritten after each save for the Phase 0 tools and git. Hand edits aren't used: the page says so, and the next save keeps a copy in `history/` |
| `config/connections.json` | Broker, historian and notification settings without secrets (git-ignored) |
| `config/secrets/` | `mqtt-password`, `mqtt-ca.pem`, `timebase-token`, `timebase-password`, `teams-flow-url`, `smtp-password`, `postgres-password`, `postgres-app-password`; files 0600, folder 0700 (git-ignored) |
| `config/history/` | The old `audit.jsonl` (imported once, kept) and copies of hand-edited register files (git-ignored) |

History in the database is append-only: triggers refuse changes and deletions.
Rules roll back by activating an earlier version. The register can't be rolled
back on the page yet, but every version is kept.

## Tests

```bash
cd services && .venv/bin/python -m pytest      # 167 api tests (281 with monitor-core's, the notifier's and the acceptance suites), run as centerline_app: unit, schema, API against the mock Timebase and the database, MQTT on a local Mosquitto
CENTERLINE_TEST_CLAMD=127.0.0.1:3310 .venv/bin/python -m pytest api/tests/test_ocap_units.py   # also scan the samples with a real clamd
```

The tests use the register the mock Timebase was built for
(`tools/timebase-analysis/tests/parameter-register.json`), not the live one, so
edits on the Tags tab can't break them. The database tests need the
development database running. Each test gets a
fresh, migrated `centerline_test_*` database, dropped afterwards, so the
`centerline` database is never touched. Without the database those tests are
skipped, and so is the Mosquitto test when `mosquitto` isn't installed.

The OCAP tests read OCAPs generated by `tests/ocap_samples.py` (fpdf2 and python-docx), since the plant's real ones
aren't in the repository, and scan with a stand-in that speaks clamd's protocol. EICAR, the antivirus test file, is
hidden inside a Word file there: a real clamd finds it at the start of a file or of an archive's member only.

Statistics are checked against Python's `statistics.correlation` and
`linear_regression`. The API tests run against
`tools/timebase-analysis/tests/mock_timebase.py`, which reproduces the real
server's quirks.
