# ADR-0017: Switching monitoring off, and maintenance windows (Phase 1)

- **Status:** Accepted
- **Date:** 2026-09-30
- **Decider:** Szyrelle (system owner)
- **Related:** [ADR-0014](ADR-0014-monitor-core.md) (monitor-core), [ADR-0015](ADR-0015-live-centerline-page.md) (the live page),
  [ADR-0016](ADR-0016-accounts-sign-in-and-roles.md) (roles: switching off is the Manager's, O-13)
- **URS:** MON-01, MNT-01, MNT-02, OPC-03, OPC-05; SDD §5 (pause gate, monitoring disabled)

## Context

- **MON-01:** switching monitoring off closes the active event as "Monitoring disabled",
  cancels the timers and workflows that depend on it, keeps the initial notifications,
  and sends no recovery notice.
- **MNT-01:** manual and scheduled Administrator maintenance, with a scope and a
  reason, 30- and 5-minute warnings, and an overdue status.
- **MNT-02:** after an interruption, judging resumes on fresh data, with timers from zero.
- **The SDD** puts a maintenance window in the pause gate: judging and timers stop, and
  open events stay open.
- **What neither said:**
  - what can be switched off;
  - whether switching off ends by itself;
  - what the warnings and "overdue" mean;
  - what a window can cover.

  The owner decided these on 2026-09-30.

## Decision

1. **Switching off (MON-01), by a Manager:**
   - A Manager switches off one zone, or all of a parameter's zones at once. A reason is
     required.
   - The zone's open events close as `CLOSED_MONITORING_DISABLED`, with no recovery
     notice. Their delays and repeats stop, and the notices already sent stay on record.
   - The zone isn't judged until a **Manager switches it on again**. It doesn't come back
     by itself.
   - The live page lists every switched-off zone, with who, when and why, so none is
     forgotten.
   - Switched on again, a zone is judged only on values that arrived after that moment,
     and its delays start from zero (MNT-02).
   - Every switch is a row in `monitoring_switch`, append-only; a zone's latest row is its
     state.
2. **Maintenance windows (MNT-01), by an Administrator:**
   - **Scope:** the whole line, or chosen zones.
   - **When:** now or at a set time, always with a reason and a planned end. It can be
     extended, ended early, or cancelled before it starts.
   - **Chosen zones:** delays and repeats stop, and open events stay open. The rest of the
     line is judged as usual.
   - **The whole line:** the pause gate closes with "Maintenance: …" as the reason.
   - **After a window** judging resumes only on data that arrived after its end, with
     delays and repeats from zero (MNT-02).
   - **Warnings** come 30 and 5 minutes **before the planned end**. The live page's
     maintenance bar turns amber, then red, and Administrators get a toast on any page. They
     can end the window or move its end.
   - **Past the planned end** the window **stays in force as overdue**, because the work may
     not be done. monitor-core alerts Management once (a `system` notification delivered
     by the Phase 2 notifier), and it stays overdue until an Administrator ends it.
   - `maintenance_window` rows can only have their planned end moved, and be ended once.
     Every change is in the audit log.
3. **monitor-core** reads the switches and the open windows every 2 s, and once at start
   before judging anything. It works out from its own clock when a scheduled window starts.
   The heartbeat gives each zone's control state: off, maintenance, or waiting for fresh
   values.
4. **The api:**
   - `GET /api/v1/monitoring/control` and `GET /api/v1/maintenance`: every role;
   - `POST /api/v1/monitoring/switch`: Manager;
   - `POST /api/v1/maintenance`, `/maintenance/{id}/extend`, `/maintenance/{id}/end`:
     Administrator.

   The live view includes the control view, so it shows even while monitor-core is down.
5. **The pages:**
   - The live page has the maintenance bar, the "Switched off" card, the control state in
     each zone's row, and, for Managers, a switch on each row.
   - A **Maintenance** page (Setup) lists the windows in force, coming and past. Managers
     see it; Administrators open, move and end windows.

## Consequences

- **The operator workflow comes later.** MON-01 also cancels "dependent workflows", which
  arrive in Phase 2 and will need to follow the same switch.
- **Up to 2 s to take effect.** A switch or a window takes effect within 2 s. A delay that
  ends inside those 2 s can still open an event, which then stays open under maintenance.
- **Warnings are in-app only for now.** The 30- and 5-minute warnings are on the page and
  in toasts. Delivering them, and the overdue alert, to Teams or email is the Phase 2
  notifier's job.

## Tests

- `services/monitor_core/tests/test_monitor_control.py`:
  - switching off closes events with no recovery notice and stops judging the zone;
  - on again, the zone is judged on fresh values with delays from zero;
  - a zone window holds its events and repeats; it goes overdue once, and afterwards the
    repeats restart from zero;
  - a line window pauses the gate and resumes only on data from after it;
  - a scheduled window takes effect at its planned start.
- `test_monitor_store.py`: the latest switch counts, and the event closes in the database.
- `services/api/tests/test_control_api.py`:
  - a Manager switches zones off with a reason, and on again;
  - an Administrator opens, extends, ends and cancels windows, with validation;
  - an overdue window stays in force, and the history is guarded.
- `test_access.py` checks each new route's roles.
- Checked in headless Edge:
  - switching off with a Critical open, and on again;
  - a zone window with its warning;
  - the Maintenance page;
  - ending a window;
  - an overdue window and its alert;
  - a line window and the resume.
