# ADR-0013: Tag mappings on the Configuration page

- **Status:** Accepted. Amended by [ADR-0022](ADR-0022-placeholder-sku.md) (2026-10-01): a version may name a
  placeholder SKU instead of the SKU field, judged on actual values only. Amended again by [ADR-0027](ADR-0027-no-sku.md) (2026-10-05):
  a mapping names only tags, with no SKU field or placeholder
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner)
- **Implements:** [ADR-0006](ADR-0006-mqtt-acquisition.md) decision 3 (tag mapping), on the storage and
  versioning of [ADR-0012](ADR-0012-rules-configuration-postgresql.md)
- **URS:** OPC-06, OPC-07, OPC-08

## Context

- monitor-core has to know where each register tag arrives on the broker: a
  topic, and a field of its JSON message. ADR-0006 planned a versioned mapping
  imported from the probe's `topic-map.json`.
- The first contact with the plant broker (2026-09-30) showed:
  - one topic per machine area (`…/Volpak/Filler/SPC`, `…/Dosing_Parameters`);
  - one JSON message per topic, carrying every field, about every 1.7 s;
  - field names equal to the Timebase tag names, and all 30 needed tags present;
  - no SKU field yet (O-15).
- The owner asked for the mapping on the Configuration page, like the rules.

## Decision

1. **A Mappings tab**, between Tags and Rules.
   - A mapping places each tag monitor-core needs: every monitored zone's
     setpoint and actual, plus the machine-state tags (`Machine_Run` for the
     stop pause, `Machine_Speed`).
   - Each place is a topic and a JSON field; an empty field means the whole
     payload.
   - The mapping also holds the SKU field's place, once the edge team adds it.
2. **Three ways to fill it**, all without saving:
   - listen to the saved broker for 10 s, read-only, using the same check as
     the MQTT Test;
   - import the probe's `topic-map.json`;
   - import a `tag,topic,field` CSV, with the SKU on a row called `SKU`.

   Each version can also be exported as that CSV. A topic is chosen from a list:
   the topics heard on the broker, those the connection's filters imply for the
   register's machine areas, and those already in the mapping. A topic that
   isn't listed can be typed.
3. **Checks:**
   - each tag once, and only tags the register needs;
   - a real topic (no `+` or `#`), and no two tags in the same place;
   - a warning for topics the connection's filters wouldn't receive, and while
     there's no SKU field.
4. **Versions and activation as for the rules** (ADR-0012):
   - immutable versions with a SHA-256 checked on every read;
   - a save needs a reason and the newest version number (409 if stale);
   - activation now or at a set Manila time, rollback, and cancelling a
     scheduled activation;
   - the activation logic is shared with the rules (`config/versioning.py`).
5. **Only a complete mapping can be activated.** Every tag monitor-core needs
   must have a place, because the engine can't judge a zone it can't read. If
   the register later needs a tag the mapping in effect lacks, the tab says so
   and monitoring pauses until a new mapping is activated.
6. **Tables** (migration `0002`):
   - `mapping_version`, `tag_mapping` and `mapping_activation`, append-only by
     trigger;
   - `active_mapping_version()` returns the version in effect.

   The SDD calls these `opc_mapping_version` / `opc_mapping`, and ADR-0006
   calls them `tag_mapping_version`.

## Consequences

- monitor-core has its input defined: the connection (ADR-0011), the mapping in
  effect (this ADR) and the rules in effect (ADR-0012).
- The SKU field goes in a new mapping version once the edge team publishes it.
  Until then the mapping can be complete without it, but the real machine stays
  paused (OPC-08).
- Like the rules, mapping changes have no login yet; they become
  Administrator-only (assumed, O-13) with Phase 1.

## Tests

- `services/api/tests/test_mapping_unit.py`: required tags, filter matching,
  validation naming the row and field, topic map and CSV round trip.
- `test_db.py`: mappings are append-only, refuse wildcards and shared places;
  the activation guard.
- `test_mapping_api.py`: import, save, refusal to activate an incomplete
  mapping, activation, CSV, a stale save, check without saving, and listening
  to a local Mosquitto with the simulator (all 30 tags and the SKU field found).
