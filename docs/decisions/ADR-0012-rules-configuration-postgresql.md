# ADR-0012: Monitoring rules on the Configuration page, kept in PostgreSQL

- **Status:** Accepted. Amended by [ADR-0016](ADR-0016-accounts-sign-in-and-roles.md): signing in needs the
  database, so without it Analytics answers 503 too; the Rules tab is the Manager's to change. Amended by
  [ADR-0027](ADR-0027-no-sku.md) (2026-10-05): no SKU, so targets are set per zone and the line is judged once every zone has its limits
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner)
- **Confirms:** assumptions A-01 and A-02
- **Amends:** [ADR-0011](ADR-0011-configuration-page.md) (where the register history and the audit log live) and
  [ADR-0007](ADR-0007-parameter-register.md) decision 1 (the register file becomes an export)
- **Related:** [ADR-0001](ADR-0001-sku-changeover.md), [ADR-0002](ADR-0002-default-delays.md),
  [ADR-0010](ADR-0010-pause-actual-rules-when-stopped.md)
- **URS:** HMI-01…05, ACT-01…03, OPC-07, OPC-08, DAT-01

## Context

- The monitoring engine can't judge anything without targets, Warning and
  Critical limits and delays. The URS and SDD want them configured in the app,
  versioned, activated now or at a set time, and rolled back by reactivating an
  earlier version (OPC-07, SDD §9).
- Phase 0 left starting values: the delays in ADR-0002 (proposed) and limits
  proposed from 28 days of history. There are no targets and no SKU list: the
  machine doesn't publish a SKU yet (O-15).
- ADR-0011 kept everything in files "until the Phase 1 database". Scheduled
  activation, rollback and immutable history (DAT-01) are awkward on files, and
  events will be pinned to a rules version.
- The owner accepted the plan on 2026-09-30: the Rules tab next, rules per SKU
  and zone with line defaults, PostgreSQL now, and the Phase 0 values loaded as
  a proposal.

## Decision

1. **Rule model (confirms A-01 and A-02).**
   - A rules version holds line-wide settings and rule rows.
   - A row applies to one SKU or every SKU, and to one zone or every zone of a
     parameter. A field a row leaves empty is inherited. The most specific row
     that sets a field wins: this SKU and zone > this SKU > every SKU, this zone >
     every SKU and zone > line defaults.
   - The fields are:
     - the target;
     - Warning and Critical limits, as distances from the raw HMI setpoint (A-02);
     - the HMI mismatch, Warning, Critical and Recovery delays. The Warning
       delay also covers Critical → Warning (ACT-02), and Recovery defaults to
       15 s;
     - the short-change mode (default Lightweight record, HMI-05);
     - Warning notifications on or off. Criticals always notify (ACT-03).
   - Line-wide settings are the stop pause from ADR-0010 and the defaults for
     the delays and handling. Targets and limits have no line default.
   - Critical must lie at least as far out as Warning once the layers combine.
   - The HMI comparison rule stays in the register (ADR-0007) until O-17 is
     decided.
2. **A SKU is ready** when every monitored zone has a target and all four limits.
   monitor-core treats a SKU that isn't ready as unconfigured: the OPC-08 pause
   (ADR-0001). The page shows readiness per SKU.
3. **Versions are immutable.**
   - A save creates Rules v*n* with its rows in one transaction.
   - The version stores a SHA-256 of its content, which the api checks on every
     read. A mismatch shows as "changed outside Centerline".
   - A save must name the newest version the editor started from, and is
     refused (409) if another was saved meanwhile.
   - Every save needs a reason.
4. **Activation is separate** and runs now or at a set Manila time.
   - The version in effect is the latest activation whose time has come.
     Activating an older version again is a rollback. A scheduled activation
     can be cancelled until it takes effect.
   - Activation checks the version the page saw as active (409 if it changed)
     and needs a reason. Open events keep the version they started under (OPC-07).
5. **SKUs are reference data.** A SKU has a code, exactly as the machine will
   publish it, and a name. It can be renamed, and removed only while no saved
   version uses it.
6. **PostgreSQL now**, in the SDD's image (PostgreSQL 17 with pgvector):
   - Development: `deploy/dev/compose.yaml`, on `127.0.0.1:55432`; 5432 is
     taken on this PC. The password is generated into
     `config/secrets/postgres-password`.
   - Schema: `db/migrations/*.sql`, applied in order and recorded with their
     hashes. An edited migration is refused.
   - Tables: `audit_log`, `sku`, `register_version`, `config_version`,
     `sku_parameter_rule` and `config_activation`.
   - Triggers refuse UPDATE, DELETE and TRUNCATE on configuration history. The
     only exceptions are SKU names and cancelling a scheduled activation.
   - The audit log is hash-chained (`audit_log_verify()`); the health endpoint
     reports whether the chain is intact.
   - IDs are UUIDv7 (`centerline_common.db.uuid7`).
7. **What moved and what stayed:**

   | Item | Now |
   |---|---|
   | Register | `register_version` rows. On first start the file becomes the first version. After each save the file is rewritten for the Phase 0 tools and git. A file edited by hand is copied to `history/` before being overwritten, and the page says its edits aren't in use |
   | Change history | `audit_log`. `history/audit.jsonl` was imported once, keeping its times, and left in place |
   | Connections | Still `connections.json` and `secrets/`. They are deployment settings the tools and, later, monitor-core read at start-up. Their changes are audited in the database |

8. **Without the database**, the api still starts. Analytics reads the register
   file, the configuration endpoints answer 503, and the first request that
   reaches the database finishes start-up.
9. **Starting values.** `db/seed/rules-proposal.json` holds the ADR-0002 delays,
   the proposed limits and the ADR-0010 stop pause, with no targets. The Rules
   tab offers it as the first version's starting point. Nothing is saved or
   activated until someone does it on the page. **Activating it is how the
   owner accepts the delays**; the limits still wait for process engineering.

## Consequences

- monitor-core (Phase 1) has a defined source: `active_config_version()` plus
  `centerline_common.rules.resolve()` for each zone and SKU.
- **Nothing can be monitored until SKUs and targets exist.** Process
  engineering has to provide the SKU list and each SKU's target per zone (their
  centerline sheets). The page can fill empty targets from the current HMI
  setpoints as a starting point, and warns that the HMI shows what is dialled
  in, not what should be.
- Docker Desktop must be running for the Configuration page to save.
  Analytics works without it.
- The development database has one owner role. The SDD's separate `app_rw`
  and `purge` roles come with the Phase 1 migrations, as do login and the
  Manager role for rules (SDD §10). Until then the api stays on 127.0.0.1.
- Register rollback isn't on the page yet. Every version is kept in
  `register_version`, and each change's before and after is in the audit log.

## Tests

- `services/api/tests/test_rules_unit.py`: layering, validation naming the row
  and field, readiness, and the content hash.
- `test_db.py`: migrations run once and an edited one is refused; history is
  append-only; the audit chain catches an edit; only a scheduled activation can
  be cancelled.
- `test_rules_api.py`:
  - a first version from the proposal;
  - activation, rollback, scheduling and cancelling;
  - stale and invalid saves;
  - SKU readiness;
  - a tampered version reads as not intact;
  - running without the database;
  - the one-time history import.
