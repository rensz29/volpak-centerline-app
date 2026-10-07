import { Mesh, type Material, type Object3D } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

import modelUrl from './volpak-si360.glb?url'

/**
 * The owner's model of the machine (ADR-0034, tools/twin-model/volpak-si360.blend), bundled with the app
 * and served from the same origin, never a CDN (A-10). It's fetched once per page; each scene gets its own
 * copy with its own materials, because the scene frees what it was given when it closes.
 *
 * Resolves to null if the file can't be loaded or read: the line view then draws the machine in code (ADR-0033).
 */
let loading: Promise<Object3D | null> | undefined

export async function loadModel(): Promise<(() => Object3D) | null> {
  loading ??= new GLTFLoader()
    .loadAsync(modelUrl)
    .then((gltf) => gltf.scene)
    .catch(() => null)
  const scene = await loading
  return scene && (() => copyOf(scene))
}

/** The geometry stays shared (the scene copies what it changes); the materials are the copy's own. */
function copyOf(scene: Object3D): Object3D {
  const copy = scene.clone(true)
  const materials = new Map<Material, Material>()
  copy.traverse((object) => {
    if (!(object instanceof Mesh)) return
    const own = object.material as Material
    if (!materials.has(own)) materials.set(own, own.clone())
    object.material = materials.get(own)!
  })
  return copy
}
