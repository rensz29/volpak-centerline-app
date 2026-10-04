import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Info,
  MinusCircle,
  type LucideIcon,
} from 'lucide-react'

import type { AlarmSeverity, AlarmStatus, ParameterStatus } from '@/types'

/**
 * The single source of truth for process status.
 *
 * Status is always derived, never stored on a record. That way editing a
 * setpoint in the configuration modal immediately and consistently recolours
 * the table row, its badge, the summary cards and the alarm counts — there is
 * no denormalised copy that can fall out of step.
 */
export function deriveStatus(
  actual: number | null,
  target: number,
  warningTolerancePct: number,
  criticalTolerancePct: number,
): ParameterStatus {
  if (actual === null || Number.isNaN(actual)) return 'no-data'
  if (target === 0) return actual === 0 ? 'normal' : 'critical'

  const deviationPct = Math.abs(((actual - target) / target) * 100)
  if (deviationPct > criticalTolerancePct) return 'critical'
  if (deviationPct > warningTolerancePct) return 'warning'
  return 'normal'
}

export function calcDeviation(actual: number | null, target: number): number | null {
  return actual === null ? null : actual - target
}

export function calcDeviationPct(actual: number | null, target: number): number | null {
  if (actual === null || target === 0) return null
  return ((actual - target) / target) * 100
}

export interface StatusMeta {
  label: string
  icon: LucideIcon
  /** Solid fill for dots and chart markers. */
  dot: string
  /** Foreground + surface + border triple used by badges and rails. */
  badge: string
  text: string
  surface: string
  border: string
  /** 3px status rail used on cards and table rows. */
  rail: string
  description: string
}

export const STATUS_META: Record<ParameterStatus, StatusMeta> = {
  normal: {
    label: 'Normal',
    icon: CheckCircle2,
    dot: 'bg-normal-solid',
    badge: 'border-normal-border bg-normal-surface text-normal',
    text: 'text-normal',
    surface: 'bg-normal-surface',
    border: 'border-normal-border',
    rail: 'bg-normal-solid',
    description: 'Within tolerance of the target setpoint',
  },
  warning: {
    label: 'Warning',
    icon: AlertTriangle,
    dot: 'bg-warning-solid',
    badge: 'border-warning-border bg-warning-surface text-warning',
    text: 'text-warning',
    surface: 'bg-warning-surface',
    border: 'border-warning-border',
    rail: 'bg-warning-solid',
    description: 'Drifting beyond the warning tolerance',
  },
  critical: {
    label: 'Critical',
    icon: AlertOctagon,
    dot: 'bg-critical-solid',
    badge: 'border-critical-border bg-critical-surface text-critical',
    text: 'text-critical',
    surface: 'bg-critical-surface',
    border: 'border-critical-border',
    rail: 'bg-critical-solid',
    description: 'Outside the critical tolerance band',
  },
  'no-data': {
    label: 'No Data',
    icon: MinusCircle,
    dot: 'bg-nodata-solid',
    badge: 'border-nodata-border bg-nodata-surface text-nodata',
    text: 'text-nodata',
    surface: 'bg-nodata-surface',
    border: 'border-nodata-border',
    rail: 'bg-nodata-solid',
    description: 'No sensor reading received',
  },
}

export const SEVERITY_META: Record<
  AlarmSeverity,
  { label: string; icon: LucideIcon; badge: string; rail: string; dot: string }
> = {
  critical: {
    label: 'Critical',
    icon: AlertOctagon,
    badge: 'border-critical-border bg-critical-surface text-critical',
    rail: 'bg-critical-solid',
    dot: 'bg-critical-solid',
  },
  warning: {
    label: 'Warning',
    icon: AlertTriangle,
    badge: 'border-warning-border bg-warning-surface text-warning',
    rail: 'bg-warning-solid',
    dot: 'bg-warning-solid',
  },
  info: {
    label: 'Info',
    icon: Info,
    badge: 'border-brand/20 bg-brand-surface text-brand',
    rail: 'bg-brand',
    dot: 'bg-brand',
  },
}

export const ALARM_STATUS_META: Record<AlarmStatus, { label: string; badge: string }> = {
  active: {
    label: 'Active',
    badge: 'border-critical-border bg-critical-surface text-critical',
  },
  acknowledged: {
    label: 'Acknowledged',
    badge: 'border-warning-border bg-warning-surface text-warning',
  },
  resolved: {
    label: 'Resolved',
    badge: 'border-normal-border bg-normal-surface text-normal',
  },
}

/** Counts of each status across a set of rows, for the summary cards. */
export function countByStatus(
  statuses: readonly ParameterStatus[],
): Record<ParameterStatus, number> {
  const counts: Record<ParameterStatus, number> = {
    normal: 0,
    warning: 0,
    critical: 0,
    'no-data': 0,
  }
  for (const status of statuses) counts[status] += 1
  return counts
}
