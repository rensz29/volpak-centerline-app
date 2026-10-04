# ADR-0019: The Alarms pages on live events; the prototype's plant hierarchy removed (Phase 1)

- **Status:** Accepted
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner)
- **Related:** [ADR-0015](ADR-0015-live-centerline-page.md) (the live page and its events),
  [ADR-0016](ADR-0016-accounts-sign-in-and-roles.md) (roles, acknowledgment)
- **URS:** ACT-04, EXP-01; guide §15 (prototype gaps: scope, alarm lifecycle)

## Context

- **Still on sample data:** after the live Digital Centerline page (ADR-0015), the
  prototype's Active Alarms and Alarm History pages, the sidebar badge and the header bell
  still ran on its sample data. They showed alarms that don't exist, next to the real
  events.
- **The plant header and Overview:** the header had factory, line and machine selectors,
  and an Overview page of a made-up plant (2 factories, 3 lines, 5 machines).
- **The scope:** the SDD covers one line. Guide §15 says to drop the factory and machine
  hierarchy from the live model.
- The owner decided to remove them on 2026-09-30.

## Decision

1. **Active Alarms** (`/alarms/active`) lists every open event from monitor-core.
   - Criticals come first, then Warnings, then HMI mismatches.
   - Each row gives how long the event has been open, its values at opening, and whether
     it's acknowledged.
   - Filter buttons show a count for each kind.
   - A row opens the event's evidence sheet, where a Manager acknowledges a Critical
     (ADR-0016). `?event=<id>` opens one directly.
2. **Alarm History** (`/alarms/history`) lists the closed events, newest first, with how
   each ended.
   - **Filters:** kind (an Actual that *reached* Critical counts even if it went back to
     Warning), zone, and a Manila time range.
   - **Paging:** a cursor ("Show older").
   - **Export:** Managers and Administrators export the matching events (up to 10,000) as
     UTF-8 CSV with times in Manila with their offset (EXP-01). Every export is audited.
3. **The sidebar badge and the bell** count the open events (`GET /api/v1/events/counts`,
   every 10 s). The bell lists them, Criticals first, and links each to its sheet.
4. **Removed from the app:**
   - the header's plant selectors;
   - the Overview page (`/overview` now opens the Digital Centerline page);
   - the "refresh mock data" button.

   The app is the Volpak line. The prototype's files stay in `client/src` unrouted, like
   its earlier pages: the project has no version control, so files aren't deleted without
   the owner's say. The mock data providers aren't mounted any more.
5. **The api:**
   - `GET /api/v1/events` takes filters: `open`, `kind`, `severity`, `reached`, `channel`,
     `since`, `until`, `before` and `limit`. It returns `next` for the following page.
   - `GET /api/v1/events/counts` serves every role.
   - `GET /api/v1/events/export.csv` is for Managers and Administrators.

## Consequences

- No page shows the prototype's sample data any more, apart from those unrouted files.
- **No line id in the schema yet** (a correction: the option the owner chose said the
  database keeps one). The guide suggests adding one when a second line joins. That, and
  bringing back a line selector, is work for that day.
- **Operators** see both pages, but only Managers and Administrators export (EXP-01).
  PDF and Excel exports (also EXP-01) come with the export jobs (§11, later).

## Tests

- `services/api/tests/test_monitoring_api.py` (the history test):
  - the history pages through with the cursor without repeats;
  - it filters by kind, severity, reached Critical and zone;
  - the counts;
  - the CSV export (header, Manila offsets, audited).
- `test_access.py` checks the new routes' roles.
- Checked in headless Edge:
  - no plant selectors and no Overview;
  - the live badge and the bell;
  - an event opened from the bell into Active Alarms;
  - the Critical filter;
  - Alarm History and its CSV;
  - the `/overview` redirect.
