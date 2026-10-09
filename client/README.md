# Digital Centerline — Phase 1 UI Prototype

A prototype of an industrial production-monitoring application for packaging
lines. **Every page is live**: they call the Centerline api
([services/api](../services/api/README.md)). The api reads what monitor-core judged,
reads the plant's Timebase history, and keeps configuration in the development
PostgreSQL database. The app is the Volpak line: the prototype's sample plant (its
selectors and Overview) is gone ([ADR-0019](../docs/decisions/ADR-0019-alarm-pages-live.md)). Everyone signs in, and each role sees the pages it can use
([ADR-0016](../docs/decisions/ADR-0016-accounts-sign-in-and-roles.md)). monitor-core judges the simulator until gate G0b is met
([ADR-0021](../docs/decisions/ADR-0021-g0b-revised.md)).

```bash
npm install
npm run dev      # http://localhost:5173
```

Other scripts: `npm run build` (type-check + production build), `npm run preview`,
`npm run lint`.

---

## The idea

Every monitored parameter is compared across **three** values, not two:

| Value | Meaning |
|---|---|
| **Target setpoint** | What engineering says the parameter should be — the centerline |
| **HMI setpoint** | What an operator actually dialled into the machine panel |
| **Actual value** | What the sensor is reading right now |

Two independent failures fall out of that, and the UI shows both:

- **Process deviation** — `actual` drifts from `target`; the machine is not holding
  its setpoint.
- **Setpoint drift** — `hmi ≠ target`; someone changed the recipe on the panel and
  it was never reconciled with the centerline. Hopper Pressure on Filler A1
  (target 5.0 bar, HMI 5.5 bar, actual 5.7 bar) is exactly this case, and it is
  the finding a centerline system exists to catch.

> The live Digital Centerline page derives nothing: monitor-core judges every zone and
> stores each change of state, and the page shows it
> ([ADR-0015](../docs/decisions/ADR-0015-live-centerline-page.md)). The next paragraph
> describes the prototype pages that still run on mock data.

Status is **derived, never stored**. `deriveStatus()` in `src/utils/status.ts` is
the only rule, so editing a setpoint in the configuration modal immediately
recolours the table row, its badge, the summary cards and the header alarm count
together — there is no denormalised copy that can drift out of step.

---

## Pages

| Route | Purpose |
|---|---|
| `/centerline` | **Live.** Digital Centerline, the default route: whether monitor-core is judging and why not, the line view (counts, and the machine in 3D with each zone where it sits, [ADR-0033](../docs/decisions/ADR-0033-line-view-3d.md)), every zone's Target / HMI setpoint / Actual with the HMI and Actual checks and their countdowns, the open events and each one's evidence, recently closed events and brief changes |
| `/analytics` | **Analytics & Correlation** — parameter panel with X/Y axis assignment, scatter analysis with regression, trend comparison, 9 summary statistics, raw records table with CSV export |
| `/alarms/active` | **Live.** Every open event, Criticals first, filtered by kind; each opens its evidence sheet, where a Manager acknowledges a Critical |
| `/alarms/history` | **Live.** Every closed event, newest first, filtered by kind, zone and time, paged; Managers and Administrators export it as UTF-8 CSV |
| `/reasons` | **Live.** Every HMI mismatch asks that shift's operator why ([ADR-0025](../docs/decisions/ADR-0025-shifts-and-reasons.md), [ADR-0031](../docs/decisions/ADR-0031-ocap-library-deterministic-path.md)): the operator picks the reason from the Excel OCAP rows offered for the mismatch's parameter and direction, or types it under Other ([ADR-0039](../docs/decisions/ADR-0039-excel-ocaps-and-picked-reasons.md)), and answers the follow-up questions; then the operator reads the picked row, or the OCAP sections matching a typed reason, in full and chooses one, or says none of them apply. Then the operator acknowledges the section, or the Manager's guidance (with its file, and optionally kept as a reusable OCAP); everyone else reads. Grouped as waiting for you, waiting for someone else, closed. For operators the same steps also come as a chat, the **Centerline assistant**, that opens by itself on every page with a short sound ([ADR-0040](../docs/decisions/ADR-0040-reason-assistant-chat.md)) |
| `/ocaps` | **Live.** The OCAP library ([ADR-0031](../docs/decisions/ADR-0031-ocap-library-deterministic-path.md)): every role searches the Active versions (matches highlighted) and reads each version's sections with their pages, history and file. Managers upload a PDF, Word or Excel file as a Draft, check its sections (and which parameters an Excel row is offered for as a reason), add its checked Tagalog version ([ADR-0044](../docs/decisions/ADR-0044-checked-tagalog-ocap.md)) and, where the AI translation is on, see how far it got ([ADR-0045](../docs/decisions/ADR-0045-ai-translates-the-ocap.md)), activate it (keeping or retiring the earlier version) or suspend it |
| `/maintenance` | **Live, Manager and Administrator.** Maintenance windows in force, coming and past; Administrators open them for the line or chosen zones, move their end, end them |
| `/notifications` | **Live, Manager and Administrator.** Every message to Teams and email: how it was routed, each delivery's status and attempts, what was sent; Administrators send TEST messages and re-drive failures ([ADR-0023](../docs/decisions/ADR-0023-notifier.md)) |
| `/health` | **Live, Administrator.** System health ([ADR-0038](../docs/decisions/ADR-0038-system-health-page.md)): a verdict, then every part graded OK, warning or critical (monitor-core and the broker, each area's messages, time to judge, the journal, the notifier and its channels, the outbox, the disk, the backups and their restore check, the off-host copy, the database and audit chain, the malware scanner's signatures, Timebase), each with what to do and a link; refreshed every 15 s |
| `/accounts` | **Live, Administrator.** Every account with its roles and state; create one, change its roles or disable it, issue a temporary password |
| `/configuration` | **Live, Manager and Administrator** (the Rules tab is the Manager's to change, the others the Administrator's). Connections: the MQTT broker and the Timebase historian, with Test and Save. Tags: the parameter register (parameters, zones, Timebase tags with their latest values) and its change history. Mappings: each tag's topic and field. Rules: each zone's target, limits and delays as versions. Notifications: who gets which messages, as versions; the Teams flow and the SMTP relay are on Connections. Reasons: the follow-up questions. Analytics ranges: what each parameter's values must lie within to count in Analytics, as versions |

---

## Architecture

```
src/
  components/
    layout/      AppLayout, AppSidebar, AppHeader, ScopeSelectors, NotificationBell, UserMenu
    centerline/  CenterlineTable, FilterToolbar, ParameterDetailsDrawer,
                 ParameterConfigurationModal, ParameterTrendChart, ThreeValueStrip
    analytics/   AnalyticsParameterPanel, AnalyticsFilterBar, CorrelationScatterChart,
                 SetpointComparisonChart, CorrelationInsightCard, StatisticsCard, RawDataTable
    alarms/      AlarmPanel, AlarmCard, AlarmDetailsDialog, useAlarmActions
    auth/        signing in: AuthFrame, PasswordForm, IdleWarning
    accounts/    the Accounts page's dialogs: account, temporary password
    live/        the live Digital Centerline page: MonitorBanner, LineView, ZoneTable, OpenEvents,
                 EventSheet, RecentActivity, liveModel (names and colours for monitor-core's states)
      twin/      the line view's 3D machine: stations (zone → station), fromModel (the owner's Blender
                 model, volpak-si360.glb, ADR-0034), buildMachine (the machine drawn in code, the fallback),
                 parts (what both share), twinScene (camera, callouts, drawing), MachineTwin (lazy), ZonePanel
    correlation/ the live Analytics page: variable pickers, ECharts scatter and trend, statistics
    setup/       the live Configuration page: MqttConnectionCard, HistorianConnectionCard,
                 TagRegister, ParameterEditor, TagPicker, FormParts
    shared/      PageHeader, StatusBadge, SummaryCard, EmptyState, LoadingSkeleton,
                 ConfirmDialog, SectionCard, DataTableParts
    ui/          shadcn/ui primitives (vendored)
  pages/         one component per route
  data/          mock fixtures + the seeded generator
  services/      mockApi.ts  ← the only seam Phase 2 replaces
                 http.ts, analyticsApi.ts, configApi.ts, monitoringApi.ts, authApi.ts: calls to the Centerline api
  hooks/         useDataTable, useCenterlineFilters, useAnalyticsSelection, …
  context/       ScopeContext, CenterlineContext
  types/         entities, parameters, alarms, analytics
  utils/         status, stats, format, csv, selectors, cn
```

**State** is two React contexts and nothing more:

- `ScopeContext` — factory / line / machine selection, shared by the header
  selectors and every page.
- `CenterlineContext` — parameters, readings, alarms and setpoint history, plus
  the mutations `updateParameterConfig`, `acknowledgeAlarm` and `resolveAlarm`.

Everything else — sorting, pagination, chart toggles, drawer state, axis
assignment — is local `useState` in the component that owns it.

**Two deliberate omissions.** There is no table library: `useDataTable` is ~200
typed lines covering sorting, search, pagination, column visibility and row
selection over a few hundred in-memory rows, and both tables share it. And the
charts use Recharts directly rather than a wrapper, so there is no version
coupling between the chart shell and the chart.

---

## Mock data

`src/data/generate.ts` builds ~300 process samples from a seeded `mulberry32`
PRNG, so values are identical on every reload while timestamps stay relative to
the session and read as live.

The analytics dataset is deliberately **wide** — one row per machine-timestamp
carrying all eight parameters at once — because correlating two parameters
requires them observed at the same instant. That single dataset drives the
scatter chart, the trend comparison, the statistics and the raw table.

Correlations are engineered rather than incidental, so the analytics page has
something true to say. Hopper pressure is the upstream cause; on the default
scope (Filler A1, SKU-4180) the realised coefficients span every interpretation
band:

| Pair | r | Reading |
|---|---|---|
| Hopper pressure → Discharge weight | **0.76** | Strong positive |
| Discharge weight → Product weight | 0.95 | Very strong |
| Hopper level → Discharge weight | 0.55 | Moderate |
| Hopper pressure → Hopper level | 0.49 | Weak |
| Machine speed → Hopper pressure | 0.01 | Negligible |

Two data-integrity details worth knowing, because both would otherwise produce a
convincing but wrong number:

1. **The live reading is held separately from the historical series.** Hopper
   Pressure's showcase value of 5.7 bar sits five standard deviations above its
   own generated series. It is the current reading and the trend chart's final
   point, but it is kept out of `processSamples` so it cannot distort every
   correlation computed over the record.
2. **The insight card warns when the selection mixes regimes.** Pooling SKUs that
   run at different magnitudes (a 500 g doypack beside a 6 g stickpack) inflates
   a correlation on group separation alone. The warning is measured on the
   *paired points that actually enter the correlation*, so a machine that lacks a
   sensor for one of the two parameters never triggers a false alarm.

Coverage: 2 factories · 3 lines · 5 machines · 5 SKUs · 8 parameters ·
~300 samples · 29 centerline readings · 15 alarms (active, acknowledged and
resolved) · 15 setpoint changes · all four statuses visible at once.

---

## Design system

Tokens live in `src/index.css` under Tailwind v4's `@theme`. Components use
semantic names (`bg-surface`, `text-ink-soft`, `border-critical-border`), never
raw palette values.

- **Chrome** navy `#0F172A`; **canvas** `#F1F5F9`; **cards** white; **primary** `#1D4ED8`
- **Status** Normal `#15803D` · Warning `#B45309` · Critical `#B91C1C` · No Data `#475569`,
  each a foreground/surface/border triple, all clearing WCAG AA
- **Chart series** Actual solid blue · HMI dashed orange · Target solid green ·
  tolerance band light red · alarm markers red
- **Type** Inter for UI, JetBrains Mono for measured values; every numeric cell is
  `tabular-nums` and right-aligned so a column of process values scans cleanly
- **Density** 44px table rows and ≥40px touch targets for gloved operation on an
  industrial touchscreen; transitions capped at 150ms and disabled under
  `prefers-reduced-motion`

Status is never carried by colour alone — every badge pairs the hue with a dot, an
icon and a written label.

The **line view** on Digital Centerline sits on the navy chrome. There the status hues are the
`-glow` tokens (`text-normal-glow` …), which read on navy as the others do on white, and the 3D
scene takes its colours from the same tokens at runtime.

---

## Digital Centerline: live

`/centerline` ([ADR-0015](../docs/decisions/ADR-0015-live-centerline-page.md)) shows what
monitor-core ([services/monitor_core](../services/monitor_core/README.md)) judged. It
refreshes every 2 s while the tab is visible:

- **The line view** ([ADR-0033](../docs/decisions/ADR-0033-line-view-3d.md)), under the banner:
  - the counts, with the machine's state: running, stopped, warm-up, or no data;
  - the Volpak filler in 3D: the owner's Blender model (`tools/twin-model/volpak-si360.blend`, exported to
    `twin/volpak-si360.glb`, [ADR-0034](../docs/decisions/ADR-0034-line-view-blender-model.md)), or the machine
    drawn in code when it can't load. Each monitored zone is a part, found by its object name in the model
    (`twin/fromModel.ts`) and coloured by monitor-core's state. A callout per
    station lists its zones with their actual values. A Warning or a Critical gets a ring, and a Critical
    pulses. The stack light shows the line's worst state. The machine moves only while monitor-core reports it
    running, and never with reduced motion;
  - selecting a part, a callout's zone or a station flies to it. The side panel then shows the zone's three
    values, a gauge of its bands, the table's HMI and Actual checks, and its open events;
  - **Full screen** and **Hide 3D** (remembered per browser). three.js loads on its own chunk after the data.
    Without WebGL 2 the panel says so, and the rest of the page works as before.
- **The banner** says whether it's judging, under which versions, or why not:
  - a paused snapshot gate, with the reasons;
  - Actual rules paused while the machine is stopped or warming up;
  - monitor-core not running, or its heartbeat late;
  - the api unreachable.
- **The zone table** shows every monitored zone, grouped by URS parameter:
  - Target, HMI setpoint and Actual;
  - the HMI check, with the countdown to a mismatch event;
  - the Actual check, with any pending change and its countdown.

  A badge's tooltip gives the bands and the rules version it's judged by. A badge
  with an open event opens that event.
- **Open events:** Criticals first, then Warnings, then HMI mismatches.
- **The event sheet** gives the rule and versions an event was judged under, every
  change of state with its inputs, and its notifications. These stay pending until
  the Phase 2 notifier.
- **Recently closed** events and **brief changes** (HMI-05).
- **Monitoring control** ([ADR-0017](../docs/decisions/ADR-0017-monitoring-control.md)):
  - a bar for each maintenance window, amber 30 min and red 5 min before its planned end, red when overdue;
  - a **Switched off** card listing every zone a Manager switched off, with who, when and why;
  - each zone's row shows "Monitoring off", "Maintenance" or "Waiting for fresh values" in place of its checks;
  - Managers get a switch on each row: off with a reason (the zone, or all its parameter's zones), or on again.

  Administrators are warned on any page, 30 and 5 min before a window's planned end and when it goes overdue.

A Manager acknowledges an open Critical from its sheet, with an optional note; monitor-core
stops its repeats within 2 s, and the sheet shows who acknowledged and when. Without monitor-core, the page
says so and the zones show No data. The prototype page (`src/pages/DigitalCenterlinePage.tsx`,
`src/components/centerline/`) is no longer routed but is kept in the tree. The sidebar
badge and the bell count the open events, and the bell lists them.

## Analytics & Correlation: live data

`/analytics` no longer uses mock data. It renders results from the Centerline api
(`services/api`), which reads the plant's Timebase history
([ADR-0008](../docs/decisions/ADR-0008-analytics-on-timebase.md)). Charts use Apache
ECharts 6 and load with the page. Start the api first (see
[services/api/README.md](../services/api/README.md)); `npm run dev` proxies `/api` to it.

The prototype's analytics page (`src/pages/AnalyticsPage.tsx`, `src/components/analytics/`)
is no longer routed but is kept in the tree.

## Storage banner

Every page shows a bar under the header when monitor-core reports the disk 80 % full or more (`StorageBanner`, from the
event counts every page polls): amber with the cleanup's deadline at 90 %, red in protected degraded mode, saying that
uploads, brief-change records and the Analytics query log are paused until it's under 85 %
([ADR-0036](../docs/decisions/ADR-0036-storage-degraded-mode-and-at07.md)). An upload refused then answers
`507 storage-full`.

## Signing in

Everything is behind sign-in ([ADR-0016](../docs/decisions/ADR-0016-accounts-sign-in-and-roles.md)). The username, email or Employee ID work, in
any case.
- **A temporary password** comes from an Administrator, or for the first Administrator
  from the server (see [services/api](../services/api/README.md)). It must be changed first.
- **Managers and Administrators** are signed out after 15 min without activity. A
  dialog asks "Still there?" from 13 min. Clicks and keys count; the pages refreshing
  themselves don't.
- **Operators** sign in only at an operator workstation, one at a time for the line, and
  aren't timed out. A workstation that has been silent for 5 min can be taken over.
  The session ends with its shift ([ADR-0025](../docs/decisions/ADR-0025-shifts-and-reasons.md)): from 5 min before 06:00, 14:00 and 22:00 a bar
  under the header counts down, and at the boundary the page signs out for the next shift's
  operator. Text not yet sent is cleared then, as on every sign-out.

The user menu shows the account and its roles, changes the password and signs out.
Signing out on purpose returns to the Digital Centerline page for the next person.
`src/context/AuthContext.tsx` holds the session. `src/services/http.ts` adds the CSRF
header and signs the page out when the api answers 401. It also gives every POST a new
`Idempotency-Key`, and sends a POST whose answer was lost once more with the same key, so
the api answers it again instead of saving it twice
([ADR-0028](../docs/decisions/ADR-0028-polling-idempotency-g2-acceptance.md)).

## Configuration: live

`/configuration` ([ADR-0011](../docs/decisions/ADR-0011-configuration-page.md),
[ADR-0012](../docs/decisions/ADR-0012-rules-configuration-postgresql.md),
[ADR-0013](../docs/decisions/ADR-0013-tag-mappings.md), [ADR-0023](../docs/decisions/ADR-0023-notifier.md)) has five tabs:

- **Connections:**
  - the MQTT broker: host, port, TLS and CA certificate, account, topic filters, freshness per area;
  - the Timebase historian: URL, dataset, sign-in;
  - notifications: Centerline's address for the links, the Teams flow's URL, the SMTP relay.

  **Test** tries the form without saving anything. For MQTT it listens up to 30 s and
  shows the topics and which register tags it found. **Save** takes
  an optional reason, kept in the change history. Passwords, tokens and certificates
  are write-only: the page shows "Saved · not shown" and never gets them back.
- **Tags (`?tab=tags`):** every URS parameter with its zones and tags, and each tag's
  latest value. **Edit** opens a parameter:
  - set its use (Monitored, Analytics only, Not used yet);
  - add, rename or remove zones;
  - pick each setpoint and actual tag from what Timebase has under the machine;
  - give a reason.

  The api checks every tag, refuses a save if someone else changed the register
  meanwhile, and keeps the change history shown below the table.
- **Mappings (`?tab=mappings`):** where each tag the monitoring engine needs arrives on
  the broker: a topic and a JSON field. **Fill from the broker** listens 10 s, read-only;
  **Import file** reads the probe's `topic-map.json` or a `tag,topic,field` CSV. Each topic
  is chosen from a list: the topics heard on the broker, implied by the subscription, or
  already in use, or a new one typed in. Picking a topic fills an empty field with the
  tag's own name when that was heard on the topic, and the field suggests the names heard
  there. Each
  version can be exported as CSV. It's versioned and activated like the rules, but only a
  mapping with a place for every tag can be activated.
- **Rules (`?tab=rules`):** the monitoring rules, as numbered versions. The tab shows:
  - the version in effect and any scheduled switch;
  - what the version in effect leaves unjudged: zones without limits (the line isn't
    judged) and zones without a target (their HMI setpoint isn't);
  - every version, with **View**, **Edit as new** and **Activate** or **Roll back to**.

  The editor starts from the newest version, or from the Phase 0 proposal for the first
  one. It covers:
  - the stop pause;
  - default delays;
  - Warning and Critical limits per parameter, with delay and zone overrides;
  - each zone's target ([ADR-0027](../docs/decisions/ADR-0027-no-sku.md)). **Fill empty
    targets from current HMI setpoints** is a starting point to check against the
    centerline sheet. A zone without a target has only its actual value judged.

  A blank field shows what it inherits. The api checks the draft as you type and shows
  problems next to the field. Saving needs a reason, and can activate now, at a set
  Manila time, or later.
- **Notifications (`?tab=notifications`):** who gets which messages, as numbered versions
  ([ADR-0023](../docs/decisions/ADR-0023-notifier.md)). Each rule has a name, a channel
  (Teams or email), the kinds of message it sends and its recipients. The first version
  starts from a proposal: Management gets everything, at placeholder recipients the page
  warns about. A version that sends a kind of Critical to nobody can be saved but not
  activated (ACT-03).
- **Reasons (`?tab=workflow`):** the follow-up questions every reason gets, at most two
  ([ADR-0025](../docs/decisions/ADR-0025-shifts-and-reasons.md)). An Administrator changes them with a reason; every change is kept.
- **Analytics ranges (`?tab=ranges`):** the Analytics-valid range of each parameter
  ([ADR-0029](../docs/decisions/ADR-0029-analytics-ranges-and-g4-acceptance.md)). An Administrator downloads the
  template, has it filled in, and uploads it. The file is checked as a whole before it can be saved with a reason, and
  is kept exactly as uploaded. Versions are activated now or later, or rolled back, like the rules.

Managers and Administrators see every tab. A tab the account can't change says so, and
shows no editing buttons: the Rules tab is the Manager's, the others are the Administrator's
(ADR-0016). The api checks the roles anyway.

## Reasons: live

`/reasons` ([ADR-0025](../docs/decisions/ADR-0025-shifts-and-reasons.md)). monitor-core makes a request for every HMI mismatch, one per shift.
- **An operator** sees their shift's requests. For each one they:
  - give the reason, in English or Filipino;
  - answer the follow-up questions;
  - after a Manager's guidance, acknowledge it.

  A new request pops up within 3 s, since the list refreshes every 2 s for an operator.
- **Managers** give the guidance. **Everyone** sees the open requests and those closed in the
  last day.
- **Unsent text** is kept in this browser only (`src/utils/drafts.ts`). It is cleared when the
  request closes or the session ends.
- **The sidebar badge** counts what waits for you. An event's sheet lists its requests with
  every entry.
- **A request still open after 15 min** alerts Management once. One unfinished at the shift's
  end closes as not answered, and the next shift's operator gets a new one.

`src/context/WorkflowContext.tsx` keeps the list; `src/components/workflow/` draws it.

## Notifications: live

`/notifications` ([ADR-0023](../docs/decisions/ADR-0023-notifier.md)), for Managers and
Administrators, lists every message the notifier delivers or was meant to: newest first,
filtered to those on their way, failed, not sent (no rule sends them) or TEST. Each row
shows its deliveries to Teams and email with their status. A message opens in a sheet:
- how it was routed, and the rules that matched;
- each delivery: status, attempts, the next try, the last error, every attempt with what
  the provider answered, and **What was sent**;
- **Re-drive**, for an Administrator, on a delivery that failed for 24 h: it asks why.

**Send a TEST message** (Administrator) sends "TEST - NO PRODUCTION EVENT" to one recipient
you name, outside the routing. To see real messages without Teams or a relay, run
`tools/notify-sink` and point Configuration → Connections at it.

`npm run dev` proxies `/api` to `http://127.0.0.1:8000`. To point the UI at another api,
set `CENTERLINE_API`, e.g. `CENTERLINE_API=http://127.0.0.1:8001 npx vite --port 5176`.

The prototype's configuration page (`src/pages/ConfigurationPage.tsx`) is no longer routed
but is kept in the tree.

## The prototype's files

No page reads mock data any more. The prototype's own pages and their components
(`src/pages/OverviewPage.tsx`, `ActiveAlarmsPage.tsx`, `AlarmHistoryPage.tsx`,
`DigitalCenterlinePage.tsx`, `AnalyticsPage.tsx`, `ConfigurationPage.tsx`,
`src/components/alarms/`, `centerline/`, `analytics/`, `layout/ScopeSelectors.tsx`,
`src/context/CenterlineContext.tsx`, `ScopeContext.tsx`, `src/services/mockApi.ts`, `src/data/`)
are unrouted but kept: the project has no version control, so they're deleted only when the
owner says so ([ADR-0019](../docs/decisions/ADR-0019-alarm-pages-live.md)). Still to come: the WebSocket, notification delivery (Phase 2) and
the deployment configuration.
