import { Bell, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { TONE, duration, eventTitle, eventTone } from '@/components/live/liveModel'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useEventCounts } from '@/hooks/useEventCounts'
import { ROUTES } from '@/routes/navigation'
import { monitoringApi } from '@/services/monitoringApi'
import type { MonitorEvent } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'

const PREVIEW = 6
const ORDER = (e: MonitorEvent) => (e.kind === 'ACTUAL' ? (e.severity === 'CRITICAL' ? 0 : 1) : 2)

/** The open events at a glance: Criticals first; each opens its evidence on the Active Alarms page. */
export function NotificationBell() {
  const counts = useEventCounts()
  const [open, setOpen] = useState(false)
  const [events, setEvents] = useState<MonitorEvent[] | null>(null)
  const [now, setNow] = useState(0)
  const n = counts?.open ?? 0

  useEffect(() => {
    if (!open) return
    monitoringApi
      .events({ open: true, limit: 50 })
      .then((r) => {
        setEvents([...r.events].sort((a, b) => ORDER(a) - ORDER(b) || Date.parse(b.openedAt) - Date.parse(a.openedAt)))
        setNow(Date.now())
      })
      .catch(() => setEvents([]))
  }, [open])

  const summary = counts
    ? [counts.critical && `${counts.critical} Critical${counts.unacknowledgedCritical ? ` (${counts.unacknowledgedCritical} not acknowledged)` : ''}`,
       counts.warning && `${counts.warning} Warning${counts.warning === 1 ? '' : 's'}`,
       counts.hmi && `${counts.hmi} HMI mismatch${counts.hmi === 1 ? '' : 'es'}`].filter(Boolean).join(' · ')
    : ''

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className="text-nav-fg hover:bg-nav-hover focus-visible:ring-nav-accent relative grid size-9 place-items-center rounded-md transition-colors hover:text-white focus-visible:ring-2 focus-visible:outline-none"
        aria-label={`Open events: ${n}`}
      >
        <Bell className="size-4.5" aria-hidden />
        {n > 0 && (
          <span className={cn('ring-nav tnum absolute -top-0.5 -right-0.5 grid h-4.5 min-w-4.5 place-items-center rounded-full px-1 text-[10px] font-semibold text-white ring-2',
                              counts?.critical ? 'bg-critical-solid' : 'bg-warning-solid')}>
            {n > 99 ? '99+' : n}
          </span>
        )}
      </PopoverTrigger>

      <PopoverContent align="end" className="w-[380px] p-0">
        <div className="border-line border-b px-4 py-3">
          <p className="text-ink text-[13px] font-semibold">Open events</p>
          <p className="text-ink-soft text-[12px]">{n === 0 ? 'Nothing needs attention' : summary}</p>
        </div>
        {n > 0 && (
          <ul className="max-h-[320px] overflow-y-auto">
            {(events ?? []).slice(0, PREVIEW).map((e) => (
              <li key={e.id} className="border-line-soft border-b last:border-b-0">
                <Link to={`${ROUTES.activeAlarms}?event=${e.id}`} onClick={() => setOpen(false)}
                      className="hover:bg-surface-muted flex gap-2.5 px-4 py-2.5">
                  <span className={cn('w-1 shrink-0 rounded-full', TONE[eventTone(e)].rail)} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className={cn('text-[13px] font-semibold', TONE[eventTone(e)].text)}>{eventTitle(e)}</span>
                      <span className="text-ink-muted shrink-0 text-[11px]">open {duration(now - Date.parse(e.openedAt))}</span>
                    </span>
                    <span className="text-ink block truncate text-[12px]">
                      {e.parameterName} · {e.zoneName}
                      {e.acknowledgedAt ? ' · acknowledged' : ''}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <div className="border-line flex items-center justify-between border-t px-4 py-2 text-[12px]">
          <Link to={ROUTES.alarmHistory} onClick={() => setOpen(false)} className="text-ink-soft hover:text-ink">
            History
          </Link>
          <Link to={ROUTES.activeAlarms} onClick={() => setOpen(false)} className="text-brand inline-flex items-center gap-0.5 font-medium">
            All open events <ChevronRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  )
}
