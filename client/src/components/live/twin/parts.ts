import {
  AdditiveBlending,
  BufferGeometry,
  CanvasTexture,
  CylinderGeometry,
  EdgesGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshStandardMaterial,
  Sprite,
  SpriteMaterial,
  SRGBColorSpace,
  type Material,
  type Object3D,
  type Texture,
  type Vector3,
} from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'

import type { StationId } from './stations'

/**
 * What both of the line view's machines share (ADR-0033, ADR-0034): the owner's model from Blender
 * (fromModel.ts) and the one drawn in code when the model can't load (buildMachine.ts).
 */

export interface ZonePart {
  channel: string
  material: MeshStandardMaterial
  halo: SpriteMaterial
  /** The glows around its meshes, with their resting size in userData.size */
  glows: Sprite[]
  /** A ring around the part, shown for a Warning or a Critical: it reads on any background */
  ring: SpriteMaterial
  rings: Sprite[]
  outlines: LineSegments[]
}

export interface Callout {
  /** The point on the machine the callout's leader starts from */
  pin: Vector3
  /** Where the callout card hangs */
  card: Vector3
  /** The card hangs below its point rather than above it */
  below: boolean
}

export interface Lamp {
  material: MeshStandardMaterial
  halo: SpriteMaterial
}

export interface Machine {
  root: Group
  parts: Map<string, ZonePart>
  /** The zones' meshes, for the pointer */
  pickables: Mesh[]
  callouts: Record<StationId, Callout>
  /** The stack light on the filling section's electrical box */
  lamps: { red: Lamp; amber: Lamp; green: Lamp }
  /** How far from a selected part the camera stops: the parts' size sets it */
  focusDistance: number
  /** Puts every moving part where it is after this many seconds of running */
  animate(seconds: number): void
}

/** One pouch per cycle, indexed: the film and the pouches move one pitch, then dwell while the jaws close. */
export const CYCLE_S = 1.5

export const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/** Where the machine is in its cycle: pitches moved so far (in the first 30 % of each cycle), and how closed the jaws are (0–1). */
export function cyclePhase(seconds: number): { moved: number; close: number } {
  const cycles = seconds / CYCLE_S
  const cycle = Math.floor(cycles)
  const phase = cycles - cycle
  return { moved: cycle + smooth(0, 0.3, phase), close: smooth(0.36, 0.46, phase) * (1 - smooth(0.84, 0.94, phase)) }
}

export function canvasTexture(width: number, height: number, draw: (g: CanvasRenderingContext2D) => void): CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const g = canvas.getContext('2d')
  if (g) draw(g)
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  return texture
}

/** A soft white disc, tinted per use: the glow around a heated jaw or a lit lamp. */
export function glowTexture(): CanvasTexture {
  return canvasTexture(64, 64, (g) => {
    const r = g.createRadialGradient(32, 32, 0, 32, 32, 32)
    r.addColorStop(0, 'rgba(255,255,255,1)')
    r.addColorStop(0.35, 'rgba(255,255,255,0.55)')
    r.addColorStop(1, 'rgba(255,255,255,0)')
    g.fillStyle = r
    g.fillRect(0, 0, 64, 64)
  })
}

/** A white circle's outline, tinted per use: the alarm ring around a zone's part. */
export function ringTexture(): CanvasTexture {
  return canvasTexture(128, 128, (g) => {
    g.strokeStyle = 'rgba(255,255,255,1)'
    g.lineWidth = 9
    g.beginPath()
    g.arc(64, 64, 52, 0, Math.PI * 2)
    g.stroke()
    g.strokeStyle = 'rgba(255,255,255,0.35)'
    g.lineWidth = 4
    g.beginPath()
    g.arc(64, 64, 40, 0, Math.PI * 2)
    g.stroke()
  })
}

/** One pouch's width of printed film: side seals at the edges, a generic label, the gusset fold. */
export function printTexture(): CanvasTexture {
  return canvasTexture(128, 160, (g) => {
    g.fillStyle = '#eef2f6'
    g.fillRect(0, 0, 128, 160)
    g.fillStyle = '#f3e3bf'
    g.fillRect(24, 30, 80, 92)
    g.fillStyle = '#c2410c'
    g.fillRect(24, 52, 80, 14)
    g.fillStyle = '#d6dde6'
    g.fillRect(0, 136, 128, 3)
    g.fillStyle = '#c4ced9'
    g.fillRect(0, 0, 5, 160)
    g.fillRect(123, 0, 5, 160)
  })
}

/**
 * Merges the static parts by material: a handful of draw calls instead of hundreds. Parts that share a
 * material but not their attributes (texture coordinates on some, not others) keep only those they share.
 */
export function bake(group: Group) {
  group.updateMatrixWorld(true)
  const byMaterial = new Map<Material, BufferGeometry[]>()
  const meshes: Mesh[] = []
  group.traverse((object) => {
    if (!(object instanceof Mesh)) return
    const material = object.material as Material
    byMaterial.set(material, [...(byMaterial.get(material) ?? []), object.geometry.clone().applyMatrix4(object.matrixWorld)])
    meshes.push(object)
  })
  meshes.forEach((mesh) => mesh.geometry.dispose())
  group.clear()
  for (const [material, list] of byMaterial) {
    const shared = Object.keys(list[0]!.attributes).filter((name) => list.every((g) => name in g.attributes))
    let geometries = list.map((g) => {
      for (const name of Object.keys(g.attributes)) if (!shared.includes(name)) g.deleteAttribute(name)
      return g
    })
    if (geometries.some((g) => g.index) && geometries.some((g) => !g.index)) {
      geometries = geometries.map((g) => {
        if (!g.index) return g
        const flat = g.toNonIndexed()
        g.dispose()
        return flat
      })
    }
    const merged = mergeGeometries(geometries)
    geometries.forEach((g) => g.dispose())
    if (merged) group.add(new Mesh(merged, material))
  }
}

/** The zones' parts: each coloured by its state, outlined when selected, with a glow and an alarm ring. */
export function zoneKit(glow: Texture, ring: Texture) {
  const parts = new Map<string, ZonePart>()
  const pickables: Mesh[] = []
  const outlineMaterial = new LineBasicMaterial({ color: 0xffffff, transparent: true, depthTest: false })

  /** Makes a mesh a zone's part: its material becomes the zone's, and it gains the outline, glow and ring. */
  const adopt = (channel: string, mesh: Mesh, glowSize: number, ringSize = Math.max(0.32, glowSize * 0.75)): Mesh => {
    let part = parts.get(channel)
    if (!part) {
      part = {
        channel,
        material: new MeshStandardMaterial({ color: 0x475569, metalness: 0.3, roughness: 0.38 }),
        halo: new SpriteMaterial({ map: glow, transparent: true, depthWrite: false, blending: AdditiveBlending, opacity: 0 }),
        glows: [],
        ring: new SpriteMaterial({ map: ring, transparent: true, depthWrite: false, depthTest: false, opacity: 0 }),
        rings: [],
        outlines: [],
      }
      parts.set(channel, part)
    }
    // The mesh's own material may be shared with other parts (the model's Seal_Heater): it isn't freed here
    mesh.material = part.material
    mesh.userData.channel = channel
    const outline = new LineSegments(new EdgesGeometry(mesh.geometry), outlineMaterial)
    outline.visible = false
    outline.renderOrder = 10
    mesh.add(outline)
    part.outlines.push(outline)
    const halo = new Sprite(part.halo)
    halo.scale.setScalar(glowSize)
    halo.userData.size = glowSize
    mesh.add(halo)
    part.glows.push(halo)
    // One ring per zone, on its first part: a front and a rear jaw share it
    if (part.rings.length === 0) {
      const alarm = new Sprite(part.ring)
      alarm.scale.setScalar(ringSize)
      alarm.userData.size = ringSize
      alarm.renderOrder = 12
      mesh.add(alarm)
      part.rings.push(alarm)
    }
    pickables.push(mesh)
    return mesh
  }

  return { parts, pickables, adopt }
}

/**
 * The stack light, standing on (x, y, z): green, amber and red over a pole, `size` the lamps' diameter.
 * The pole and cap go in `statics`; the lamps, lit by the line view, in `moving`.
 */
export function stackLight(statics: Object3D, moving: Object3D, x: number, y: number, z: number, size: number, glow: Texture, metal: Material, cap: Material) {
  const r = size / 2
  const h = size * 0.82
  const pole = new Mesh(new CylinderGeometry(r * 0.26, r * 0.26, size * 1.15, 10), metal)
  pole.position.set(x, y + size * 0.575, z)
  statics.add(pole)
  const base = y + size * 1.15
  const lamp = (color: number, i: number): Lamp => {
    const material = new MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0, roughness: 0.3, transparent: true, opacity: 0.92 })
    const halo = new SpriteMaterial({ map: glow, color, transparent: true, depthWrite: false, blending: AdditiveBlending, opacity: 0 })
    const mesh = new Mesh(new CylinderGeometry(r, r, h, 24), material)
    mesh.position.set(x, base + h * (i + 0.5), z)
    const sprite = new Sprite(halo)
    sprite.scale.setScalar(size * 4.3)
    mesh.add(sprite)
    moving.add(mesh)
    return { material, halo }
  }
  const lamps = { green: lamp(0x22c55e, 0), amber: lamp(0xf59e0b, 1), red: lamp(0xef4444, 2) }
  const top = new Mesh(new CylinderGeometry(r * 1.03, r * 1.03, size * 0.18, 24), cap)
  top.position.set(x, base + h * 3 + size * 0.09, z)
  statics.add(top)
  return lamps
}
