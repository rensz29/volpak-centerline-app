import { HardDrive } from 'lucide-react'

import { useEventCounts } from '@/hooks/useEventCounts'
import { cn } from '@/utils/cn'
import { formatManilaTime } from '@/utils/manilaTime'

const CLEANUP_WAIT_MS = 10 * 60_000 // monitor-core's: degraded mode begins this long after 90 % (storage.py)

/**
 * The disk under the journal and the database, on every page (RES-02, O-12, ADR-0036): from 80 % a warning; at
 * 90 % the cleanup and when degraded mode would begin; in protected degraded mode what's paused and what isn't.
 * It comes with the event counts every page already asks for.
 */
export function StorageBanner() {
  const storage = useEventCounts()?.storage
  if (!storage || storage.state === 'normal' || storage.usedPct === null) return null
  const pct = `${Math.round(storage.usedPct)} %`
  const { cleanup, degradedUntilBelow } = storage.limits
  const message =
    storage.state === 'warning'
      ? `Storage is ${pct} full. An Administrator should free space before it reaches ${cleanup} %.`
      : storage.state === 'cleanup'
        ? `Storage is ${pct} full: the eligible cleanup is running. Unless it drops under ${cleanup} %, protected degraded mode begins at ${
            storage.since ? formatManilaTime(Date.parse(storage.since) + CLEANUP_WAIT_MS).slice(0, 5) : 'once the cleanup has had 10 min'
          } Manila.`
        : `Protected degraded mode: storage is ${pct} full. Monitoring, events, reasons, notifications and backups carry on; new uploads, brief-change records and the Analytics query log are paused until it's under ${degradedUntilBelow} %.`
  return (
    <div
      role="status"
      className={cn(
        'sticky top-14 z-20 flex items-center justify-center gap-2 px-4 py-2 text-center text-[13px] font-medium text-white',
        storage.state === 'degraded' ? 'bg-critical' : 'bg-warning',
      )}
    >
      <HardDrive className="size-4 shrink-0" aria-hidden />
      {message}
    </div>
  )
}
