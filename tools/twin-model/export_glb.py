"""Exports the owner's Volpak SI-360 model to the line view's GLB (ADR-0034).

Run it in Blender (5.1) with tools/twin-model/volpak-si360.blend, from the repository's root:

    blender --background tools/twin-model/volpak-si360.blend --python tools/twin-model/export_glb.py

or open the file, then this script in the Scripting tab, and run it. It writes
client/src/components/live/twin/volpak-si360.glb: every object in the collection SI360_Machine and its
children, with their names and materials, y up. The line view finds its parts by these names
(fromModel.ts), so renaming a jaw, a pouch or a gripper means changing it there too.
"""

import os

import bpy

COLLECTION = "SI360_Machine"
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if not os.path.isdir(os.path.join(ROOT, "client")):
    # Run from the Scripting tab, __file__ can be the text block's name: fall back to the .blend's folder
    ROOT = os.path.abspath(os.path.join(bpy.path.abspath("//"), "..", ".."))
OUT = os.path.join(ROOT, "client", "src", "components", "live", "twin", "volpak-si360.glb")

machine = bpy.data.collections.get(COLLECTION)
if machine is None:
    raise SystemExit(f"No collection {COLLECTION!r} in this file")

scene = next(s for s in bpy.data.scenes if machine.name in {c.name for c in s.collection.children_recursive})
if bpy.context.window is not None:
    bpy.context.window.scene = scene
layer = scene.view_layers[0]

for obj in scene.objects:
    obj.select_set(False, view_layer=layer)
objects = [o for o in machine.all_objects if o.type == "MESH"]
for obj in objects:
    obj.select_set(True, view_layer=layer)

with bpy.context.temp_override(scene=scene, view_layer=layer):
    bpy.ops.export_scene.gltf(
        filepath=OUT,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_materials="EXPORT",
    )

print(f"Exported {len(objects)} objects of {COLLECTION} to {OUT} ({os.path.getsize(OUT)} bytes)")
