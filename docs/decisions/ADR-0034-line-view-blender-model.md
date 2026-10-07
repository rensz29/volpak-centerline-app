# ADR-0034: The line view shows the owner's Blender model of the machine

- **Status:** Accepted (revised the same day; see Context)
- **Date:** 2026-10-07
- **Decider:** Szyrelle (system owner). First: "integrate the Blender design of the machine into the Digital Centerline
  page". Then, shown that the page loaded a generated copy and not that design, the owner chose "Whole machine": the
  model replaces the code-drawn machine, keeping its materials, with the zones on its named parts. For the parts it
  lacks, the owner chose "Code draws them".
- **Amends:** [ADR-0033](ADR-0033-line-view-3d.md) decisions 2 and 7
- **URS:** A-10 (no internet on the plant LAN), PER-01 (dashboard in 3 s)

## Context

- ADR-0033 draws the whole machine in code (`buildMachine.ts`), schematic and not to scale.
- The owner modelled the machine in Blender after its general arrangement drawing (SI-360 F3 / CA-995/3 / MIF-786):
  - the collection `SI360_Machine`: 328 objects in seven collections, from the foil unwinder to the discharge
    conveyor;
  - its own materials: stainless, aluminium profile, orange seal heaters, blue grippers, teal guard glass;
  - named parts: `Vertical_Sealing_1_JawF`, `Bottom_Sealing_JawR`, `Top_Sealing_Bar1_F`, `Pouch_00` …
- **The first version of this ADR did not use that design.** A script (`build_body.py`) rebuilt a simplified "body"
  from the code's own layout and palette, and saved it into the owner's file as a second scene, `Twin_Body`. The page
  loaded that copy, so it looked the same as before and the owner saw no change.

## Decision

1. **The owner's model is the line view's machine, whole,** with its own materials. The code adds only the zones'
   colours, rings and outlines, the callouts, the motion, and what the model lacks (decision 5).
2. **The source is the .blend file in the repository:** `tools/twin-model/volpak-si360.blend`.
   - It is a copy of the owner's file with the generated `Twin_Body` scene removed.
   - `tools/twin-model/export_glb.py` exports the collection `SI360_Machine` to
     `client/src/components/live/twin/volpak-si360.glb`, keeping the objects' names, y up.
   - A change to the machine is made in that file, then exported. `build_body.py` and its GLB are retired.
3. **Each zone's part is found by its object name** (`fromModel.ts`; the names are the contract):

   | Zones | Objects |
   |---|---|
   | P03 Front, Rear bottom | `Bottom_Sealing_JawF`, `Bottom_Sealing_JawR` |
   | P02 Vertical 1…5 | `Vertical_Sealing_1_JawF`/`JawR` … `Vertical_Sealing_5_JawF`/`JawR` |
   | P04 Front, Rear top 1 | `Top_Sealing_Bar1_F`, `Top_Sealing_Bar1_R` |

   An object renamed in Blender loses its zone's colour on the model. The zone stays in its station's callout, the
   side panel and the table.
4. **The motion stays in code, on the model's own parts:**
   - every jaw, bar and suction cup named …F or …R opens 5 cm from where it's modelled and closes;
   - the pouches move on one gripper per cycle, and fill over the three dosing slots;
   - the finished pouches ride the conveyor;
   - the foil reels turn, with a cross added to each chuck so the turning shows;
   - the folded film is printed with pouches whose seals meet the vertical jaws at each dwell.
5. **What the model lacks is drawn in code, in the model's materials:**
   - **Vertical 6:** a copy of the fifth station, one station on. A `Vertical_Sealing_6_JawF`/`JawR` modelled later is
     used instead.
   - **The three dosing nozzles (P06):** over gripper slots 3–5, where the model's pouches go from empty to full; with
     their manifold under the deck and a hopper on it.
   - **The pressure gauge (P09)** at the manifold's end.
   - **The stack light** on the sealing module's electrical box.
6. **Loading (amends ADR-0033 decision 7):**
   - The GLB (about 1.1 MB, with the roof and the detail added after the drawings and the roof photo; about 19,000 triangles) is bundled with the app, served from the same origin (A-10), and fetched once per page by
     the model's chunk, after three.js.
   - Each scene gets its own copy, so hiding and showing the 3D view doesn't fetch it again.
7. **Fallback:** if the file can't be loaded or read, the line view draws the machine in code, as ADR-0033 does, with
   the same zones.
8. **The camera frames whichever machine is shown.** Flying to a selected part comes in low, through the front guards,
   because the stations sit under the deck.

## Consequences

- The owner changes the machine's look and detail in Blender without touching the line view's logic. Moving or
  renaming a part the line view uses means changing `fromModel.ts` too.
- The code-drawn machine (`buildMachine.ts`) stays as the fallback, so its layout and the model's can drift apart.
  Once the model has run at the plant, the fallback can shrink to the zones alone.
- **O-26 stays open,** now about the model:
  - that "Front" and "Rear" are the jaws named F and R;
  - the order of the vertical seals;
  - where V6, the nozzles and the gauge really are, since the code places them.
- `build_body.py` was never committed. A copy is kept outside git, in `config/history/`.

## Tests

Checked in headless Edge on Windows against a temporary preview of the line view with sample data. The preview was
removed afterwards. The checks:
- the model loads with its own materials;
- Vertical 4 at Warning, Nozzle 2 with its HMI setpoint off target, Rear top 1 at Critical, and Vertical 6 switched
  off, each on its part;
- flying to a vertical seal and to a nozzle.

`npm run build` bundles `volpak-si360.glb` as an asset of the model's chunk.
