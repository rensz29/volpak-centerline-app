# ADR-0011: Configuration page for the connections and the tag register

- **Status:** Accepted. Amended by [ADR-0012](ADR-0012-rules-configuration-postgresql.md): the register's versions and the
  audit log now live in PostgreSQL, and the register file is their export. Connections stay in files
- **Date:** 2026-09-29
- **Decider:** Szyrelle (system owner)
- **Related:** [ADR-0006](ADR-0006-mqtt-acquisition.md) (MQTT, controls M1–M7),
  [ADR-0007](ADR-0007-parameter-register.md) (register), [ADR-0008](ADR-0008-analytics-on-timebase.md) (Analytics)
- **URS:** OPC-01 (what is acquired), OPC-07 (config changes don't re-judge events), SEC-02 (connection controls)

## Context

- Broker details (O-14) are still to come from the UNS team. Until now they had
  to be typed into `tools/mqtt-probe/config.json`, and the historian into
  `services/api/config.json`.
- The register was edited by hand. A mistyped tag only showed up when a query
  failed, because Timebase refuses a whole request when one tag is unknown.
- The SDD keeps configuration in the database, versioned and behind login.
  Neither exists before Phase 1.
- The owner wants a page to set up the MQTT connection and the historian, and to
  add tags.

## Decision

1. **One page, two tabs, at `/configuration`:**
   - **Connections:** the MQTT broker and the Timebase historian, each with
     Test and Save.
   - **Tags:** the register, one parameter at a time: its use (status), its
     zones, and each zone's setpoint and actual tag. Tags are picked from the
     ones Timebase has under the machine namespace, and each shows its latest value.
2. **Files until the Phase 1 database**, all in the api's `config_dir` (`config/`):

   | File | Holds | In git |
   |---|---|---|
   | `parameter-register.json` | The register; every save bumps its version | Yes |
   | `connections.json` | Broker and historian settings, without secrets | No |
   | `secrets/` | Broker password and CA certificate, historian token or password. Folder 0700, files 0600 | No |
   | `history/register-<version>.json` | The register as it was before each save | No |
   | `history/audit.jsonl` | Every save: when, what, before and after, and why | No |

3. **Secrets are write-only.** The page sends a password, token or certificate
   once. The api writes it to `secrets/` and afterwards reports only whether one
   is set. An empty field keeps the saved secret, and Remove deletes it. Secrets
   never appear in `connections.json`, api responses, the audit log or logs.
4. **Test never saves anything.** It uses what's on the form (a secret that
   isn't retyped comes from the saved one) and keeps it in memory.
   - **Historian:** lists the datasets, checks the dataset, counts the tags
     under the namespace and measures the server's clock offset.
   - **MQTT:** connects, subscribes and listens 3–30 s (default 10) with
     publishing disabled in code (M6). It reports the topics, where each
     register tag was found (topic and field), SKU-like fields, and warnings
     (TLS off, nothing received, no SKU field).
5. **Register saves are checked, versioned and audited:**
   - The page sends the version it loaded. If the register changed meanwhile,
     the save is refused (409) and nothing is written.
   - Every tag must exist in Timebase under the machine namespace, and a tag
     can belong to only one zone.
   - Zone IDs are 1–16 capital letters, digits or `_`. IDs and names are
     unique within a parameter.
   - **Monitored** needs a setpoint and an actual tag in every zone; **Analytics
     only** needs an actual in every zone; **Not used yet** needs nothing.
   - A reason is required.
   - The new version is `<Manila date>.<n>`, e.g. `2026-09-29.3`. A number is
     never reused, even after a file is copied back from `history/`.
   - The old file goes to `history/`, the file is replaced atomically, and
     Analytics uses the new register at once.
6. **A saved historian applies at once:** Analytics uses it from its next
   query. The saved broker waits for monitor-core (Phase 1). Until then the
   probe can use it: `python mqtt_probe.py ../../config/connections.json`.
7. **No login yet, so the api stays on 127.0.0.1.** Anyone who can reach the
   api can change these settings, and the page says so. With login (Phase 1)
   these endpoints become **Administrator-only** (assumed, like mapping import,
   O-13), and the audit log records the user.

## Consequences

- Broker details can be entered and tested as soon as the UNS team sends them
  (Phase 0 task 0.6), with no file editing.
- A mistyped or duplicate tag can't reach the register. It's refused, with the
  reason next to the field.
- **Rollback is by hand for now:** copy a file from `history/` over
  `parameter-register.json` and restart the api. The next save gets a new version.
- **The audit log is append-only by convention**, not enforced. It isn't the
  immutable audit trail of DAT-01; that comes with the database.
- **Phase 1 replaces the files** and keeps the endpoints and the page:
  - the register seeds `parameter` and `parameter_zone`, and later changes
    become `config_version` / `tag_mapping_version`, with scheduled activation
    and rollback;
  - secrets become files mounted into the containers (§12);
  - `audit.jsonl` is imported into the audit table.
- **Once monitor-core runs**, a register change must follow OPC-07: open events
  keep the version they were raised under.

## Tests

`services/api/tests/test_config_api.py`:
- secrets are stored 0600 and never returned;
- Test persists nothing;
- tag browsing and latest values;
- a zone added on the page reaches Analytics;
- stale versions are refused;
- invalid edits are refused, naming the field;
- a copied-back register never reuses a version;
- the MQTT Test against a local Mosquitto and the simulator.
