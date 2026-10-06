import {
  AdditiveBlending,
  BoxGeometry,
  BufferGeometry,
  CanvasTexture,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  EdgesGeometry,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  RepeatWrapping,
  SphereGeometry,
  Sprite,
  SpriteMaterial,
  SRGBColorSpace,
  TorusGeometry,
  Vector3,
  type Material,
  type Object3D,
  type Texture,
} from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'

import type { StationId } from './stations'

/**
 * The Volpak filler as a 3D model (ADR-0033), after its general arrangement drawing (SI-360 F3):
 * the film unwinder, the forming section with the bottom seal and six vertical seals, the filling
 * section with the pouch chain, three dosing nozzles and the top seal, and the discharge conveyor.
 * Schematic, not to scale: metres along x from the machine's middle, y up, the guarded front at +z.
 *
 * Every zone monitor-core judges is a part of its own (a jaw, a nozzle collar, the pressure gauge's
 * bezel), coloured by the line view. Everything else is merged by material into a few meshes.
 */

/** One pouch per cycle, indexed: the pouches move one pitch, then dwell while the jaws close. */
const CYCLE_S = 1.5
const PITCH = 0.25

const BAND = { x0: -4.15, x1: 0.45, y: 1.33, h: 0.3 }
/** Pitches from the band's start, so the seal lines printed on the film meet the jaws at each dwell */
const VERTICAL_X = [5, 7, 9, 11, 13, 15].map((k) => BAND.x0 + k * PITCH)
const BOTTOM_X = -3.45
const CHAIN = { x0: 0.75, slots: 18, y: 1.52 }
const NOZZLE_X = [1.75, 2.25, 2.75]
const GAUGE_X = 3.12
const TOP_X = 3.75
const SECTIONS = [
  { x0: -4.15, x1: 0.6 },
  { x0: 0.65, x1: 5.35 },
]

export interface ZonePart {
  channel: string
  material: MeshStandardMaterial
  halo: SpriteMaterial
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
  /** Puts every moving part where it is after this many seconds of running */
  animate(seconds: number): void
}

export const CALLOUTS: Record<StationId, Callout> = {
  bottom: { pin: new Vector3(BOTTOM_X, 1.2, 0.06), card: new Vector3(BOTTOM_X - 0.25, 0.45, 1.25), below: true },
  vertical: { pin: new Vector3(-1.65, 1.5, 0.05), card: new Vector3(-1.65, 2.75, 0.3), below: false },
  dosing: { pin: new Vector3(2.25, 2.0, 0.06), card: new Vector3(2.25, 2.75, 0.3), below: false },
  top: { pin: new Vector3(TOP_X, 1.6, 0.06), card: new Vector3(TOP_X + 0.25, 0.45, 1.25), below: true },
}

type Axis = 'x' | 'y' | 'z'

function canvasTexture(width: number, height: number, draw: (g: CanvasRenderingContext2D) => void): CanvasTexture {
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
    r.addColorStop(0.3, 'rgba(255,255,255,0.45)')
    r.addColorStop(1, 'rgba(255,255,255,0)')
    g.fillStyle = r
    g.fillRect(0, 0, 64, 64)
  })
}

/** One pouch's width of printed film: side seals at the edges, a generic label, the gusset fold. */
function printTexture(): CanvasTexture {
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

/** The operator panel's screen: a dark page with a few bars, lit by itself. */
function screenTexture(): CanvasTexture {
  return canvasTexture(160, 112, (g) => {
    g.fillStyle = '#0b1530'
    g.fillRect(0, 0, 160, 112)
    g.fillStyle = '#1d4ed8'
    g.fillRect(0, 0, 160, 14)
    const bars = ['#16a34a', '#16a34a', '#d97706', '#16a34a', '#16a34a']
    bars.forEach((color, i) => {
      g.fillStyle = '#1e293b'
      g.fillRect(12, 24 + i * 16, 136, 9)
      g.fillStyle = color
      g.fillRect(12, 24 + i * 16, 60 + ((i * 37) % 70), 9)
    })
  })
}

function palette() {
  const standard = (color: number, metalness: number, roughness: number) => new MeshStandardMaterial({ color, metalness, roughness })
  const glass = (color: number, opacity: number) =>
    new MeshStandardMaterial({ color, metalness: 0.1, roughness: 0.08, transparent: true, opacity, depthWrite: false, side: DoubleSide })
  const print = printTexture()
  print.wrapS = RepeatWrapping
  print.repeat.set((BAND.x1 - BAND.x0) / PITCH, 1)
  const pouchPrint = printTexture()
  return {
    steel: standard(0xb4bdc8, 0.8, 0.3),
    steelDark: standard(0x566170, 0.6, 0.42),
    painted: standard(0x8a95a3, 0.35, 0.5),
    wall: standard(0x273141, 0.35, 0.6),
    profile: standard(0xcfd6de, 0.75, 0.28),
    cabinet: standard(0x4a5361, 0.45, 0.48),
    motor: standard(0x2f3b52, 0.5, 0.4),
    rubber: standard(0x1c2128, 0, 0.85),
    film: new MeshStandardMaterial({ color: 0xeef2f6, roughness: 0.35, side: DoubleSide }),
    band: new MeshStandardMaterial({ map: print, roughness: 0.4, side: DoubleSide }),
    pouch: new MeshStandardMaterial({ map: pouchPrint, roughness: 0.38 }),
    pouchFilled: new MeshStandardMaterial({ map: pouchPrint, roughness: 0.32, color: 0xfff0d2 }),
    gaugeFace: standard(0xf8fafc, 0, 0.5),
    screen: new MeshBasicMaterial({ map: screenTexture() }),
    glassTeal: glass(0x6cc4c0, 0.17),
    glassBlue: glass(0xa3b6d6, 0.13),
    print,
  }
}

function span(x0: number, x1: number, y0: number, y1: number, z0: number, z1: number, material: Material, parent: Object3D): Mesh {
  const mesh = new Mesh(new BoxGeometry(x1 - x0, y1 - y0, z1 - z0), material)
  mesh.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
  parent.add(mesh)
  return mesh
}

function rod(axis: Axis, radius: number, length: number, material: Material, x: number, y: number, z: number, parent: Object3D, segments = 20): Mesh {
  const mesh = new Mesh(new CylinderGeometry(radius, radius, length, segments), material)
  if (axis === 'x') mesh.rotation.z = Math.PI / 2
  if (axis === 'z') mesh.rotation.x = Math.PI / 2
  mesh.position.set(x, y, z)
  parent.add(mesh)
  return mesh
}

/** A bar from a to b, `width` across and `depth` deep: legs, braces, the discharge chute. */
function strut(a: Vector3, b: Vector3, width: number, depth: number, material: Material, parent: Object3D): Mesh {
  const along = b.clone().sub(a)
  const mesh = new Mesh(new BoxGeometry(width, along.length(), depth), material)
  mesh.position.copy(a).add(b).multiplyScalar(0.5)
  mesh.quaternion.setFromUnitVectors(new Vector3(0, 1, 0), along.normalize())
  parent.add(mesh)
  return mesh
}

/** A flat panel facing +z, or turned to face x or y */
function pane(width: number, height: number, material: Material, x: number, y: number, z: number, facing: Axis, parent: Object3D): Mesh {
  const mesh = new Mesh(new PlaneGeometry(width, height), material)
  if (facing === 'x') mesh.rotation.y = Math.PI / 2
  if (facing === 'y') mesh.rotation.x = -Math.PI / 2
  mesh.position.set(x, y, z)
  parent.add(mesh)
  return mesh
}

/** The twelve edges of a box as aluminium profiles, like the machine's guarding. */
function frame(x0: number, x1: number, y0: number, y1: number, z0: number, z1: number, t: number, material: Material, parent: Object3D) {
  const h = t / 2
  for (const x of [x0, x1]) for (const z of [z0, z1]) span(x - h, x + h, y0, y1, z - h, z + h, material, parent)
  for (const y of [y0, y1]) for (const z of [z0, z1]) span(x0, x1, y - h, y + h, z - h, z + h, material, parent)
  for (const y of [y0, y1]) for (const x of [x0, x1]) span(x - h, x + h, y - h, y + h, z0, z1, material, parent)
}

/** A strip of film along a path in the x–y plane, `width` across in z: the web over the rollers. */
function ribbon(points: [number, number][], width: number): BufferGeometry {
  const positions: number[] = []
  const uvs: number[] = []
  const index: number[] = []
  let length = 0
  points.forEach(([x, y], i) => {
    if (i > 0) {
      const [px, py] = points[i - 1]!
      length += Math.hypot(x - px, y - py)
    }
    positions.push(x, y, -width / 2, x, y, width / 2)
    uvs.push(length / PITCH, 0, length / PITCH, 1)
    if (i > 0) {
      const a = (i - 1) * 2
      index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2)
    }
  })
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geometry.setAttribute('uv', new Float32BufferAttribute(uvs, 2))
  geometry.setIndex(index)
  geometry.computeVertexNormals()
  return geometry
}

/** Merges the static parts by material: a handful of draw calls instead of hundreds. */
function bake(group: Group) {
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
  for (const [material, geometries] of byMaterial) {
    const merged = mergeGeometries(geometries)
    geometries.forEach((g) => g.dispose())
    if (merged) group.add(new Mesh(merged, material))
  }
}

const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

interface Jaw {
  object: Object3D
  /** +1 the front jaw, -1 the rear */
  side: 1 | -1
  closed: number
  open: number
}

export function buildMachine(glow: Texture): Machine {
  const root = new Group()
  const statics = new Group()
  const moving = new Group()
  root.add(statics, moving)
  const m = palette()

  const parts = new Map<string, ZonePart>()
  const pickables: Mesh[] = []
  const outlineMaterial = new LineBasicMaterial({ color: 0xffffff, transparent: true, depthTest: false })
  const jaws: Jaw[] = []
  const nozzles: Object3D[] = []
  const spinners: { object: Object3D; radius: number }[] = []

  /** A zone's own mesh: coloured by its state, outlined when selected, with a glow around it. */
  const zoneMesh = (channel: string, geometry: BufferGeometry, parent: Object3D, x: number, y: number, z: number, glowSize: number): Mesh => {
    let part = parts.get(channel)
    if (!part) {
      part = {
        channel,
        material: new MeshStandardMaterial({ color: 0x475569, metalness: 0.3, roughness: 0.38 }),
        halo: new SpriteMaterial({ map: glow, transparent: true, depthWrite: false, blending: AdditiveBlending, opacity: 0 }),
        outlines: [],
      }
      parts.set(channel, part)
    }
    const mesh = new Mesh(geometry, part.material)
    mesh.position.set(x, y, z)
    mesh.userData.channel = channel
    const outline = new LineSegments(new EdgesGeometry(geometry), outlineMaterial)
    outline.visible = false
    outline.renderOrder = 10
    mesh.add(outline)
    const halo = new Sprite(part.halo)
    halo.scale.setScalar(glowSize)
    mesh.add(halo)
    parent.add(mesh)
    part.outlines.push(outline)
    pickables.push(mesh)
    return mesh
  }

  /** A pair of jaws closing on the film from the front and the rear, each on its actuator rod. */
  const jawPair = (x: number, y: number, size: [number, number, number], channels: [string, string] | null, closed: number, open: number) => {
    for (const side of [1, -1] as const) {
      const carriage = new Group()
      carriage.position.set(x, y, side * open)
      const geometry = new BoxGeometry(...size)
      const channel = channels ? channels[side === 1 ? 0 : 1] : null
      if (channel) zoneMesh(channel, geometry, carriage, 0, 0, 0, Math.max(size[0], size[1]) * 1.7)
      else carriage.add(new Mesh(geometry, m.steelDark))
      rod('z', 0.014, 0.3, m.steel, 0, 0, side * 0.17, carriage, 12)
      moving.add(carriage)
      jaws.push({ object: carriage, side, closed, open })
    }
    // The actuators' block on the wall
    span(x - size[0] / 2 - 0.05, x + size[0] / 2 + 0.05, y - 0.1, y + 0.1, -0.5, -0.42, m.steelDark, statics)
  }

  // --- Film unwinder ---------------------------------------------------------------------
  const u = { x0: -6.55, x1: -4.2, y0: 0.16, y1: 2.45, z0: -0.85, z1: 0.85 }
  span(u.x0, u.x1, 0.03, u.y0, u.z0, u.z1, m.steelDark, statics)
  frame(u.x0, u.x1, u.y0, u.y1, u.z0, u.z1, 0.05, m.profile, statics)
  for (const z of [u.z0, u.z1]) {
    span(-5.32, -5.28, u.y0, u.y1, z - 0.025, z + 0.025, m.profile, statics)
    span(u.x0, u.x1, 1.28, 1.32, z - 0.025, z + 0.025, m.profile, statics)
  }
  span(u.x0 + 0.05, u.x1 - 0.05, u.y0, u.y1 - 0.05, -0.64, -0.6, m.wall, statics)
  // The electrical cabinet's door, lower left, and the glazing elsewhere
  span(u.x0 + 0.03, -5.32, u.y0 + 0.02, 1.28, u.z1 - 0.012, u.z1, m.cabinet, statics)
  rod('y', 0.012, 0.25, m.steel, -5.45, 0.75, u.z1 + 0.02, statics, 10)
  pane(u.x1 + 5.28, 1.12, m.glassBlue, (-5.28 + u.x1) / 2, (u.y0 + 1.28) / 2, u.z1, 'z', statics)
  pane(u.x1 - u.x0, u.y1 - 1.32, m.glassBlue, (u.x0 + u.x1) / 2, (1.32 + u.y1) / 2, u.z1, 'z', statics)
  pane(u.x1 - u.x0, u.y1 - u.y0, m.glassBlue, (u.x0 + u.x1) / 2, (u.y0 + u.y1) / 2, u.z0, 'z', statics)
  pane(u.z1 - u.z0, u.y1 - u.y0, m.glassBlue, u.x0, (u.y0 + u.y1) / 2, 0, 'x', statics)
  pane(u.x1 - u.x0, u.z1 - u.z0, m.glassBlue, (u.x0 + u.x1) / 2, u.y1, 0, 'y', statics)

  // Two reels on cantilevered shafts, the web over its rollers, the former folding it upright
  const reel = (x: number, y: number, radius: number) => {
    const spindle = new Group()
    spindle.position.set(x, y, -0.05)
    rod('z', radius, 0.46, m.film, 0, 0, 0, spindle, 48)
    rod('z', 0.07, 0.5, m.steelDark, 0, 0, 0, spindle)
    rod('z', 0.035, 0.4, m.steelDark, 0, 0, -0.42, spindle)
    span(-0.11, 0.11, -0.012, 0.012, 0.245, 0.27, m.steel, spindle)
    span(-0.012, 0.012, -0.11, 0.11, 0.245, 0.27, m.steel, spindle)
    moving.add(spindle)
    spinners.push({ object: spindle, radius })
  }
  reel(-5.95, 1.8, 0.36)
  reel(-5.95, 0.72, 0.28)
  const rollers: [number, number][] = [[-5.35, 2.22], [-4.95, 1.72], [-4.6, 2.12], [-4.45, 1.45]]
  for (const [x, y] of rollers) {
    const roller = rod('z', 0.035, 0.52, m.steel, x, y, -0.05, moving, 16)
    spinners.push({ object: roller, radius: 0.035 })
  }
  strut(new Vector3(-5.2, 1.98, -0.36), new Vector3(-4.95, 1.72, -0.36), 0.04, 0.04, m.steelDark, statics)
  const web = new Mesh(
    ribbon([[-5.95, 2.165], [-5.35, 2.257], [-4.95, 1.684], [-4.6, 2.157], [-4.45, 1.413], [-4.24, 1.36]], 0.42),
    m.film,
  )
  web.position.z = -0.05
  statics.add(web)
  span(-4.3, -4.12, 1.1, 1.56, -0.13, 0.13, m.steel, statics)

  // --- The forming section and the filling section ------------------------------------------
  for (const { x0, x1 } of SECTIONS) {
    const mid = (x0 + x1) / 2
    span(x0, x1, 0.78, 0.92, -0.6, 0.6, m.painted, statics)
    span(x0, x1, 0.92, 2.12, -0.62, -0.5, m.wall, statics)
    span(x0 - 0.02, x1 + 0.02, 2.12, 2.2, -0.66, 0.7, m.painted, statics)
    // Guard doors on the front: profiles and teal glazing, as on the machine
    for (const x of [x0 + 0.025, mid, x1 - 0.025]) span(x - 0.025, x + 0.025, 0.92, 2.12, 0.64, 0.69, m.profile, statics)
    span(x0, x1, 0.92, 0.97, 0.64, 0.69, m.profile, statics)
    span(x0, x1, 2.07, 2.12, 0.64, 0.69, m.profile, statics)
    for (const [a, b] of [[x0 + 0.05, mid - 0.025], [mid + 0.025, x1 - 0.05]] as const) {
      pane(b - a, 1.1, m.glassTeal, (a + b) / 2, 1.52, 0.665, 'z', statics)
    }
    rod('y', 0.012, 0.22, m.steel, mid - 0.1, 1.5, 0.71, statics, 10)
    rod('y', 0.012, 0.22, m.steel, mid + 0.1, 1.5, 0.71, statics, 10)
    // A-frame legs and the truss beneath, as in the side view
    for (const x of [x0 + 0.4, x1 - 0.4]) {
      for (const side of [-1, 1]) {
        strut(new Vector3(x, 0.79, side * 0.42), new Vector3(x, 0.1, side * 0.7), 0.09, 0.09, m.painted, statics)
        rod('y', 0.075, 0.035, m.rubber, x, 0.02, side * 0.72, statics)
        rod('y', 0.02, 0.08, m.steel, x, 0.07, side * 0.71, statics, 10)
      }
      span(x - 0.035, x + 0.035, 0.42, 0.48, -0.56, 0.56, m.painted, statics)
    }
    for (const z of [-0.56, 0.56]) {
      strut(new Vector3(x0 + 0.4, 0.45, z), new Vector3(mid, 0.78, z), 0.06, 0.05, m.painted, statics)
      strut(new Vector3(mid, 0.78, z), new Vector3(x1 - 0.4, 0.45, z), 0.06, 0.05, m.painted, statics)
      span(x0 + 0.4, x1 - 0.4, 0.42, 0.48, z - 0.025, z + 0.025, m.painted, statics)
    }
    // Servo motors behind the mechanisms
    for (let x = x0 + 0.6; x < x1 - 0.3; x += 1.15) {
      rod('z', 0.07, 0.16, m.motor, x, 1.9, -0.42, statics)
      rod('z', 0.045, 0.04, m.steel, x, 1.9, -0.32, statics)
    }
  }
  // Glass at the line's two outer ends; the unwinder closes the first section's other end
  pane(1.14, 1.15, m.glassTeal, SECTIONS[1]!.x1, 1.52, 0.07, 'x', statics)

  // Electrical boxes on the deck, with their rows of connectors
  for (const [x0, x1] of [[-3.75, -2.8], [4.2, 5.15]] as const) {
    span(x0, x1, 2.2, 2.5, -0.38, 0.32, m.cabinet, statics)
    for (let x = x0 + 0.1; x < x1 - 0.05; x += 0.12) rod('z', 0.022, 0.05, m.rubber, x, 2.33, 0.345, statics, 12)
  }

  // The operator panel on its swing arm, at the front of the forming section
  rod('z', 0.025, 0.4, m.steel, -3.95, 2.16, 0.86, statics, 12)
  rod('y', 0.025, 0.2, m.steel, -3.95, 2.06, 1.04, statics, 12)
  span(-4.17, -3.73, 1.68, 1.98, 1.0, 1.06, m.cabinet, statics)
  pane(0.4, 0.26, m.screen, -3.95, 1.83, 1.062, 'z', statics)

  // --- Forming: the film band, bottom seal, six vertical seals, cooling, cutter ------------
  const band = new Mesh(new PlaneGeometry(BAND.x1 - BAND.x0, BAND.h), m.band)
  band.position.set((BAND.x0 + BAND.x1) / 2, BAND.y, 0)
  moving.add(band)
  span(BAND.x0, BAND.x1, 1.49, 1.51, -0.07, -0.03, m.steel, statics)
  jawPair(BOTTOM_X, 1.2, [0.42, 0.06, 0.07], ['P03.FRONT', 'P03.REAR'], 0.04, 0.15)
  VERTICAL_X.forEach((x, i) => jawPair(x, BAND.y, [0.06, 0.34, 0.07], [`P02.V${i + 1}`, `P02.V${i + 1}`], 0.04, 0.15))
  jawPair(BAND.x0 + 17 * PITCH, BAND.y, [0.06, 0.34, 0.07], null, 0.04, 0.15)
  span(0.3, 0.4, 1.52, 1.7, -0.12, 0.12, m.steelDark, statics)
  span(0.3, 0.4, 0.98, 1.15, -0.12, 0.12, m.steelDark, statics)

  // --- Filling: the pouch chain, opener, dosing, top seal, cooling, chute -----------------
  span(0.7, 5.25, 1.75, 1.8, -0.09, 0.09, m.steel, statics)
  rod('y', 0.13, 0.05, m.steelDark, 0.78, 1.775, 0, statics, 32)
  rod('y', 0.13, 0.05, m.steelDark, 5.17, 1.775, 0, statics, 32)
  const pouchGeometry = new BoxGeometry(0.16, 0.28, 1)
  const clampGeometry = new BoxGeometry(0.03, 0.06, 0.05)
  const pouches = Array.from({ length: CHAIN.slots }, () => {
    const group = new Group()
    const pouch = new Mesh(pouchGeometry, m.pouch)
    group.add(pouch)
    for (const x of [-0.07, 0.07]) {
      const clamp = new Mesh(clampGeometry, m.steelDark)
      clamp.position.set(x, 0.17, 0)
      group.add(clamp)
    }
    moving.add(group)
    return { group, pouch }
  })
  jawPair(1.25, 1.56, [0.05, 0.05, 0.03], null, 0.035, 0.1)

  // The dosing manifold under the deck, fed from the riser at the line's end
  rod('x', 0.055, 1.5, m.steel, 2.25, 2.0, 0, statics)
  NOZZLE_X.forEach((x, i) => {
    const nozzle = new Group()
    nozzle.position.x = x
    rod('y', 0.022, 0.32, m.steel, 0, 1.8, 0, nozzle, 16)
    const tip = new Mesh(new ConeGeometry(0.022, 0.05, 16), m.steel)
    tip.rotation.x = Math.PI
    tip.position.y = 1.615
    nozzle.add(tip)
    zoneMesh(`P06.N${i + 1}`, new CylinderGeometry(0.042, 0.042, 0.05, 24), nozzle, 0, 1.9, 0, 0.3)
    moving.add(nozzle)
    nozzles.push(nozzle)
    rod('y', 0.03, 0.12, m.steelDark, x, 2.06, -0.08, statics, 16)
  })
  rod('x', 0.02, 0.14, m.steel, 3.05, 2.0, 0, statics, 12)
  rod('z', 0.08, 0.04, m.gaugeFace, GAUGE_X, 2.0, 0.06, statics, 32)
  span(GAUGE_X - 0.004, GAUGE_X + 0.004, 2.0, 2.06, 0.081, 0.083, m.rubber, statics)
  zoneMesh('P09.MAIN', new TorusGeometry(0.08, 0.014, 10, 36), moving, GAUGE_X, 2.0, 0.085, 0.4)
  rod('y', 0.04, 1.62, m.steel, 5.5, 1.61, -0.5, statics)
  rod('x', 0.04, 3.25, m.steel, 3.875, 2.42, -0.5, statics)
  rod('y', 0.04, 0.22, m.steel, 2.25, 2.31, -0.5, statics)
  for (const x of [2.25, 5.5]) {
    const elbow = new Mesh(new SphereGeometry(0.04, 16, 12), m.steel)
    elbow.position.set(x, 2.42, -0.5)
    statics.add(elbow)
  }
  span(5.44, 5.56, 1.2, 1.32, -0.56, -0.44, m.steelDark, statics)
  rod('z', 0.03, 0.5, m.steel, 2.25, 2.0, -0.25, statics, 12)

  jawPair(TOP_X, 1.6, [0.22, 0.06, 0.06], ['P04.FRONT', 'P04.REAR'], 0.035, 0.14)
  jawPair(4.25, 1.6, [0.22, 0.06, 0.06], null, 0.035, 0.14)
  strut(new Vector3(5.12, 1.38, 0), new Vector3(5.42, 1.02, 0), 0.015, 0.3, m.steel, statics)

  // --- Discharge conveyor, under its glass cover -------------------------------------------
  span(5.4, 6.8, 0.93, 0.98, -0.2, 0.2, m.rubber, statics)
  for (const z of [-0.22, 0.22]) span(5.4, 6.8, 0.86, 1.02, z - 0.02, z + 0.02, m.steel, statics)
  for (const x of [5.4, 6.8]) rod('z', 0.045, 0.4, m.steelDark, x, 0.955, 0, statics)
  for (const x of [5.55, 6.65]) {
    for (const z of [-0.2, 0.2]) {
      span(x - 0.03, x + 0.03, 0.04, 0.86, z - 0.03, z + 0.03, m.painted, statics)
      rod('y', 0.05, 0.03, m.rubber, x, 0.02, z, statics, 12)
    }
  }
  frame(5.4, 6.8, 1.02, 1.3, -0.24, 0.24, 0.025, m.profile, statics)
  pane(1.4, 0.28, m.glassTeal, 6.1, 1.16, 0.24, 'z', statics)
  pane(1.4, 0.28, m.glassTeal, 6.1, 1.16, -0.24, 'z', statics)
  pane(1.4, 0.48, m.glassTeal, 6.1, 1.3, 0, 'y', statics)
  const conveyed = Array.from({ length: 5 }, (_, i) => {
    const pouch = new Mesh(pouchGeometry, m.pouchFilled)
    pouch.rotation.set(-Math.PI / 2, 0, (i % 2 ? 1 : -1) * 0.12)
    pouch.scale.z = 0.05
    moving.add(pouch)
    return pouch
  })

  // --- The stack light on the filling section's electrical box -----------------------------
  rod('y', 0.014, 0.1, m.steel, 5.0, 2.55, 0.15, statics, 10)
  const lamp = (color: number, y: number): Lamp => {
    const material = new MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0, roughness: 0.3, transparent: true, opacity: 0.92 })
    const halo = new SpriteMaterial({ map: glow, color, transparent: true, depthWrite: false, blending: AdditiveBlending, opacity: 0 })
    const mesh = rod('y', 0.05, 0.086, material, 5.0, y, 0.15, moving, 24)
    const sprite = new Sprite(halo)
    sprite.scale.setScalar(0.42)
    mesh.add(sprite)
    return { material, halo }
  }
  const lamps = { green: lamp(0x22c55e, 2.645), amber: lamp(0xf59e0b, 2.735), red: lamp(0xef4444, 2.825) }
  rod('y', 0.052, 0.02, m.steelDark, 5.0, 2.878, 0.15, statics, 24)

  bake(statics)

  const animate = (seconds: number) => {
    const cycles = seconds / CYCLE_S
    const cycle = Math.floor(cycles)
    const phase = cycles - cycle
    // Pitches the film and the chain have moved: one per cycle, in the first 30 % of it
    const moved = cycle + smooth(0, 0.3, phase)
    const close = smooth(0.36, 0.46, phase) * (1 - smooth(0.84, 0.94, phase))

    for (const jaw of jaws) jaw.object.position.z = jaw.side * (jaw.closed + (1 - close) * (jaw.open - jaw.closed))
    for (const nozzle of nozzles) nozzle.position.y = -0.11 * close
    m.print.offset.x = -moved
    const travelled = (seconds * PITCH) / CYCLE_S
    for (const { object, radius } of spinners) object.rotation.z = -travelled / radius

    pouches.forEach(({ group, pouch }, k) => {
      const slot = (k + moved) % CHAIN.slots
      const x = CHAIN.x0 + slot * PITCH
      const leaving = Math.max(0, slot - (CHAIN.slots - 1))
      group.position.set(x, CHAIN.y - leaving * 0.45, 0)
      const doses = NOZZLE_X.filter((nx) => x > nx - 0.01).length
      pouch.scale.z = 0.02 + 0.012 * doses
      pouch.material = doses ? m.pouchFilled : m.pouch
    })
    conveyed.forEach((pouch, i) => {
      const along = (i * 0.28 + travelled * 1.2) % 1.4
      pouch.position.set(5.4 + along, 1.005, ((i * 7) % 5) * 0.03 - 0.06)
    })
  }
  animate(0)

  return { root, parts, pickables, callouts: CALLOUTS, lamps, animate }
}
