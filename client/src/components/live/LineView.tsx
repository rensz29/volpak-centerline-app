import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  Box,
  CircleHelp,
  CirclePause,
  Eye,
  EyeOff,
  Flame,
  Gauge,
  Loader2,
  Maximize2,
  Minimize2,
  MinusCircle,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import { Component, Suspense, lazy, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { useLocalStorage } from '@/hooks/useLocalStorage'
import type { LiveView, MonitorStatus } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { formatManilaTime } from '@/utils/manilaTime'

import type { Tone } from './liveModel'
import { GLOW } from './twin/glow'
import { TwinUnavailable } from './twin/TwinUnavailable'
import { twinZones, worstTone } from './twin/stations'
import { ZonePanel } from './twin/ZonePanel'

// three.js is large: the model loads on its own chunk, after the page's data is on screen (PER-01).
const MachineTwin = lazy(() => import('./twin/MachineTwin'))

/** A chunk that fails to load, or a scene that throws, costs the model and nothing else on the page. */
class TwinBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  override render() {
    return this.state.failed ? <TwinUnavailable detail="The model failed to load. Reloading the page tries again." /> : this.props.children
  }
}

function machineState(monitor: MonitorStatus | null): { label: string; icon: LucideIcon; tone: Tone; detail: string } {
  if (!monitor?.alive) return { label: 'No data', icon: MinusCircle, tone: 'nodata', detail: "monitor-core isn't running" }
  switch (monitor.stop) {
    case 'running':
      return { label: 'Running', icon: Activity, tone: 'normal', detail: "From the machine's run signal" }
    case 'stopped':
      return { label: 'Stopped', icon: CirclePause, tone: 'nodata', detail: 'Actual rules paused while stopped' }
    case 'warmup':
      return {
        label: 'Warm-up',
        icon: Flame,
        tone: 'brand',
        detail: monitor.warmupUntil ? `Actual rules resume ${formatManilaTime(Date.parse(monitor.warmupUntil))}` : 'Actual rules paused',
      }
    default:
      return { label: 'Unknown', icon: CircleHelp, tone: 'nodata', detail: 'No run signal yet' }
  }
}

function Kpi({ label, value, detail, icon: Icon, tone }: { label: string; value: ReactNode; detail: string; icon: LucideIcon; tone: Tone | null }) {
  const lit = tone !== null && tone !== 'nodata'
  return (
    <div className="flex items-center gap-3 rounded-md border border-white/10 bg-white/[0.03] px-3.5 py-2.5">
      <span className={cn('grid size-9 shrink-0 place-items-center rounded-md', lit ? cn(GLOW[tone].soft, GLOW[tone].text) : 'text-nav-fg bg-white/[0.05]')}>
        <Icon className="size-[18px]" aria-hidden />
      </span>
      <div className="min-w-0">
        <p className="micro-label text-nav-fg">{label}</p>
        <p className={cn('tnum text-[22px] leading-tight font-semibold', lit ? GLOW[tone].text : 'text-nav-fg-strong')}>{value}</p>
        <p className="text-nav-fg truncate text-[11px]">{detail}</p>
      </div>
    </div>
  )
}

function HeaderButton({ onClick, icon: Icon, children }: { onClick: () => void; icon: LucideIcon; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick}
            className="text-nav-fg hover:text-nav-fg-strong inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 px-2.5 text-[12px] font-medium transition-colors hover:bg-white/[0.08]">
      <Icon className="size-3.5" aria-hidden />
      {children}
    </button>
  )
}

/**
 * The Digital Centerline page's line view (ADR-0033): the counts, the machine in 3D with each
 * monitored zone where it sits, and the selected zone's values and checks. It names and colours
 * monitor-core's states and judges nothing (ADR-0015); the zone table below stays the full record.
 */
export function LineView({ view, now, onOpenEvent }: { view: LiveView; now: number; onOpenEvent: (id: string) => void }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [showModel, setShowModel] = useLocalStorage('dc.lineview.model', true)
  const [fullscreen, setFullscreen] = useState(false)
  const root = useRef<HTMLElement>(null)

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === root.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const zones = useMemo(() => twinZones(view.parameters), [view.parameters])
  const monitor = view.monitor
  const judging = !!monitor?.alive && !!monitor.judging
  const running = !!monitor?.alive && monitor.stop === 'running'
  const line = judging ? worstTone(zones.map((z) => z.look)) : null
  const machine = machineState(monitor)
  const counts = view.counts

  // The event sheet opens over the page, which a full-screen line view would hide
  const openEvent = (id: string) => {
    if (document.fullscreenElement) void document.exitFullscreen()
    onOpenEvent(id)
  }
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void root.current?.requestFullscreen()
  }

  return (
    <section ref={root} aria-label="Line view"
             className={cn('bg-nav border-nav-border shadow-raised text-nav-fg overflow-hidden rounded-lg border', fullscreen && 'flex h-screen flex-col rounded-none border-0')}>
      <div className="flex flex-wrap items-center gap-3 border-b border-white/10 px-5 py-3">
        <span className="bg-nav-accent/15 text-nav-accent grid size-8 shrink-0 place-items-center rounded-md">
          <Box className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-nav-fg-strong text-[15px] leading-tight font-semibold">Line view · Volpak filler</h2>
          <p className="text-[12px]">The machine in 3D, modelled after its general arrangement (SI-360 F3)</p>
        </div>
        <div className="flex items-center gap-2">
          {showModel && (
            <HeaderButton onClick={toggleFullscreen} icon={fullscreen ? Minimize2 : Maximize2}>
              {fullscreen ? 'Exit full screen' : 'Full screen'}
            </HeaderButton>
          )}
          <HeaderButton onClick={() => setShowModel(!showModel)} icon={showModel ? EyeOff : Eye}>
            {showModel ? 'Hide 3D' : 'Show 3D'}
          </HeaderButton>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 border-b border-white/10 px-5 py-3 md:grid-cols-3 xl:grid-cols-5">
        <Kpi label="Machine" value={machine.label} detail={machine.detail} icon={machine.icon} tone={machine.tone} />
        <Kpi label="Zones monitored" value={counts.zones} detail="From the register in effect" icon={Gauge} tone={null} />
        <Kpi label="HMI mismatches" value={counts.hmiOpen} detail="Setpoint off target past the delay" icon={SlidersHorizontal}
             tone={counts.hmiOpen ? 'warning' : null} />
        <Kpi label="Warnings" value={counts.warning} detail="Actual past the Warning limits" icon={AlertTriangle}
             tone={counts.warning ? 'warning' : null} />
        <Kpi label="Criticals" value={counts.critical} detail="Actual past the Critical limits" icon={AlertOctagon}
             tone={counts.critical ? 'critical' : null} />
      </div>

      {showModel && (
        <div className={cn('grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px]', fullscreen && 'min-h-0 flex-1')}>
          <div className={cn('bg-twin-floor relative min-w-0', fullscreen ? 'min-h-[420px]' : 'h-[560px]')}>
            <TwinBoundary>
              <Suspense
                fallback={
                  <div className="text-nav-fg flex h-full items-center justify-center gap-2 text-[12px]">
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                    Loading the 3D view…
                  </div>
                }
              >
                <MachineTwin zones={zones} running={running} line={line} selected={selected} onSelect={setSelected} />
              </Suspense>
            </TwinBoundary>
          </div>
          <aside aria-label="Selected zone"
                 className={cn('min-h-0 overflow-y-auto border-t border-white/10 xl:border-t-0 xl:border-l', !fullscreen && 'xl:h-[560px]')}>
            <ZonePanel zones={zones} selected={selected} now={now} onSelect={setSelected} onOpenEvent={openEvent} />
          </aside>
        </div>
      )}
    </section>
  )
}
