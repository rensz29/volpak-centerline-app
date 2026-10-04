import type { MaintenanceWindow } from '@/types/monitoringApi'
import { formatManilaShort, formatManilaTime } from '@/utils/manilaTime'

import { duration, type Tone } from './liveModel'

/**
 * Words and colours for monitoring control (ADR-0017). A window warns 30 and 5 minutes before its
 * planned end, and past it stays in force as overdue until an Administrator ends it (MNT-01).
 */

export const WARN_AT_MIN = [30, 5] as const

export function windowScope(w: Pick<MaintenanceWindow, 'scope' | 'zones'>): string {
  return w.scope === 'line' ? 'the whole line' : w.zones.map((z) => z.zoneName).join(', ')
}

/** Minutes until the planned end, on the server's clock; negative when overdue. */
export function minutesLeft(w: MaintenanceWindow, serverNowMs: number): number {
  return (Date.parse(w.plannedEnd) - serverNowMs) / 60000
}

export function windowTone(w: MaintenanceWindow, serverNowMs: number): Tone {
  if (w.status === 'scheduled' || w.status === 'ended' || w.status === 'cancelled') return 'nodata'
  const left = minutesLeft(w, serverNowMs)
  if (left <= WARN_AT_MIN[1]) return 'critical' // 5 min left, or overdue
  if (left <= WARN_AT_MIN[0]) return 'warning'
  return 'brand'
}

/** "ends 15:30 Manila, in 42 min", "overdue: planned to end 15:30, 12 min ago", "scheduled 17:00 to 18:00". */
export function windowTiming(w: MaintenanceWindow, serverNowMs: number): string {
  const end = formatManilaTime(Date.parse(w.plannedEnd)).slice(0, 5)
  if (w.status === 'ended' || w.status === 'cancelled') {
    return `${w.status} ${w.endedAt ? formatManilaShort(Date.parse(w.endedAt)) : ''}${w.endedBy ? ` by ${w.endedBy}` : ''}`
  }
  if (w.status === 'scheduled') {
    return `scheduled ${formatManilaShort(Date.parse(w.plannedStart))} to ${end} Manila`
  }
  const left = minutesLeft(w, serverNowMs)
  if (left < 0) return `overdue: planned to end ${end} Manila, ${duration(-left * 60000)} ago`
  return `planned to end ${end} Manila, in ${duration(left * 60000)}`
}
