import type { MonitorEvent, Severity } from '@/types/monitoringApi'
import { formatManilaTime } from '@/utils/manilaTime'

/**
 * Display helpers for the live Digital Centerline page (ADR-0015). States come from
 * monitor-core; these only name and colour them, and count down to timers it set.
 */

export type Tone = 'normal' | 'warning' | 'critical' | 'nodata' | 'brand'

export const TONE: Record<Tone, { badge: string; dot: string; text: string; rail: string }> = {
  normal: { badge: 'border-normal-border bg-normal-surface text-normal', dot: 'bg-normal-solid', text: 'text-normal', rail: 'bg-normal-solid' },
  warning: { badge: 'border-warning-border bg-warning-surface text-warning', dot: 'bg-warning-solid', text: 'text-warning', rail: 'bg-warning-solid' },
  critical: { badge: 'border-critical-border bg-critical-surface text-critical', dot: 'bg-critical-solid', text: 'text-critical', rail: 'bg-critical-solid' },
  nodata: { badge: 'border-nodata-border bg-nodata-surface text-nodata', dot: 'bg-nodata-solid', text: 'text-nodata', rail: 'bg-nodata-solid' },
  brand: { badge: 'border-brand/30 bg-brand-surface text-brand', dot: 'bg-brand', text: 'text-brand', rail: 'bg-brand' },
}

export const SEVERITY_TONE: Record<Severity, Tone> = { NORMAL: 'normal', WARNING: 'warning', CRITICAL: 'critical' }
export const SEVERITY_LABEL: Record<Severity, string> = { NORMAL: 'Normal', WARNING: 'Warning', CRITICAL: 'Critical' }

export const EVENT_STATE_LABEL: Record<string, string> = {
  OPEN: 'Open',
  WARNING: 'Warning',
  CRITICAL: 'Critical',
  RESOLVED: 'Resolved',
  SUPERSEDED: 'Superseded',
  CLOSED_SKU_CHANGEOVER: 'Closed: SKU changeover',
  CLOSED_MONITORING_DISABLED: 'Closed: monitoring switched off',
  ACKNOWLEDGED: 'Acknowledged',
}

/** The colour of each change of state in an event's timeline. */
export const STATE_TONE: Record<string, Tone> = {
  OPEN: 'warning',
  WARNING: 'warning',
  CRITICAL: 'critical',
  RESOLVED: 'normal',
  SUPERSEDED: 'nodata',
  CLOSED_SKU_CHANGEOVER: 'nodata',
  CLOSED_MONITORING_DISABLED: 'nodata',
  ACKNOWLEDGED: 'brand',
}

export const NOTIFICATION_LABEL: Record<string, string> = {
  initial: 'First notice',
  escalated: 'Escalated to Critical',
  recovery: 'Recovery notice',
  critical_repeat: 'Critical repeat',
  critical_escalation: 'Final escalation',
  changeover: 'SKU changeover',
  system: 'System alert',
}

/** A message's delivery state in an event's evidence (ADR-0023) */
export const DELIVERY_STATE: Record<string, string> = {
  pending: 'waiting to be routed',
  unrouted: 'not sent: no routing for it',
  expired: 'not sent: over 24 h old',
  waiting: 'sending',
  sent: 'sent',
  failed: 'failed: an Administrator can re-drive it',
}

export function eventTitle(e: Pick<MonitorEvent, 'kind' | 'severity'>): string {
  return e.kind === 'HMI_MISMATCH' ? 'HMI mismatch' : `Actual ${SEVERITY_LABEL[e.severity ?? 'WARNING']}`
}

export function eventTone(e: Pick<MonitorEvent, 'kind' | 'severity' | 'open'>): Tone {
  if (!e.open) return 'nodata'
  return e.kind === 'HMI_MISMATCH' ? 'warning' : SEVERITY_TONE[e.severity ?? 'WARNING']
}

/** "221.4 °C"; an em dash when unknown. */
export function withUnit(value: string | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return unit ? `${value} ${unit}` : value
}

const FACT_ORDER = ['actual', 'hmi', 'target', 'pending_since', 'acknowledged_by', 'note']

/** A change of state's inputs as monitor-core recorded them, in words: "HMI 213 °C", "off target since 13:19:27". */
export function transitionFacts(inputs: Record<string, unknown>, unit: string | null | undefined): string[] {
  // A fixed order (the database keeps JSON keys in its own); the band only repeats the state
  const keys = [...FACT_ORDER, ...Object.keys(inputs).filter((k) => !FACT_ORDER.includes(k) && k !== 'band')]
  return keys
    .filter((key) => inputs[key] !== null && inputs[key] !== undefined)
    .map((key) => {
      const value = String(inputs[key])
      switch (key) {
        case 'hmi':
          return `HMI ${withUnit(value, unit)}`
        case 'target':
        case 'actual':
          return `${key} ${withUnit(value, unit)}`
        case 'pending_since':
          return `off target since ${formatManilaTime(Date.parse(value))}`
        case 'acknowledged_by':
          return `by ${value}`
        case 'note':
          return `“${value}”`
        case 'payload_clock': {
          // The machine's own stamps on the messages, kept as evidence: judging goes by our clock (invariant 13)
          const stamps = Object.entries(inputs[key] as Record<string, string>).map(
            ([topic, t]) => `${topic.split('/').pop()} ${formatManilaTime(Date.parse(t))}`,
          )
          return `machine's clock ${stamps.join(', ')}`
        }
        default:
          return `${key.replaceAll('_', ' ')} ${value}`
      }
    })
}

/** "45 s", "4 min 12 s", "1 h 5 min" */
export function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s} s`
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}

/** Seconds left until a timer monitor-core set, on the server's clock. */
export function secondsLeft(dueIso: string | null | undefined, serverNowMs: number): number | null {
  return dueIso ? Math.max(0, Math.ceil((Date.parse(dueIso) - serverNowMs) / 1000)) : null
}
