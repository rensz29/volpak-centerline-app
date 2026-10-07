import {
  Box3,
  BoxGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  Float32BufferAttribute,
  Group,
  Mesh,
  MeshStandardMaterial,
  RepeatWrapping,
  TorusGeometry,
  Vector3,
  type Material,
  type Object3D,
  type Texture,
} from 'three'

import { bake, cyclePhase, CYCLE_S, printTexture, stackLight, zoneKit, type Callout, type Machine } from './parts'
import type { StationId } from './stations'

/**
 * The owner's model of the Volpak SI-360 as the line view's machine (ADR-0034). It's modelled in Blender
 * (tools/twin-model/volpak-si360.blend, exported by export_glb.py) and keeps its own materials. The line
 * view finds what it colours and moves by the objects' names there:
 * - each zone's part: ZONE_PARTS;
 * - the jaws, bars and cups that close from the front (…F) and the rear (…R): JAW;
 * - the pouches in the grippers (Pouch_00…), those on the conveyor (Finished_Pouch_…), the film reels
 *   (Foil_Reel_…) and the folded film (Film_Web_Folded).
 *
 * What the model lacks is drawn here, in its materials: a sixth vertical seal (the fifth one, copied one
 * station on), the three dosing nozzles with their manifold, hopper and pressure gauge, and the stack light.
 * The model's coordinates are Blender's, y up after the export: metres, the guarded front at +z.
 */

/** Each zone's part, by object name. O-26: Szyrelle confirms the placement at the machine. */
const ZONE_PARTS: Record<string, string> = {
  Bottom_Sealing_JawF: 'P03.FRONT',
  Bottom_Sealing_JawR: 'P03.REAR',
  Top_Sealing_Bar1_F: 'P04.FRONT',
  Top_Sealing_Bar1_R: 'P04.REAR',
  ...Object.fromEntries(
    [1, 2, 3, 4, 5, 6].flatMap((n) => [
      [`Vertical_Sealing_${n}_JawF`, `P02.V${n}`],
      [`Vertical_Sealing_${n}_JawR`, `P02.V${n}`],
    ]),
  ),
}

/** Parts that close on the film or a pouch from the front (F) or the rear (R) */
const JAW = /^(?:Bottom_Sealing_Jaw|Vertical_Sealing_\d+_Jaw|Cooling_Jaw_Jaw|Top_Sealing_Bar\d_|Top_Seal_Cooling_|Suction_Cup_)([FR])$/
/** How far a jaw opens from where it's modelled, closed */
const OPEN = 0.05
const POUCH = /^Pouch_(\d+)$/
const FINISHED = /^Finished_Pouch_\d+$/
const REEL = /^Foil_Reel_\d+$/
/** The gripper slots the three nozzles dose at: the model's pouches are empty before the first and full after the last */
const FIRST_DOSE_SLOT = 3
const NOZZLES = 3

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function machineFromModel(model: Object3D, glow: Texture, ring: Texture): Machine {
  const root = new Group()
  const statics = new Group()
  const moving = new Group()
  root.add(statics, moving)
  const { parts, pickables, adopt } = zoneKit(glow, ring)

  // Every part in the model's coordinates, its transform applied to its own copy of the geometry (the
  // loader keeps the original for the next scene), then the machine centred on the origin along x and z
  model.updateMatrixWorld(true)
  const meshes: Mesh[] = []
  model.traverse((object) => {
    if (object instanceof Mesh) meshes.push(object)
  })
  const box = new Box3()
  for (const mesh of meshes) {
    mesh.geometry = mesh.geometry.clone().applyMatrix4(mesh.matrixWorld)
    mesh.geometry.computeBoundingBox()
    box.union(mesh.geometry.boundingBox!)
  }
  const shift = new Vector3(-(box.min.x + box.max.x) / 2, 0, -(box.min.z + box.max.z) / 2)
  for (const mesh of meshes) {
    mesh.removeFromParent()
    mesh.position.set(0, 0, 0)
    mesh.quaternion.identity()
    mesh.scale.set(1, 1, 1)
    mesh.geometry.translate(shift.x, 0, shift.z)
    mesh.geometry.computeBoundingBox()
  }
  const byName = new Map(meshes.map((mesh) => [mesh.name, mesh]))
  const bounds = (mesh: Mesh | undefined) => (mesh ? mesh.geometry.boundingBox!.clone().translate(mesh.position) : undefined)
  const centre = (mesh: Mesh) => bounds(mesh)!.getCenter(new Vector3())
  /** Moves a part's origin to its centre, so it can move or turn about it */
  const pivot = (mesh: Mesh) => {
    const c = centre(mesh)
    mesh.geometry.translate(-c.x, -c.y, -c.z)
    mesh.geometry.computeBoundingBox()
    mesh.position.copy(c)
    return mesh
  }

  // The model's materials: glass drawn from both sides without hiding what's behind it, the operator panel's screen lit
  const materials = new Set(meshes.map((mesh) => mesh.material as Material))
  for (const material of materials) {
    if (material.transparent) {
      material.depthWrite = false
      material.side = DoubleSide
    }
    if (material.name === 'HMI_Screen' && material instanceof MeshStandardMaterial) {
      material.emissive.set(0x1e40af)
      material.emissiveIntensity = 0.8
    }
  }
  const named = (name: string, fallback: number) =>
    ([...materials].find((m) => m.name === name) as MeshStandardMaterial | undefined) ?? new MeshStandardMaterial({ color: fallback, metalness: 0.8, roughness: 0.35 })
  const stainless = named('Stainless', 0x9ea8b4)
  const housing = named('Elec_Box', 0x4b5563)

  // --- What moves --------------------------------------------------------------------------
  const jaws: { mesh: Mesh; side: 1 | -1; rest: number }[] = []
  const pouches: { mesh: Mesh; slot: number; thickness: number }[] = []
  const finished: Mesh[] = []
  const reels: { mesh: Mesh; radius: number }[] = []
  let film: Mesh | undefined
  for (const mesh of meshes) {
    const jaw = JAW.exec(mesh.name)
    const pouch = POUCH.exec(mesh.name)
    if (jaw) {
      moving.add(pivot(mesh))
      jaws.push({ mesh, side: jaw[1] === 'F' ? 1 : -1, rest: mesh.position.z })
    } else if (pouch) {
      moving.add(pivot(mesh))
      pouches.push({ mesh, slot: Number(pouch[1]), thickness: bounds(mesh)!.getSize(new Vector3()).z })
    } else if (FINISHED.test(mesh.name)) {
      moving.add(pivot(mesh))
      finished.push(mesh)
    } else if (REEL.test(mesh.name)) {
      moving.add(pivot(mesh))
      const size = bounds(mesh)!.getSize(new Vector3())
      reels.push({ mesh, radius: size.x / 2 })
      // A cross on the reel's chuck, or its turning wouldn't show
      for (const [w, h] of [[size.x * 0.75, 0.014], [0.014, size.x * 0.75]] as const) {
        const bar = new Mesh(new BoxGeometry(w, h, 0.01), stainless)
        bar.position.z = size.z / 2 + 0.006
        mesh.add(bar)
      }
    } else if (mesh.name === 'Film_Web_Folded') {
      film = mesh
      moving.add(mesh)
    } else {
      statics.add(mesh)
    }
  }
  pouches.sort((a, b) => a.slot - b.slot)

  // --- The sixth vertical seal: the model has five --------------------------------------------
  const vertical = (n: number, part: string) => byName.get(`Vertical_Sealing_${n}_${part}`)
  const [fourth, fifth] = [vertical(4, 'JawF'), vertical(5, 'JawF')]
  if (!vertical(6, 'JawF') && fourth && fifth) {
    const step = fifth.position.x - fourth.position.x
    for (const part of ['Actuator', 'Arm', 'JawF', 'JawR']) {
      const source = vertical(5, part)
      if (!source) continue
      const copy = new Mesh(source.geometry.clone(), source.material)
      copy.name = `Vertical_Sealing_6_${part}`
      copy.position.copy(source.position)
      copy.position.x += step
      const jaw = JAW.exec(copy.name)
      if (jaw) {
        moving.add(copy)
        jaws.push({ mesh: copy, side: jaw[1] === 'F' ? 1 : -1, rest: copy.position.z })
      } else {
        statics.add(copy)
      }
      byName.set(copy.name, copy)
    }
  }

  // --- The zones' parts ---------------------------------------------------------------------
  const zoneMeshes = new Map<string, Mesh[]>()
  for (const [name, channel] of Object.entries(ZONE_PARTS)) {
    const mesh = byName.get(name)
    if (!mesh) continue
    const size = bounds(mesh)!.getSize(new Vector3())
    const longest = Math.max(size.x, size.y)
    adopt(channel, mesh, clamp(longest * 0.6, 0.14, 0.3), clamp(longest * 0.45, 0.14, 0.24))
    zoneMeshes.set(channel.split('.')[0]!, [...(zoneMeshes.get(channel.split('.')[0]!) ?? []), mesh])
  }

  // --- Dosing: three nozzles over the gripper slots where the model's pouches fill -------------
  const pitch = pouches.length > 1 ? pouches[1]!.mesh.position.x - pouches[0]!.mesh.position.x : 0.13
  const x0 = pouches[0]?.mesh.position.x ?? 0
  const pouchTop = pouches[0] ? bounds(pouches[0].mesh)!.max.y : 1.28
  const deck = bounds(byName.get('M2_Top_Deck'))
  const deckBottom = deck?.min.y ?? pouchTop + 0.3
  const deckTop = deck?.max.y ?? deckBottom + 0.03
  const manifoldY = deckBottom - 0.07
  const tipY = pouchTop + 0.025
  // Beside each gripper's body, over its pouch
  const nozzleX = Array.from({ length: NOZZLES }, (_, i) => x0 + (FIRST_DOSE_SLOT + i) * pitch + 0.03)
  const first = nozzleX[0]!
  const last = nozzleX[NOZZLES - 1]!
  const middle = (first + last) / 2
  const rod = (radius: number, length: number, x: number, y: number, z: number, axis: 'x' | 'y' | 'z', parent: Object3D, material: Material = stainless) => {
    const mesh = new Mesh(new CylinderGeometry(radius, radius, length, 20), material)
    if (axis === 'x') mesh.rotation.z = Math.PI / 2
    if (axis === 'z') mesh.rotation.x = Math.PI / 2
    mesh.position.set(x, y, z)
    parent.add(mesh)
    return mesh
  }
  rod(0.02, last - first + 0.14, middle, manifoldY, 0, 'x', statics)
  const nozzles = nozzleX.map((x, i) => {
    const nozzle = new Group()
    nozzle.position.x = x
    const length = manifoldY - tipY
    rod(0.011, length, 0, tipY + length / 2, 0, 'y', nozzle)
    const tip = new Mesh(new ConeGeometry(0.011, 0.025, 16), stainless)
    tip.rotation.x = Math.PI
    tip.position.y = tipY - 0.012
    nozzle.add(tip)
    const collar = new Mesh(new CylinderGeometry(0.022, 0.022, 0.035, 24))
    collar.position.y = tipY + length * 0.62
    nozzle.add(collar)
    adopt(`P06.N${i + 1}`, collar, 0.16, 0.14)
    moving.add(nozzle)
    return nozzle
  })
  // The hopper on the deck, feeding the manifold through it
  rod(0.016, deckTop + 0.04 - manifoldY, middle, (manifoldY + deckTop + 0.04) / 2, 0, 'y', statics)
  const hopper = new Mesh(new CylinderGeometry(0.11, 0.03, 0.09, 32), stainless)
  hopper.position.set(middle, deckTop + 0.085, 0)
  statics.add(hopper)
  rod(0.11, 0.16, middle, deckTop + 0.21, 0, 'y', statics)
  rod(0.116, 0.014, middle, deckTop + 0.297, 0, 'y', statics, housing)
  // The pressure gauge at the manifold's end (P09)
  const gaugeX = last + 0.14
  rod(0.009, 0.08, last + 0.09, manifoldY, 0, 'x', statics)
  rod(0.035, 0.02, gaugeX, manifoldY, 0.03, 'z', statics, new MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.5 }))
  const bezel = new Mesh(new TorusGeometry(0.035, 0.008, 10, 32))
  bezel.position.set(gaugeX, manifoldY, 0.042)
  moving.add(bezel)
  adopt('P09.MAIN', bezel, 0.18, 0.16)

  // --- The stack light on the sealing module's electrical box ------------------------------------
  const box2 = bounds(byName.get('M2_Elec_Box'))
  const lamps = box2
    ? stackLight(statics, moving, box2.max.x - 0.08, box2.max.y, box2.max.z - 0.08, 0.09, glow, stainless, housing)
    : stackLight(statics, moving, box.max.x + shift.x - 0.6, deckTop, 0, 0.09, glow, stainless, housing)

  // --- The folded film: the printed pouches, their seals meeting the vertical jaws at each dwell --
  const v1 = vertical(1, 'JawF')
  const v2 = vertical(2, 'JawF')
  const filmPitch = v1 && v2 ? v2.position.x - v1.position.x : 0.105
  const print = printTexture()
  print.wrapS = RepeatWrapping
  if (film) {
    const extent = bounds(film)!
    const position = film.geometry.getAttribute('position')
    const uv: number[] = []
    for (let i = 0; i < position.count; i++) {
      uv.push((position.getX(i) - (v1?.position.x ?? extent.min.x)) / filmPitch, (position.getY(i) - extent.min.y) / (extent.max.y - extent.min.y))
    }
    film.geometry.setAttribute('uv', new Float32BufferAttribute(uv, 2))
    film.material = new MeshStandardMaterial({ map: print, roughness: 0.4, side: DoubleSide })
  }
  const filmMaterial = (pouches[0]?.mesh.material as MeshStandardMaterial | undefined) ?? new MeshStandardMaterial({ color: 0xeef2f6 })
  const filledMaterial = filmMaterial.clone()
  filledMaterial.color.multiply(new Color(0xfff0d2))
  const thicknesses = pouches.map((p) => p.thickness)
  const emptyT = Math.min(...thicknesses)
  const fullT = Math.max(...thicknesses)
  const pouchY = pouches[0]?.mesh.position.y ?? 1.2
  const belt = bounds(byName.get('Conveyor_Belt'))
  const finishedX = finished.map((mesh) => mesh.position.x)

  // --- Callouts: each station's card above the machine, or below it in front -------------------
  const top = Math.max(bounds(byName.get('M1_Elec_Box'))?.max.y ?? deckTop, box2?.max.y ?? deckTop)
  const front = (bounds(byName.get('M1_Door1_Glass'))?.max.z ?? 0.45) + 0.55
  const middleOf = (list: Mesh[] | undefined, fallback: Vector3) => {
    if (!list?.length) return fallback
    const all = list.reduce((b, mesh) => b.union(bounds(mesh)!), new Box3())
    return all.getCenter(new Vector3()).setY(all.max.y)
  }
  const anywhere = new Vector3(0, deckTop, 0)
  const bottomPin = middleOf(zoneMeshes.get('P03'), anywhere)
  const verticalPin = middleOf(zoneMeshes.get('P02'), anywhere)
  const topPin = middleOf(zoneMeshes.get('P04'), anywhere)
  const callouts: Record<StationId, Callout> = {
    bottom: { pin: bottomPin, card: new Vector3(bottomPin.x - 0.5, 0.45, front), below: true },
    vertical: { pin: verticalPin, card: new Vector3(verticalPin.x, top + 0.55, 0.2), below: false },
    dosing: { pin: new Vector3(middle, manifoldY, 0.03), card: new Vector3(middle, top + 0.55, 0.2), below: false },
    top: { pin: topPin, card: new Vector3(topPin.x + 0.35, 0.45, front), below: true },
  }

  bake(statics)

  const animate = (seconds: number) => {
    const { moved, close } = cyclePhase(seconds)
    for (const { mesh, side, rest } of jaws) mesh.position.z = rest + side * OPEN * (1 - close)
    for (const nozzle of nozzles) nozzle.position.y = -0.06 * close
    print.offset.x = -moved
    const travelled = (seconds * filmPitch) / CYCLE_S
    for (const { mesh, radius } of reels) mesh.rotation.z = -travelled / radius

    // The pouches index one gripper on per cycle; the last drops to the chute and a new one takes the first gripper
    const slots = pouches.length
    pouches.forEach(({ mesh, thickness }, k) => {
      const slot = (k + moved) % slots
      const leaving = Math.max(0, slot - (slots - 1))
      mesh.position.x = x0 + slot * pitch
      mesh.position.y = pouchY - leaving * 0.3
      const doses = clamp(Math.floor(slot + 1e-6) - FIRST_DOSE_SLOT + 1, 0, NOZZLES)
      mesh.scale.z = (emptyT + ((fullT - emptyT) * doses) / NOZZLES) / thickness
      mesh.material = doses ? filledMaterial : filmMaterial
    })
    if (belt) {
      const length = belt.max.x - belt.min.x - 0.12
      finished.forEach((mesh, i) => {
        mesh.position.x = belt.min.x + 0.06 + ((finishedX[i]! - belt.min.x - 0.06 + travelled * 3) % length)
      })
    }
  }
  animate(0)

  return { root, parts, pickables, callouts, lamps, focusDistance: 2.6, animate }
}
