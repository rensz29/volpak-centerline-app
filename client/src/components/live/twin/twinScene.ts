import {
  ACESFilmicToneMapping,
  AdditiveBlending,
  Box3,
  BufferGeometry,
  CanvasTexture,
  Color,
  Fog,
  GridHelper,
  HemisphereLight,
  DirectionalLight,
  Line,
  LineBasicMaterial,
  Material,
  Mesh,
  MeshBasicMaterial,
  NormalBlending,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  Raycaster,
  Scene,
  SphereGeometry,
  SRGBColorSpace,
  Sprite,
  Vector2,
  Vector3,
  WebGLRenderer,
  type Object3D,
} from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js'

import type { Tone } from '../liveModel'
import { buildMachine } from './buildMachine'
import { machineFromModel } from './fromModel'
import { glowTexture, ringTexture, type Machine } from './parts'
import { STATIONS, type StationId } from './stations'

/**
 * The line view's 3D scene (ADR-0033): the machine on a floor, a camera the user turns, a callout
 * card per station, and a loop that draws only when something changed, or at 30 frames a second
 * while the machine runs or a Critical pulses. Off screen, it doesn't draw at all.
 */

export interface TwinState {
  /** Each zone's tone, by channel */
  tones: Map<string, Tone>
  stations: Record<StationId, Tone>
  /** The stack light: the line's worst state, or nothing while monitor-core isn't judging */
  line: Tone | null
  /** monitor-core reports the machine running: it moves */
  running: boolean
  selected: string | null
  hovered: string | null
}

export interface TwinScene {
  /** The callout cards' elements, for React to render into */
  cards: Record<StationId, HTMLElement>
  update(state: TwinState): void
  /** Flies to a zone's part, or back to the whole machine */
  focus(channel: string | null): void
  resetView(): void
  dispose(): void
}

const FRAME_MS = 1000 / 30
const HOME_DIRECTION = new Vector3(-0.34, 0.33, 0.88).normalize()

/** A design token, as the scene's colour */
function token(name: string): Color {
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim()
  return new Color(value || '#64748b')
}

function shadowTexture(): CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = 512
  canvas.height = 128
  const g = canvas.getContext('2d')
  if (g) {
    g.filter = 'blur(18px)'
    g.fillStyle = 'rgba(0,0,0,0.7)'
    g.fillRect(40, 34, 432, 60)
  }
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  return texture
}

/**
 * Throws when the browser can't give a WebGL context; the line view's error boundary then says so.
 * `model` is the owner's model of the machine (ADR-0034), the scene's own copy, which it frees when it
 * closes; null, or a model that can't be read, draws the machine in code (ADR-0033).
 */
export function createTwinScene(
  host: HTMLElement,
  events: { hover(channel: string | null): void; select(channel: string | null): void },
  model: Object3D | null = null,
): TwinScene {
  const renderer = new WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.outputColorSpace = SRGBColorSpace
  renderer.toneMapping = ACESFilmicToneMapping
  renderer.domElement.style.display = 'block'
  renderer.domElement.style.cursor = 'grab'
  renderer.domElement.setAttribute('role', 'img')
  renderer.domElement.setAttribute('aria-label', 'The Volpak filler in 3D, each monitored zone coloured by its state')
  host.appendChild(renderer.domElement)

  const labels = new CSS2DRenderer()
  // Above the vignette the line view lays over the canvas
  Object.assign(labels.domElement.style, { position: 'absolute', top: '0', left: '0', pointerEvents: 'none', zIndex: '2' })
  host.appendChild(labels.domElement)

  const colors = {
    normal: token('normal-glow'),
    warning: token('warning-glow'),
    critical: token('critical-glow'),
    nodata: token('nodata-glow'),
    brand: token('nav-accent'),
    floor: token('twin-floor'),
    grid: token('nav-hover'),
    leader: token('nav-fg'),
  }

  const scene = new Scene()
  scene.background = colors.floor
  scene.fog = new Fog(colors.floor, 26, 60)
  const pmrem = new PMREMGenerator(renderer)
  const room = new RoomEnvironment()
  const environment = pmrem.fromScene(room, 0.04).texture
  room.dispose()
  scene.environment = environment
  scene.environmentIntensity = 0.5
  scene.add(new HemisphereLight(0xdbeafe, colors.floor, 0.6))
  const key = new DirectionalLight(0xffffff, 1.5)
  key.position.set(-6, 10, 8)
  const rim = new DirectionalLight(0x93c5fd, 0.6)
  rim.position.set(8, 5, -7)
  scene.add(key, rim)

  // The floor: a faint grid fading into the fog, and a soft shadow under the machine
  const grid = new GridHelper(90, 90, colors.grid, colors.grid)
  const gridMaterial = grid.material as Material
  gridMaterial.transparent = true
  gridMaterial.opacity = 0.55
  scene.add(grid)

  const glow = glowTexture()
  const ring = ringTexture()
  const fromCode = () => buildMachine(glow, ring)
  let machine: Machine
  try {
    machine = model ? machineFromModel(model, glow, ring) : fromCode()
  } catch {
    // A model the line view can't make sense of: the machine drawn in code still shows every zone
    machine = fromCode()
  }
  scene.add(machine.root)
  const box = new Box3().setFromObject(machine.root)
  const corners = [box.min.x, box.max.x].flatMap((x) =>
    [box.min.y, box.max.y].flatMap((y) => [box.min.z, box.max.z].map((z) => new Vector3(x, y, z))),
  )
  /** Above the machine's middle, so it sits low in the frame and the callouts fit above it */
  const homeTarget = new Vector3((box.min.x + box.max.x) / 2, box.max.y * 0.6, (box.min.z + box.max.z) / 2)
  const shadow = new Mesh(
    new PlaneGeometry(box.max.x - box.min.x + 2, box.max.z - box.min.z + 1.6),
    new MeshBasicMaterial({ map: shadowTexture(), transparent: true, depthWrite: false }),
  )
  shadow.rotation.x = -Math.PI / 2
  shadow.position.set(homeTarget.x, 0.004, homeTarget.z)
  scene.add(shadow)

  // A callout per station: a pin on the machine, a leader line, and a card React renders into
  const outlineHover = new LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, depthTest: false })
  const outlineSelected = new LineBasicMaterial({ color: colors.brand, depthTest: false })
  const pinGeometry = new SphereGeometry(0.035, 16, 12)
  const pins = {} as Record<StationId, MeshBasicMaterial>
  const cards = {} as Record<StationId, HTMLElement>
  const cardObjects: CSS2DObject[] = []
  for (const { id } of STATIONS) {
    const { pin, card, below } = machine.callouts[id]
    const pinMaterial = new MeshBasicMaterial({ color: colors.nodata, depthTest: false, transparent: true })
    const pinMesh = new Mesh(pinGeometry, pinMaterial)
    pinMesh.position.copy(pin)
    pinMesh.renderOrder = 21
    const leader = new Line(
      new BufferGeometry().setFromPoints([pin, card]),
      new LineBasicMaterial({ color: colors.leader, transparent: true, opacity: 0.5, depthTest: false }),
    )
    leader.renderOrder = 20
    const element = document.createElement('div')
    element.style.pointerEvents = 'auto'
    const object = new CSS2DObject(element)
    object.position.copy(card)
    object.center.set(0.5, below ? 0 : 1)
    scene.add(pinMesh, leader, object)
    pins[id] = pinMaterial
    cards[id] = element
    cardObjects.push(object)
  }

  const camera = new PerspectiveCamera(28, 1, 0.1, 120)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minDistance = 1.2
  controls.maxDistance = 32
  controls.maxPolarAngle = 1.5
  controls.screenSpacePanning = true

  /** The distance that fits the whole machine in the frame from the home direction */
  const homeDistance = () => {
    let near = 2
    let far = 80
    for (let i = 0; i < 22; i++) {
      const d = (near + far) / 2
      camera.position.copy(homeTarget).addScaledVector(HOME_DIRECTION, d)
      camera.lookAt(homeTarget)
      camera.updateMatrixWorld()
      // The machine inside the frame, and room for the callout cards above and below it
      const fits =
        corners.every((c) => {
          const p = c.clone().project(camera)
          return Math.abs(p.x) <= 0.94 && Math.abs(p.y) <= 0.9
        }) &&
        STATIONS.every(({ id }) => {
          const { card, below } = machine.callouts[id]
          const y = card.clone().project(camera).y
          return below ? y >= -0.6 : y <= 0.36
        })
      if (fits) far = d
      else near = d
    }
    return far
  }
  const goHome = () => {
    // Measured first: the search moves the camera itself
    const distance = homeDistance()
    controls.target.copy(homeTarget)
    camera.position.copy(homeTarget).addScaledVector(HOME_DIRECTION, distance)
    camera.lookAt(homeTarget)
  }

  let state: TwinState = { tones: new Map(), stations: { bottom: 'nodata', vertical: 'nodata', dosing: 'nodata', top: 'nodata' }, line: null, running: false, selected: null, hovered: null }
  let dirty = true
  let visible = true
  let userMoved = false
  let flight: { from: Vector3; fromTarget: Vector3; to: Vector3; toTarget: Vector3; start: number } | null = null
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  controls.addEventListener('start', () => {
    userMoved = true
    flight = null
  })

  const resize = () => {
    const width = host.clientWidth
    const height = host.clientHeight
    if (!width || !height) return
    renderer.setSize(width, height)
    labels.setSize(width, height)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    if (!userMoved) goHome()
    dirty = true
  }
  const resizer = new ResizeObserver(resize)
  resizer.observe(host)
  const watcher = new IntersectionObserver(([entry]) => {
    visible = entry?.isIntersecting ?? true
    dirty = true
  })
  watcher.observe(host)

  // The pointer: hover outlines a zone, a click (not a drag) selects it, or clears the selection
  const raycaster = new Raycaster()
  const pointer = new Vector2()
  let pointerMoved = false
  let pressedAt: { x: number; y: number } | null = null
  const pick = (): string | null => {
    raycaster.setFromCamera(pointer, camera)
    const hit = raycaster.intersectObjects(machine.pickables, false)[0]
    return (hit?.object.userData.channel as string | undefined) ?? null
  }
  const canvas = renderer.domElement
  const onMove = (e: PointerEvent) => {
    const r = canvas.getBoundingClientRect()
    pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    pointerMoved = true
  }
  const onLeave = () => {
    pointerMoved = false
    if (state.hovered) events.hover(null)
    canvas.style.cursor = 'grab'
  }
  const onDown = (e: PointerEvent) => {
    pressedAt = { x: e.clientX, y: e.clientY }
  }
  const onUp = (e: PointerEvent) => {
    if (pressedAt && Math.hypot(e.clientX - pressedAt.x, e.clientY - pressedAt.y) < 5) events.select(pick())
    pressedAt = null
  }
  canvas.addEventListener('pointermove', onMove)
  canvas.addEventListener('pointerleave', onLeave)
  canvas.addEventListener('pointerdown', onDown)
  canvas.addEventListener('pointerup', onUp)

  const paint = (pulse: number) => {
    for (const [channel, part] of machine.parts) {
      const tone = state.tones.get(channel) ?? 'nodata'
      const color = colors[tone]
      const judged = tone !== 'nodata'
      part.material.color.copy(color).multiplyScalar(judged ? 0.5 : 0.35)
      part.material.emissive.copy(color)
      part.material.emissiveIntensity = { critical: 0.6 + 0.9 * pulse, warning: 0.85, normal: 0.42, nodata: 0.05, brand: 0.4 }[tone]
      part.halo.color.copy(color)
      // A Warning or a Critical glows through whatever stands in front of it (the rear jaws sit behind the
      // pouches), blended so its colour shows on white film too, where added light would only turn white
      const alarm = tone === 'warning' || tone === 'critical'
      part.halo.depthTest = !alarm
      part.halo.blending = alarm ? NormalBlending : AdditiveBlending
      part.ring.color.copy(color)
      part.ring.opacity = tone === 'critical' ? 0.65 + 0.35 * pulse : tone === 'warning' ? 0.9 : 0
      for (const sprite of part.rings) sprite.scale.setScalar((sprite.userData.size as number) * (tone === 'critical' ? 1 + 0.4 * (1 - pulse) : 1))
      part.halo.opacity = { critical: 0.7 + 0.3 * pulse, warning: 0.65, normal: 0.2, nodata: 0, brand: 0.3 }[tone]
      for (const sprite of part.glows) sprite.scale.setScalar((sprite.userData.size as number) * (tone === 'critical' ? 1.2 + 0.5 * pulse : 1))
      const selected = state.selected === channel
      if (selected) part.halo.opacity = Math.max(part.halo.opacity, 0.45)
      for (const outline of part.outlines) {
        outline.visible = selected || state.hovered === channel
        outline.material = selected ? outlineSelected : outlineHover
      }
    }
    for (const { id } of STATIONS) pins[id].color.copy(colors[state.stations[id]])
    const lit = { red: state.line === 'critical', amber: state.line === 'warning', green: state.line === 'normal' }
    for (const name of ['red', 'amber', 'green'] as const) {
      const lamp = machine.lamps[name]
      const on = lit[name]
      const level = name === 'red' ? 0.5 + 0.5 * pulse : 1
      lamp.material.emissiveIntensity = on ? 2.4 * level : 0.03
      lamp.material.opacity = on ? 0.95 : 0.55
      lamp.halo.opacity = on ? 0.75 * level : 0
    }
  }

  let machineSeconds = 0
  let last = performance.now()
  let lastDrawn = 0
  let frame = 0
  const tick = (now: number) => {
    frame = requestAnimationFrame(tick)
    const dt = Math.min(0.1, (now - last) / 1000)
    last = now
    if (!visible) return
    const still = reducedMotion.matches
    const pulsing = !still && (state.line === 'critical' || [...state.tones.values()].includes('critical'))
    const moving = state.running && !still
    if (moving) machineSeconds += dt

    if (flight) {
      const t = Math.min(1, (now - flight.start) / 600)
      const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2
      camera.position.lerpVectors(flight.from, flight.to, eased)
      controls.target.lerpVectors(flight.fromTarget, flight.toTarget, eased)
      if (t === 1) flight = null
      dirty = true
    }
    if (pointerMoved) {
      pointerMoved = false
      const hovered = pick()
      canvas.style.cursor = hovered ? 'pointer' : 'grab'
      if (hovered !== state.hovered) events.hover(hovered)
    }
    const turned = controls.update(dt)
    const ambient = (moving || pulsing) && now - lastDrawn >= FRAME_MS
    if (!(dirty || turned || ambient)) return

    machine.animate(machineSeconds)
    paint(pulsing ? 0.5 + 0.5 * Math.sin((now / 1000) * Math.PI * 2.4) : 1)
    renderer.render(scene, camera)
    labels.render(scene, camera)
    lastDrawn = now
    dirty = false
  }
  resize()
  frame = requestAnimationFrame(tick)

  const fly = (to: Vector3, toTarget: Vector3) => {
    dirty = true
    if (reducedMotion.matches) {
      camera.position.copy(to)
      controls.target.copy(toTarget)
      return
    }
    flight = { from: camera.position.clone(), fromTarget: controls.target.clone(), to, toTarget, start: performance.now() }
  }
  const flyHome = () => {
    userMoved = false
    const from = camera.position.clone()
    const fromTarget = controls.target.clone()
    goHome()
    const to = camera.position.clone()
    camera.position.copy(from)
    controls.target.copy(fromTarget)
    fly(to, homeTarget.clone())
  }

  return {
    cards,
    update(next) {
      state = next
      dirty = true
    },
    focus(channel) {
      const mesh = channel ? machine.pickables.find((m) => m.userData.channel === channel) : undefined
      if (!mesh) return flyHome()
      userMoved = true
      const point = mesh.getWorldPosition(new Vector3())
      // From the side the camera is on, but low: the stations sit under the deck, behind the front guards
      const direction = camera.position.clone().sub(controls.target).setY(0).normalize().setY(0.22).normalize()
      fly(point.clone().addScaledVector(direction, machine.focusDistance), point)
    },
    resetView: flyHome,
    dispose() {
      cancelAnimationFrame(frame)
      resizer.disconnect()
      watcher.disconnect()
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerleave', onLeave)
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointerup', onUp)
      controls.dispose()
      for (const object of cardObjects) object.removeFromParent()
      scene.traverse((object: Object3D) => {
        if (object instanceof Mesh || object instanceof Line || object instanceof Sprite) {
          // Every sprite shares three's one quad: it isn't ours to free
          if (!(object instanceof Sprite)) object.geometry.dispose()
          const materials: Material[] = Array.isArray(object.material) ? object.material : [object.material]
          for (const material of materials) {
            for (const value of Object.values(material)) if (value && typeof value === 'object' && 'isTexture' in value) (value as { dispose(): void }).dispose()
            material.dispose()
          }
        }
      })
      outlineHover.dispose()
      outlineSelected.dispose()
      glow.dispose()
      ring.dispose()
      environment.dispose()
      pmrem.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
      canvas.remove()
      labels.domElement.remove()
    },
  }
}
