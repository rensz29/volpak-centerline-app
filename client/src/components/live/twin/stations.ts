import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Hourglass,
  MinusCircle,
  PowerOff,
  SlidersHorizontal,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

import type { LiveParameter, LiveZone } from '@/types/monitoringApi'

import type { Tone } from '../liveModel'

/**
 * Where the monitored zones sit on the Volpak filler, for the line view (ADR-0033). The model is
 * drawn after the machine's general arrangement (SI-360 F3): film unwinder, bottom and vertical
 * seals, the pouch chain with its dosing nozzles, top seal, discharge conveyor.
 */

export type StationId = 'bottom' | 'vertical' | 'dosing' | 'top'

export interface Station {
  id: StationId
  name: string
  /** The URS parameters judged there */
  parameters: string
}

export const STATIONS: Station[] = [
  { id: 'bottom', name: 'Bottom seal', parameters: 'P03' },
  { id: 'vertical', name: 'Vertical seals', parameters: 'P02' },
  { id: 'dosing', name: 'Dosing', parameters: 'P06 · P09' },
  { id: 'top', name: 'Top seal', parameters: 'P04' },
]

/**
 * Each zone's place, by channel. A zone the register gains later (Configuration → Tags) has no
 * place until it's drawn: the line view lists it beside the model, and the table shows it as usual.
 */
export const PLACE: Record<string, StationId> = {
  'P03.FRONT': 'bottom',
  'P03.REAR': 'bottom',
  'P02.V1': 'vertical',
  'P02.V2': 'vertical',
  'P02.V3': 'vertical',
  'P02.V4': 'vertical',
  'P02.V5': 'vertical',
  'P02.V6': 'vertical',
  'P06.N1': 'dosing',
  'P06.N2': 'dosing',
  'P06.N3': 'dosing',
  'P09.MAIN': 'dosing',
  'P04.FRONT': 'top',
  'P04.REAR': 'top',
}

/** How a zone looks right now: monitor-core's states named and coloured, never judged again (ADR-0015). */
export interface Look {
  tone: Tone
  icon: LucideIcon
  label: string
}

export interface TwinZone {
  channel: string
  zone: LiveZone
  parameter: LiveParameter
  look: Look
}

/** The same reading as the zone table's checks: an Actual state, then the HMI state, worst first. */
export function zoneLook(z: LiveZone): Look {
  if (!z.known) return { tone: 'nodata', icon: MinusCircle, label: 'No data' }
  if (z.control?.state === 'off') return { tone: 'nodata', icon: PowerOff, label: 'Monitoring off' }
  if (z.control?.state === 'maintenance') return { tone: 'nodata', icon: Wrench, label: 'Maintenance' }
  if (z.control?.state === 'waiting') return { tone: 'nodata', icon: Hourglass, label: 'Waiting for fresh values' }
  // Without a value only an open event is a fact, as in the table
  const actual = z.actualSeverity && (z.actual != null || z.actualEvent) ? z.actualSeverity : undefined
  if (actual === 'CRITICAL') return { tone: 'critical', icon: AlertOctagon, label: 'Critical' }
  if (actual === 'WARNING') return { tone: 'warning', icon: AlertTriangle, label: 'Warning' }
  if (z.hmi === 'OPEN' && z.hmiEvent) return { tone: 'warning', icon: SlidersHorizontal, label: 'HMI mismatch' }
  if (z.hmi === 'PENDING' && z.setpoint != null) return { tone: 'warning', icon: Hourglass, label: 'HMI off target' }
  if (!actual) return { tone: 'nodata', icon: MinusCircle, label: 'No data' }
  return { tone: 'normal', icon: CheckCircle2, label: 'Normal' }
}

const RANK: Record<Tone, number> = { critical: 3, warning: 2, normal: 1, nodata: 0, brand: 0 }

/** The worst of some zones: Critical, then Warning, then Normal; No data only when nothing else is known. */
export function worstTone(looks: Look[]): Tone {
  return looks.reduce<Tone>((worst, l) => (RANK[l.tone] > RANK[worst] ? l.tone : worst), 'nodata')
}

/** The zone to open for a station: its worst, or its first. */
export function worstZone(zones: TwinZone[]): TwinZone | undefined {
  return zones.reduce<TwinZone | undefined>((worst, z) => (!worst || RANK[z.look.tone] > RANK[worst.look.tone] ? z : worst), undefined)
}

/** Every zone in register order, with its look. */
export function twinZones(parameters: LiveParameter[]): TwinZone[] {
  return parameters.flatMap((parameter) =>
    parameter.zones.map((zone) => ({ channel: zone.channel, zone, parameter, look: zoneLook(zone) })),
  )
}

/** "Vertical seals: 1 Critical, 2 Warnings", or "all Normal" */
export function stationSummary(zones: TwinZone[]): string {
  if (zones.length === 0) return 'No zones'
  const count = (tone: Tone) => zones.filter((z) => z.look.tone === tone).length
  const parts = [
    [count('critical'), 'Critical', 'Criticals'],
    [count('warning'), 'Warning', 'Warnings'],
    [count('nodata'), 'not judged', 'not judged'],
  ] as const
  const named = parts.filter(([n]) => n > 0).map(([n, one, many]) => `${n} ${n === 1 ? one : many}`)
  return named.length ? named.join(' · ') : `${zones.length === 1 ? 'Normal' : `all ${zones.length} Normal`}`
}
