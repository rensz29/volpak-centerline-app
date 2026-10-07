import { Loader2, RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Object3D } from 'three'
import WebGL from 'three/addons/capabilities/WebGL.js'

import { cn } from '@/utils/cn'

import { withUnit, type Tone } from '../liveModel'
import { GLOW } from './glow'
import { loadModel } from './loadModel'
import { PLACE, STATIONS, worstTone, type Station, type StationId, type TwinZone } from './stations'
import { createTwinScene, type TwinScene } from './twinScene'
import { TwinUnavailable } from './TwinUnavailable'

export interface MachineTwinProps {
  zones: TwinZone[]
  /** monitor-core reports the machine running */
  running: boolean
  /** The line's worst state for the stack light, or null while monitor-core isn't judging */
  line: Tone | null
  selected: string | null
  onSelect: (channel: string | null) => void
}

function StationCallout({ station, zones, selected, hovered, onSelect, onHover }: {
  station: Station
  zones: TwinZone[]
  selected: string | null
  hovered: string | null
  onSelect: (channel: string | null) => void
  onHover: (channel: string | null) => void
}) {
  if (zones.length === 0) return null
  const tone = worstTone(zones.map((z) => z.look))
  return (
    <div className={cn('bg-nav/85 shadow-overlay w-[212px] overflow-hidden rounded-lg border backdrop-blur-sm', GLOW[tone].border)}>
      <div className="flex items-center gap-2 border-b border-white/10 px-2.5 py-1.5">
        <span className={cn('size-2 shrink-0 rounded-full', GLOW[tone].dot)} aria-hidden />
        <span className="text-nav-fg-strong text-[12px] font-semibold">{station.name}</span>
        <span className="text-nav-fg ml-auto font-mono text-[10px]">{station.parameters}</span>
      </div>
      <ul className="py-1">
        {zones.map(({ channel, zone, parameter, look }) => {
          const Icon = look.icon
          const alarming = look.tone === 'warning' || look.tone === 'critical'
          return (
            <li key={channel}>
              <button
                type="button"
                onClick={() => onSelect(selected === channel ? null : channel)}
                onMouseEnter={() => onHover(channel)}
                onMouseLeave={() => onHover(null)}
                aria-pressed={selected === channel}
                title={`${zone.name}: ${look.label}`}
                className={cn(
                  'flex w-full items-center gap-2 px-2.5 py-[3px] text-left text-[12px] transition-colors hover:bg-white/[0.06]',
                  hovered === channel && 'bg-white/[0.06]',
                  selected === channel && 'bg-nav-active/80 hover:bg-nav-active/80',
                )}
              >
                <Icon className={cn('size-3.5 shrink-0', GLOW[look.tone].text)} aria-hidden />
                <span className="text-nav-fg min-w-0 flex-1 truncate">{zone.name}</span>
                <span className="sr-only">{look.label},</span>
                <span className={cn('font-mono tabular-nums', alarming ? GLOW[look.tone].text : 'text-nav-fg-strong')}>
                  {withUnit(zone.actual, parameter.unit)}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * The line view's 3D machine (ADR-0033): a callout per station with its zones' actual values,
 * each zone's part coloured by its state, the stack light showing the line's worst. It loads on
 * its own chunk, with three.js, so the rest of the page never waits for it.
 */
export default function MachineTwin({ zones, running, line, selected, onSelect }: MachineTwinProps) {
  const host = useRef<HTMLDivElement>(null)
  const twin = useRef<TwinScene | null>(null)
  const selectRef = useRef(onSelect)
  const [cards, setCards] = useState<Record<StationId, HTMLElement> | null>(null)
  // three.js draws with WebGL 2; anything else the scene throws reaches the line view's error boundary
  const [supported] = useState(() => WebGL.isWebGL2Available())
  const [hovered, setHovered] = useState<string | null>(null)
  // The owner's model (ADR-0034), as a maker of fresh copies: undefined while it loads, null if it can't, and
  // the scene then draws the machine in code (ADR-0033)
  const [model, setModel] = useState<(() => Object3D) | null | undefined>(undefined)

  useEffect(() => {
    if (!supported) return
    let live = true
    void loadModel().then((loaded) => {
      // Wrapped: a function given to a state setter is an updater
      if (live) setModel(() => loaded)
    })
    return () => {
      live = false
    }
  }, [supported])

  useEffect(() => {
    selectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    if (!host.current || model === undefined) return
    const scene = createTwinScene(host.current, { hover: setHovered, select: (channel) => selectRef.current(channel) }, model?.() ?? null)
    twin.current = scene
    setCards(scene.cards)
    return () => {
      scene.dispose()
      twin.current = null
      setCards(null)
    }
  }, [model])

  const byStation = useMemo(
    () => Object.fromEntries(STATIONS.map((s) => [s.id, zones.filter((z) => PLACE[z.channel] === s.id)])) as Record<StationId, TwinZone[]>,
    [zones],
  )

  useEffect(() => {
    twin.current?.update({
      tones: new Map(zones.map((z) => [z.channel, z.look.tone])),
      stations: Object.fromEntries(STATIONS.map((s) => [s.id, worstTone(byStation[s.id].map((z) => z.look))])) as Record<StationId, Tone>,
      line,
      running,
      selected,
      hovered,
    })
  }, [zones, byStation, line, running, selected, hovered, cards])

  // A new selection flies the camera to its part; clearing it flies back to the whole machine
  const focused = useRef<string | null>(null)
  useEffect(() => {
    if (!twin.current || focused.current === selected) return
    focused.current = selected
    twin.current.focus(selected)
  }, [selected, cards])

  if (!supported) return <TwinUnavailable detail="This browser has WebGL 2 switched off or unavailable, and the model needs it." />

  return (
    <div className="relative h-full w-full">
      <div ref={host} className="absolute inset-0" />
      {model === undefined && (
        <div className="text-nav-fg absolute inset-0 z-[2] flex items-center justify-center gap-2 text-[12px]">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Loading the 3D view…
        </div>
      )}
      {/* Darkens the edges so the machine stands out; under the callouts */}
      <div className="from-twin-floor/0 to-twin-floor/80 pointer-events-none absolute inset-0 z-[1] bg-radial-[at_50%_42%] from-55%" aria-hidden />
      {cards &&
        STATIONS.map((station) =>
          createPortal(
            <StationCallout station={station} zones={byStation[station.id]} selected={selected} hovered={hovered}
                            onSelect={onSelect} onHover={setHovered} />,
            cards[station.id],
            station.id,
          ),
        )}
      <div className="absolute top-3 right-3 z-[3]">
        <button
          type="button"
          onClick={() => twin.current?.resetView()}
          className="text-nav-fg hover:text-nav-fg-strong bg-nav/80 inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 px-2.5 text-[12px] font-medium backdrop-blur-sm transition-colors hover:bg-white/[0.08]"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          Reset view
        </button>
      </div>
      <p className="text-nav-fg pointer-events-none absolute bottom-2.5 left-4 z-[3] text-[11px]">
        Drag to turn · right-drag to move · scroll to zoom · select a part or a zone
      </p>
    </div>
  )
}
