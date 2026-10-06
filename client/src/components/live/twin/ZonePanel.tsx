import { AlertOctagon, AlertTriangle, CheckCircle2, ChevronRight, ExternalLink, MinusCircle, X } from 'lucide-react'
import type { ReactNode } from 'react'

import type { LiveZone } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'

import { withUnit } from '../liveModel'
import { ActualCell, ControlCell, HmiCell } from '../ZoneTable'
import { GLOW } from './glow'
import { PLACE, STATIONS, stationSummary, worstTone, worstZone, type TwinZone } from './stations'

/** A value monitor-core reported, under its series colour (Target green, HMI orange, Actual blue). */
function Reading({ label, value, unit, accent, className }: { label: string; value: string | null | undefined; unit: string | null; accent: string; className?: string }) {
  return (
    <div className={cn('rounded-md border border-t-2 border-white/10 bg-white/[0.03] px-2.5 py-2', accent)}>
      <dt className="text-nav-fg text-[11px]">{label}</dt>
      <dd className={cn('text-nav-fg-strong mt-0.5 font-mono text-[15px] font-semibold whitespace-nowrap tabular-nums', className)}>
        {withUnit(value, unit)}
      </dd>
    </div>
  )
}

const finite = (v: number | null): v is number => v !== null && Number.isFinite(v)
const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v))

/**
 * The zone's Warning and Critical bands (around its HMI setpoint, A-02) on one axis, with the
 * Actual, the HMI setpoint and the target marked on it.
 */
function BandGauge({ zone, unit }: { zone: LiveZone; unit: string | null }) {
  const b = zone.bands
  if (!b) {
    return <p className="text-nav-fg text-[12px]">No Warning or Critical limits for this zone in the rules it's judged by.</p>
  }
  const [critLow, warnLow, warnHigh, critHigh] = [b.critLow, b.warnLow, b.warnHigh, b.critHigh].map(Number) as [number, number, number, number]
  const marks = { actual: num(zone.actual), hmi: num(zone.setpoint), target: num(zone.target) }
  const known = Object.values(marks).filter(finite)
  const pad = (critHigh - critLow) * 0.25 || 1
  const lo = Math.min(critLow - pad, ...known.map((v) => v - pad * 0.3))
  const hi = Math.max(critHigh + pad, ...known.map((v) => v + pad * 0.3))
  const W = 300
  const x = (v: number) => ((v - lo) / (hi - lo)) * W
  const bands = [
    [lo, critLow, 'fill-critical-glow/35'],
    [critLow, warnLow, 'fill-warning-glow/40'],
    [warnLow, warnHigh, 'fill-normal-glow/35'],
    [warnHigh, critHigh, 'fill-warning-glow/40'],
    [critHigh, hi, 'fill-critical-glow/35'],
  ] as const
  // Limit labels, skipping any that would overlap the one before
  let lastX = -Infinity
  const ticks = [critLow, warnLow, warnHigh, critHigh].filter((v) => {
    if (x(v) - lastX < 34) return false
    lastX = x(v)
    return true
  })
  const u = unit ? ` ${unit}` : ''
  return (
    <figure>
      <svg viewBox={`0 0 ${W} 60`} className="w-full overflow-visible" role="img"
           aria-label={`Normal ${b.warnLow} to ${b.warnHigh}${u}, Warning up to ${b.critLow} to ${b.critHigh}${u}; actual ${zone.actual ?? 'unknown'}`}>
        {bands.map(([from, to, fill]) => (
          <rect key={`${from}-${fill}`} x={x(from)} y={22} width={Math.max(0, x(to) - x(from))} height={10} className={fill} />
        ))}
        {ticks.map((v) => (
          <g key={v}>
            <line x1={x(v)} x2={x(v)} y1={32} y2={36} className="stroke-nav-fg/60" />
            <text x={x(v)} y={47} textAnchor="middle" className="fill-nav-fg font-mono text-[9px]">{v}</text>
          </g>
        ))}
        {finite(marks.target) && (
          <line x1={x(marks.target)} x2={x(marks.target)} y1={16} y2={38} strokeWidth={2} strokeDasharray="3 2" className="stroke-series-target" />
        )}
        {finite(marks.hmi) && <line x1={x(marks.hmi)} x2={x(marks.hmi)} y1={17} y2={37} strokeWidth={2.5} className="stroke-series-hmi" />}
        {finite(marks.actual) && (
          <path d={`M ${x(marks.actual) - 6} 8 L ${x(marks.actual) + 6} 8 L ${x(marks.actual)} 18 Z`} className="fill-nav-fg-strong stroke-nav" strokeWidth={1} />
        )}
      </svg>
      <figcaption className="text-nav-fg mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
        <span><span className="text-nav-fg-strong">▼</span> Actual</span>
        <span><span className="text-series-hmi">┃</span> HMI setpoint</span>
        <span><span className="text-series-target">┆</span> Target</span>
        <span className="ml-auto font-mono tabular-nums">Normal {b.warnLow}–{b.warnHigh}{u}</span>
      </figcaption>
    </figure>
  )
}

function ZoneDetail({ item, now, onClose, onOpenEvent }: { item: TwinZone; now: number; onClose: () => void; onOpenEvent: (id: string) => void }) {
  const { zone: z, parameter: p, look } = item
  const Icon = look.icon
  const actualTone = z.actualSeverity === 'CRITICAL' ? 'critical' : z.actualSeverity === 'WARNING' ? 'warning' : null
  const eventLabel = (id: string) => (id === z.hmiEvent ? 'HMI mismatch event' : id === z.actualEvent ? 'Actual event' : 'Event')
  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="micro-label text-nav-fg">{p.name} · {p.id}</p>
          <h3 className="text-nav-fg-strong mt-0.5 text-[17px] leading-tight font-semibold">
            {z.name} <span className="text-nav-fg font-mono text-[12px] font-normal">{z.id}</span>
          </h3>
        </div>
        <button type="button" onClick={onClose} aria-label="Back to the stations"
                className="text-nav-fg hover:text-nav-fg-strong grid size-8 shrink-0 place-items-center rounded-md transition-colors hover:bg-white/[0.08]">
          <X className="size-4" aria-hidden />
        </button>
      </div>

      <div className={cn('flex items-center gap-2 rounded-md border px-3 py-2', GLOW[look.tone].border, GLOW[look.tone].soft)}>
        <Icon className={cn('size-4 shrink-0', GLOW[look.tone].text)} aria-hidden />
        <span className="text-nav-fg-strong text-[13px] font-semibold">{look.label}</span>
      </div>

      <dl className="grid grid-cols-3 gap-2">
        <Reading label="Target" value={z.target} unit={p.unit} accent="border-t-series-target" />
        <Reading label="HMI setpoint" value={z.setpoint} unit={p.unit} accent="border-t-series-hmi"
                 className={z.hmi === 'PENDING' || z.hmi === 'OPEN' ? 'text-warning-glow' : undefined} />
        <Reading label="Actual" value={z.actual} unit={p.unit} accent="border-t-series-actual"
                 className={actualTone ? GLOW[actualTone].text : undefined} />
      </dl>

      <BandGauge zone={z} unit={p.unit} />

      {/* The table's own checks, on a light card: the same badges, countdowns and event links */}
      <dl className="bg-surface flex flex-col gap-2.5 rounded-md p-3">
        {z.known && z.control ? (
          <div>
            <dt className="micro-label mb-1">Monitoring</dt>
            <dd><ControlCell c={z.control} z={z} onOpenEvent={onOpenEvent} /></dd>
          </div>
        ) : (
          <>
            <div>
              <dt className="micro-label mb-1">HMI check</dt>
              <dd><HmiCell z={z} now={now} onOpenEvent={onOpenEvent} /></dd>
            </div>
            <div>
              <dt className="micro-label mb-1">Actual check</dt>
              <dd><ActualCell z={z} unit={p.unit} now={now} onOpenEvent={onOpenEvent} /></dd>
            </div>
          </>
        )}
      </dl>

      {z.events.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {z.events.map((id) => (
            <button key={id} type="button" onClick={() => onOpenEvent(id)}
                    className="text-nav-fg-strong bg-nav-active hover:bg-brand inline-flex h-9 items-center justify-center gap-2 rounded-md text-[13px] font-medium transition-colors">
              <ExternalLink className="size-4" aria-hidden />
              Open the {eventLabel(id)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const LEGEND = [
  { tone: 'normal', icon: CheckCircle2, label: 'Normal' },
  { tone: 'warning', icon: AlertTriangle, label: 'Warning, or HMI off target' },
  { tone: 'critical', icon: AlertOctagon, label: 'Critical' },
  { tone: 'nodata', icon: MinusCircle, label: 'No data, or not judged' },
] as const

function StationButton({ name, detail, zones, onSelect }: { name: ReactNode; detail: string; zones: TwinZone[]; onSelect: (channel: string) => void }) {
  const tone = worstTone(zones.map((z) => z.look))
  const first = worstZone(zones)
  return (
    <button type="button" disabled={!first} onClick={() => first && onSelect(first.channel)}
            className="group flex w-full items-center gap-3 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2 text-left transition-colors hover:bg-white/[0.07] disabled:opacity-50">
      <span className={cn('size-2.5 shrink-0 rounded-full', GLOW[tone].dot)} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="text-nav-fg-strong block text-[13px] font-medium">{name}</span>
        <span className={cn('block text-[11px]', tone === 'warning' || tone === 'critical' ? GLOW[tone].text : 'text-nav-fg')}>{detail}</span>
      </span>
      <ChevronRight className="text-nav-fg group-hover:text-nav-fg-strong size-4 shrink-0" aria-hidden />
    </button>
  )
}

function LineOverview({ zones, onSelect }: { zones: TwinZone[]; onSelect: (channel: string) => void }) {
  const unplaced = zones.filter((z) => !PLACE[z.channel])
  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <h3 className="text-nav-fg-strong text-[14px] font-semibold">Stations</h3>
        <p className="text-nav-fg mt-0.5 text-[12px]">Select a station, a zone in a callout, or a part on the model.</p>
      </div>
      <ul className="flex flex-col gap-1.5">
        {STATIONS.map((station) => {
          const here = zones.filter((z) => PLACE[z.channel] === station.id)
          return (
            <li key={station.id}>
              <StationButton name={station.name} detail={stationSummary(here)} zones={here} onSelect={onSelect} />
            </li>
          )
        })}
      </ul>
      {unplaced.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="micro-label text-nav-fg">Monitored, not on the model yet</p>
          {unplaced.map((z) => (
            <StationButton key={z.channel} name={`${z.zone.name} · ${z.parameter.name}`} detail={z.look.label} zones={[z]} onSelect={onSelect} />
          ))}
        </div>
      )}
      <div className="border-t border-white/10 pt-3">
        <p className="micro-label text-nav-fg mb-2">Colours</p>
        <ul className="grid grid-cols-1 gap-1.5 text-[12px]">
          {LEGEND.map(({ tone, icon: Icon, label }) => (
            <li key={tone} className="text-nav-fg flex items-center gap-2">
              <Icon className={cn('size-3.5 shrink-0', GLOW[tone].text)} aria-hidden />
              {label}
            </li>
          ))}
        </ul>
        <p className="text-nav-fg mt-3 text-[11px] leading-relaxed">
          The stack light shows the line's worst state while monitor-core judges. The machine moves only while monitor-core
          reports it running.
        </p>
      </div>
    </div>
  )
}

/** Beside the model: the selected zone in full, or the stations to choose from. */
export function ZonePanel({ zones, selected, now, onSelect, onOpenEvent }: {
  zones: TwinZone[]
  selected: string | null
  now: number
  onSelect: (channel: string | null) => void
  onOpenEvent: (id: string) => void
}) {
  const current = zones.find((z) => z.channel === selected)
  return current ? (
    <ZoneDetail item={current} now={now} onClose={() => onSelect(null)} onOpenEvent={onOpenEvent} />
  ) : (
    <LineOverview zones={zones} onSelect={onSelect} />
  )
}
