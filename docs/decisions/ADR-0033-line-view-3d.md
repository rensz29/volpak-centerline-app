# ADR-0033: The line view: the Volpak filler in 3D on the Digital Centerline page

- **Status:** Accepted. Decisions 2 and 7 amended by [ADR-0034](ADR-0034-line-view-blender-model.md) (2026-10-07): the
  line view shows the owner's Blender model of the machine; the machine drawn in code is its fallback
- **Date:** 2026-10-06
- **Decider:** Szyrelle (system owner), on 2026-10-06: "enhance the UI … make it a 3D show the actual machine, something
  like a modern dashboard for industrial"
- **Amends:** [ADR-0015](ADR-0015-live-centerline-page.md) decision 4 (the counts move into the line view; the page
  shows the machine in 3D above the zone table)
- **URS:** CLI-01 (Edge and Chrome, 1920×1080), PER-01 (dashboard in 3 s), A-10 (no internet on the plant LAN)

## Context

- The Digital Centerline page showed four count cards above the zone table. Nothing showed where on the machine a zone
  is, so an operator new to the line has to know that "Rear top 1" is a jaw of the top seal.
- The owner asked for a modern industrial dashboard showing the actual machine in 3D.
- The machine's general arrangement drawing (Volpak SI-360 F3 / CA-995/3 / MIF-786) shows its layout:
  - the film unwinder;
  - the forming section, with its six vertical seal bars;
  - the filling section, with the pouch chain;
  - the discharge conveyor;
  - two electrical boxes on top.

  There is no 3D model file of the machine.
- ADR-0015 holds: the browser names and colours monitor-core's states and judges nothing.

## Decision

1. **A line view under the banner** (which stays first, ADR-0015). It's a navy panel, in the colours of the sidebar and
   header, holding:
   - **the counts:** the machine's state (running, stopped, warm-up or no data, as monitor-core reports it), zones,
     HMI mismatches, Warnings and Criticals;
   - **the machine in 3D;**
   - **a side panel:**
     - with a zone selected: its target, HMI setpoint and actual; a gauge of its Warning and Critical bands with the
       three values on it; the zone table's own HMI and Actual checks, with their countdowns; buttons to its open
       events;
     - with nothing selected: each station's state, any zone not on the model, and what the colours mean.

   Below it the page is unchanged: the monitoring control cards, the zone table, the open events and recent activity.
   **The zone table stays the full record,** and the view for keyboard and screen-reader users.
2. **The model is drawn in code with three.js, after the drawing.** It is schematic, not to scale, and says so. The
   parts are:
   - the unwinder, with its reels and rollers;
   - both sections, with their teal guards, A-frame legs and trusses;
   - the electrical boxes and the operator panel;
   - the film band, with the printed pouches;
   - the pouch chain, the dosing manifold and the riser;
   - the conveyor;
   - a stack light.
3. **Each monitored zone is a part of the model,** found by its channel (`client/src/components/live/twin/stations.ts`):

   | Zones | Parts |
   |---|---|
   | P03 Front, Rear bottom | the bottom seal's front and rear jaws |
   | P02 Vertical 1…6 | the six vertical seal stations, in the film's direction, each a pair of jaws |
   | P06 Nozzle 1…3 | the three dosing nozzles' collars, in the pouches' direction |
   | P09 Dosing pressure | the gauge on the dosing manifold |
   | P04 Front, Rear top 1 | the top seal's front and rear jaws |

   A zone the register gains later has no part until it's drawn. The side panel lists it under "Monitored, not on the
   model yet", and the table shows it as usual.
4. **Colours come from monitor-core's states only,** read the same way as the zone table's checks:
   - Normal is green, a Warning or an HMI mismatch amber, a Critical red;
   - no data, switched off, under maintenance and waiting are grey.

   A part never carries its state by colour alone:
   - every station has a callout card listing its zones, each with an icon, the state's name for screen readers, and
     the actual value;
   - a Warning or a Critical also gets a ring, drawn through whatever stands in front of it;
   - a Critical's ring and glow pulse.

   The stack light shows the line's worst state while monitor-core judges, and nothing otherwise.
5. **The model moves only while monitor-core reports the machine running.** The film indexes, the jaws close, the
   nozzles dip, the reels turn. With `prefers-reduced-motion` nothing moves or pulses.
6. **Interaction:**
   - drag to turn, right-drag to move, scroll to zoom;
   - selecting a part, a zone in a callout or a station flies the camera to that part; clearing the selection, or
     **Reset view**, flies back;
   - **Full screen**, for a control-room display;
   - **Hide 3D**, remembered per browser, leaves only the counts.

   Opening an event leaves full screen first, because the event sheet opens over the page.
7. **Cost:**
   - three.js (about 145 kB gzipped) is its own chunk. It loads after the page's data is on screen, never with the rest
     of the app, and it's bundled, not fetched from a CDN (A-10).
   - The scene draws only when something changed, or at 30 frames a second while the machine moves or a Critical
     pulses. It stops drawing when off screen or in a hidden tab.
   - The static parts are merged into a few meshes.
8. **Without WebGL 2, or if the model's chunk fails to load,** the panel says the 3D view can't be shown here. The
   counts, the side panel and the rest of the page work as before. An error boundary keeps a failure in the model from
   taking the page down.

## Consequences

- An operator sees where each zone is on the machine, and which part is in trouble, before reading the table.
- The page gains one dependency, `three`, used by the line view only.
- **Open item O-26:** the placement in decision 3 follows the drawing and the zones' names, not a check on the machine:
  - that "Front" and "Rear" are the two jaws of one station;
  - the order of Vertical 1…6 and of Nozzle 1…3.

  Szyrelle, with maintenance, confirms them at the machine. Moving a zone is an edit to `PLACE` and the model, not to
  the register.
- The control-room PC's browser needs WebGL 2, which current Edge and Chrome have unless a policy or a missing GPU
  driver turns it off. Without it, decision 8 applies.

## Tests

Checked in headless Edge on Windows against a preview of the line view with fixture data. The preview and its files
were removed afterwards. The states checked:
- running, with a Warning, a Critical, an HMI setpoint off target and a zone switched off;
- stopped;
- monitor-core not running;
- a zone selected from its callout, and a part selected on the model;
- full screen;
- a narrow window, with the side panel under the model.

`npm run build` puts three.js in its own chunk, which the page doesn't preload.
