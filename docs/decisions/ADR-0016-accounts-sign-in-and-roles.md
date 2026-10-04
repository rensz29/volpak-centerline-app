# ADR-0016: Accounts, sign-in and roles (Phase 1)

- **Status:** Accepted
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner)
- **Related:** [ADR-0011](ADR-0011-configuration-page.md), [ADR-0012](ADR-0012-rules-configuration-postgresql.md),
  [ADR-0013](ADR-0013-tag-mappings.md) (the Configuration page), [ADR-0014](ADR-0014-monitor-core.md) (acknowledgments),
  [ADR-0015](ADR-0015-live-centerline-page.md) (the live page)
- **URS:** IAM-01…04, SES-01…04, ACT-04; guide §12 (security, identity and sessions); closes **O-13**

## Context

- Until now anyone who could reach the api could change everything. So it stayed on
  127.0.0.1, and nothing recorded who made a change.
- The SDD fixes most of the rules (guide §12):
  - local accounts with Argon2id;
  - a sign-in name that is the username, email or Employee ID, in any case;
  - passwords of at least 12 characters, checked against an offline breached-password
    list, with the last 5 blocked;
  - a 15 min lockout after 5 failed sign-ins;
  - temporary passwords that last 24 h;
  - server-side sessions (DD-06);
  - the session rules per role, and the cookie flags.
- The SDD left O-13 open: who may import mappings, disable monitoring and open
  Analytics. Which role may change which Configuration tab was only assumed (§11).
- The owner decided both on 2026-09-30, and decided that one account may hold two roles.

## Decision

1. **Roles** (the owner's decisions, O-13):

   | Area | Read | Change |
   |---|---|---|
   | Digital Centerline, events | every role | acknowledging a Critical: Manager (ACT-04) |
   | Analytics | Manager, Administrator | (read-only) |
   | Configuration: Rules tab (SKUs, targets, limits, delays) | Manager, Administrator | **Manager** |
   | Configuration: Connections, Tags, Mappings (mapping import included) | Manager, Administrator | **Administrator** |
   | Monitoring disable (MON-01, a later slice) | | **Manager** |
   | Accounts, detailed health | Administrator | Administrator |

   - **One account can be Manager, Administrator, or both.** Their session rules are
     the same.
   - **An Operator account has only that role,** because its session rules differ.
     - IAM-01 allows several roles per account and doesn't exclude Operator, so this
       narrows it (the owner's decision).
     - An Operator session and a Manager or Administrator session can't be one session:
       they differ on concurrency (SES-01), timeout (SES-02) and where they can sign in
       (SES-04).
     - Someone who works the line and also manages uses two accounts.
   - The api checks the roles on every call. A test lists every route with its roles,
     so a new route fails the build until its roles are decided.
2. **Accounts:**
   - **Temporary passwords.** An Administrator creates accounts and resets passwords.
     Each gives a random temporary password such as `k7mq-x2pt-9hwz-r4cd`. It is shown
     once, works for 24 h, and must be changed before anything else works.
   - **Disabled, never deleted.** The audit log and the events name accounts by their
     username, which never changes.
   - **Changes take effect at once.** Changing an account's roles, disabling it or
     resetting its password signs it out everywhere.
   - **An Administrator always remains.** The last active Administrator can't be
     disabled or lose the role.
   - **The first Administrator, and recovery, from the server's command line:**
     `python -m centerline_api.auth create-admin` and `temporary-password`. This needs a
     shell on the server. The password can go to a 0600 file instead of the screen, and
     each use is audited.
3. **Passwords:**
   - They are stored as Argon2id hashes, using RFC 9106's second recommended profile
     (64 MiB, 3 passes, 4 lanes).
   - The breached-password list is the NCSC top 100,000 plus the top million of the
     xato ten million list, from SecLists (MIT). Only the 46,825 entries of 12
     characters or more are kept, because shorter passwords fail the length rule anyway.
     The list ships with the api (`auth/breached-passwords.txt.gz` and its NOTICE); the
     builder is `tools/breached-passwords`.
   - A wrong name costs as much time as a wrong password, and the typed name isn't
     recorded, because people sometimes type their password into it.
4. **Sessions** (SES-01…04):
   - **Where they live:** rows in PostgreSQL. The browser holds a random token in a
     cookie that is `HttpOnly; Secure; SameSite=Strict; Path=/api`, and the database
     keeps only its SHA-256.
   - **Operators:**
     - one session for the line, signing in only at a configured workstation
       (`auth.operator_workstations`, by IP);
     - no inactivity limit;
     - the same workstation signing in again replaces its session;
     - another workstation can take a session over once it has had no heartbeat for
       5 min.
   - **Managers and Administrators:**
     - at most 10 sessions;
     - each ends after 15 min without the person's own activity, with a warning from
       13 min. Clicks, keys and changes count; the pages refreshing themselves don't.
   - **The client address** comes from the connection, or from `X-Forwarded-For` only
     when the connection comes from a configured proxy (`auth.trusted_proxies`).
   - Every call that changes something carries an `X-Centerline-CSRF: 1` header, on
     top of the SameSite cookie.
5. **The audit log names who.** Every configuration change, sign-in, failed sign-in,
   sign-out, takeover, account change and acknowledgment records the account. The api
   sets the signed-in username on the request's database connection.
   - **Versions and activations name it too**, since 2026-10-01: register, rules and
     mapping versions in `created_by`, and activations in `created_by` and `cancelled_by`.
     The Rules and Mappings tabs show who activated. Older rows leave these empty, though
     the audit log names who made the ones after sign-in arrived.
   - **Tables** (migration `0004`), against the SDD's data model:
     - The SDD's `user_account`, `role` and `user_role` are one `app_user` table, with
       its roles as an array. A trigger keeps `app_user_login` in step, so each sign-in
       name is unique across usernames, emails and Employee IDs.
     - `session` is `app_session`; `password_history` is `app_user_password`.
     - Sign-in events have no `auth_event` table. They go to the hash-chained
       `audit_log`, so they're tamper-evident like every other change.
6. **Acknowledging a Critical** (ACT-04). `POST /api/v1/events/{id}/acknowledge` is for a
   Manager, on an open Actual event that is Critical.
   - **Once per Critical period.** After a downgrade and a new Critical, the new period
     needs its own acknowledgment. The acknowledgment row records its period.
   - **How monitor-core applies it.** Within 2 s it writes an ACKNOWLEDGED transition
     with who acknowledged and the note, and stops that period's repeats.
   - **While monitor-core is down.** An acknowledgment given then is applied when it
     restarts, and none is applied twice.
7. **The pages:**
   - a sign-in page;
   - the forced password change;
   - the account and a password change in the user menu;
   - the inactivity warning;
   - an Accounts page for Administrators;
   - pages and tabs shown by role, and read-only tabs for roles that can't change them;
   - the Acknowledge box in an event's sheet, for Managers.

## Consequences

- **The database is needed to sign in.** Without it, every endpoint except
  `GET /api/v1/health/live` answers 503. That includes Analytics, which ADR-0012 had
  kept working without the database. Sessions are server-side by design (DD-06).
- **Still to come:**
  - HTTPS through the proxy (Caddy, §12). The cookie is Secure already; browsers accept
    that on `http://localhost` only.
  - Until the proxy exists, keep the api on 127.0.0.1. Once it does, set
    `auth.trusted_proxies`.
- **Not in this slice:**
  - the shift-boundary warning and staged handover (SES-03, O-11, Phase 2);
  - the WebSocket, which will close sessions ended elsewhere at once;
  - monitoring disable and maintenance windows (next slice).
- The sidebar alarm badge, the bell and the Alarms pages still show the prototype's
  sample data.

## Tests

- `services/api/tests/test_access.py`:
  - every route's roles, as decided above;
  - no sign-in, only the public routes answer;
  - the CSRF header is required;
  - each role reaches its own pages only.
- `services/api/tests/test_auth_api.py`:
  - sign-in by any name in any case, and the cookie flags;
  - the lockout;
  - unknown names;
  - temporary passwords: forced change, strength, expiry;
  - password history, and other sessions signed out on a change;
  - inactivity, where background refreshes don't count;
  - the session cap;
  - operator workstations, one operator session, takeover and replacement;
  - signing out, and the audit actor.
- `services/api/tests/test_accounts_api.py`:
  - creating accounts;
  - an Operator has that role alone, and names are unique across kinds;
  - roles or disabling sign out at once;
  - the last Administrator stays;
  - a reset unlocks the account;
  - the username never changes.
- `services/api/tests/test_monitoring_api.py`: a Manager acknowledges once per Critical
  period.
- `services/monitor_core/tests/`:
  - an acknowledgment counts only for its Critical period;
  - one given while monitor-core was down counts after the restart, never twice.
- Checked in headless Edge against a scratch stack:
  - the first Administrator from the command line;
  - sign-in and the forced change;
  - acknowledging a Critical and seeing it applied;
  - creating an Operator and its one-time password;
  - the inactivity warning;
  - signing out;
  - the Operator signing in by Employee ID, with its pages and a read-only event sheet.
