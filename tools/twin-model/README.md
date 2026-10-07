# Twin model: the Volpak SI-360 for the line view

`volpak-si360.blend` is the owner's model of the machine: the collection `SI360_Machine`, from the foil unwinder to
the discharge conveyor, with its own materials. The Digital Centerline page's line view shows it, coloured by
monitor-core's states ([ADR-0034](../../docs/decisions/ADR-0034-line-view-blender-model.md)).

## After changing the model

Save the .blend, then export it to the GLB the page loads. From the repository's root:

```
blender --background tools/twin-model/volpak-si360.blend --python tools/twin-model/export_glb.py
```

Or, in Blender (5.1): open the file, then `export_glb.py` in the Scripting tab, and run it. It writes
`client/src/components/live/twin/volpak-si360.glb`. Rebuild the app to ship it.

## Rules

- **Keep the names the line view uses** (`client/src/components/live/twin/fromModel.ts`):
  - the zones' parts: `Bottom_Sealing_JawF`/`JawR`, `Vertical_Sealing_<n>_JawF`/`JawR`, `Top_Sealing_Bar1_F`/`R`;
  - what moves: any `…_JawF`/`JawR`, `Top_Sealing_Bar<n>_F`/`R`, `Top_Seal_Cooling_F`/`R`, `Suction_Cup_F`/`R`
    (they open towards the front and the rear); `Pouch_00`…, `Finished_Pouch_<n>`, `Foil_Reel_<n>`,
    `Film_Web_Folded`.

  A renamed zone part loses its colour on the model.
- **Model closed:** jaws and bars touching the film or the pouch. The page opens them.
- **The front is −Y in Blender** (the guards, the operator panel) and Z is up. The export turns this into the page's
  y up.
- **Not modelled yet, so drawn by the page:** the sixth vertical seal (name it `Vertical_Sealing_6_…` and the page
  uses it), the dosing nozzles, their manifold, hopper and pressure gauge, and the stack light.
