# ADR-0020: The services' database role (Phase 1)

- **Status:** Accepted
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner), with the Phase 1 go-ahead; the design follows the SDD
- **Related:** [ADR-0012](ADR-0012-rules-configuration-postgresql.md) (PostgreSQL), [ADR-0014](ADR-0014-monitor-core.md),
  [ADR-0016](ADR-0016-accounts-sign-in-and-roles.md)
- **URS:** DAT-01, RET-02; SDD §9 ("How immutability is enforced"); guide §16 checklist

## Context

- **What the SDD asks:** "the application's database role may only INSERT and SELECT on
  evidence tables, and triggers reject UPDATE and DELETE. A separate purge role deletes only
  records past retention and not under legal hold."
- **Until now** the api and monitor-core connected as the database's owner, a superuser in
  the development container.
- **The risk:** a bug or an intruder in either service could switch every trigger off
  (`session_replication_role`), rewrite or delete evidence, truncate tables, or change the
  schema. The triggers alone didn't hold against their own owner.

## Decision

1. **The role.** `centerline_app` (the SDD's `app_rw`) is created by migration `0006`.
   - It can log in, isn't a superuser, can't create roles or databases, and owns nothing.
     So it can't switch triggers off, alter or drop tables, or truncate.
   - **Evidence and versions** it can only add and read: the audit log, register, rules and
     mapping versions, events, transitions, brief changes, acknowledgments, the outbox,
     password history, and monitoring switches.
   - **It may also update** the rows that are operational by design:
     - event state, timers, pauses and the heartbeat;
     - accounts and maintenance windows;
     - activations, which their triggers let it cancel only.
   - **It may also delete** unused SKUs, ended sessions, and an account's sign-in names,
     which their trigger rewrites.
   - The append-only triggers stay as a second line, and stop even the owner.
2. **Its password** is in `config/secrets/postgres-app-password` (0600), never in a
   migration. `python -m centerline_common.roles` sets it, making the file first if needed.
   The api does the same at start.
3. **Who connects how:**
   - The api connects as `centerline_app`. It runs the migrations as the owner, then sets
     the role's password, then connects. It does this at start, and again if the database
     comes up after it: `migrate_database` in its config, by default the development
     database's owner.
   - monitor-core connects as `centerline_app` and never migrates.
   - The accounts command line (`python -m centerline_api.auth`) migrates as the owner first, like the
     api, then writes the account as `centerline_app`. *Fixed 2026-10-01: until then it migrated as
     the services' role, which can't, so it failed.*
4. **The purge role waits for retention** (RET-01/02, with the Phase 5 data governance).
   It needs the retention policies and legal hold first. The append-only triggers must also
   let that role, and only it, delete records past retention.
5. **The test suites run as `centerline_app`,** so every path they cover proves its grants
   suffice. `test_roles.py` lists each table's privileges: a new table fails until its
   grants are decided. The tests that check the triggers themselves, or tamper on purpose,
   use the owner.

## Consequences

- **Neither service can** rewrite or delete evidence, switch the triggers off, or change the
  schema, even with a bug or an intruder.
- **Adding a table:** each new table needs its grants in its own migration and a line in
  `test_roles.py`.
- **In production:** the owner's password is needed only by whatever applies the
  migrations. The services get only `postgres-app-password`, so the api's owner
  connection (`migrate_database`) becomes a deployment step.
- The Docker `postgres` container's own superuser is still the owner in development.

## Tests

- `services/api/tests/test_roles.py`:
  - every table's privileges for the role;
  - the role's attributes, and that it owns nothing;
  - it can't update or delete evidence, truncate, switch the triggers off, drop or create
    tables, record a migration, or create a role;
  - a fresh database is migrated by the owner, then served as the role.
- Every api and monitor-core test now runs as `centerline_app`.
