import { BellRing, CheckCircle2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { EventSheet } from '@/components/live/EventSheet'
import { TONE, duration, eventTitle, eventTone, withUnit } from '@/components/live/liveModel'
import { EmptyState } from '@/components/shared/EmptyState'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import { monitoringApi } from '@/services/monitoringApi'
import type { MonitorEvent } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { formatManilaShort } from '@/utils/manilaTime'

const EVERY_MS = 5000
const ORDER = (e: MonitorEvent) => (e.kind === 'ACTUAL' ? (e.severity === 'CRITICAL' ? 0 : 1) : 2)
type Show = 'all' | 'critical' | 'warning' | 'hmi'
const SHOWS: { id: Show; label: string; keep: (e: MonitorEvent) => boolean }[] = [
  { id: 'all', label: 'All', keep: () => true },
  { id: 'critical', label: 'Critical', keep: (e) => e.kind === 'ACTUAL' && e.severity === 'CRITICAL' },
  { id: 'warning', label: 'Warning', keep: (e) => e.kind === 'ACTUAL' && e.severity === 'WARNING' },
  { id: 'hmi', label: 'HMI mismatch', keep: (e) => e.kind === 'HMI_MISMATCH' },
]

/** Active Alarms: every open event, Criticals first. Each opens its evidence; a Manager acknowledges a Critical there. */
export function OpenEventsPage() {
  const [params, setParams] = useSearchParams()
  const openId = params.get('event')
  const [events, setEvents] = useState<MonitorEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [show, setShow] = useState<Show>('all')
  const [now, setNow] = useState(0)

  const load = useCallback(() => {
    monitoringApi
      .events({ open: true, limit: 200 })
      .then((r) => {
        setEvents(r.events)
        setNow(Date.now())
        setError(null)
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [])

  useEffect(() => {
    load()
    const t = window.setInterval(load, EVERY_MS)
    return () => window.clearInterval(t)
  }, [load])

  const keep = SHOWS.find((s) => s.id === show)!.keep
  const rows = [...(events ?? [])].filter(keep).sort((a, b) => ORDER(a) - ORDER(b) || Date.parse(a.openedAt) - Date.parse(b.openedAt))

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Active Alarms"
        description="Every open event, as monitor-core judges them: Criticals first, then Warnings, then HMI mismatches. Each closes by itself when its value is back."
        breadcrumbs={[{ label: 'Alarms' }, { label: 'Active Alarms' }]}
      />
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
        {SHOWS.map((s) => (
          <Button key={s.id} type="button" size="sm" variant={show === s.id ? 'default' : 'outline'} onClick={() => setShow(s.id)}>
            {s.label}
            {events && <span className="tabular-nums opacity-70">{events.filter(s.keep).length}</span>}
          </Button>
        ))}
      </div>
      <SectionCard title="Open events" icon={BellRing} flush description={events ? `${rows.length} shown` : ' '}>
        {error ? (
          <EmptyState icon={BellRing} title="Can't load the open events" description={error} />
        ) : !events ? (
          <TableSkeleton rows={4} />
        ) : rows.length === 0 ? (
          <p className="text-ink-soft flex items-center gap-2 px-5 py-6 text-[13px]">
            <CheckCircle2 className="text-normal size-4" aria-hidden /> Nothing needs attention.
          </p>
        ) : (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-ink-muted border-line border-b text-left text-[11px] whitespace-nowrap uppercase">
                <th className="px-5 py-2 font-semibold">Event</th>
                <th className="px-3 py-2 font-semibold">Zone</th>
                <th className="px-3 py-2 font-semibold">Opened</th>
                <th className="px-3 py-2 font-semibold">Open for</th>
                <th className="px-3 py-2 font-semibold">At opening</th>
                <th className="px-3 py-2 font-semibold">SKU</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const tone = eventTone(e)
                return (
                  <tr key={e.id} tabIndex={0} onClick={() => setParams({ event: e.id })}
                      onKeyDown={(k) => (k.key === 'Enter' || k.key === ' ') && (k.preventDefault(), setParams({ event: e.id }))}
                      className="border-line-soft hover:bg-surface-muted focus-visible:bg-surface-muted cursor-pointer border-b focus-visible:outline-none">
                    <td className="px-5 py-2">
                      <span className="flex items-center gap-2">
                        <span className={cn('h-5 w-1 rounded-full', TONE[tone].rail)} aria-hidden />
                        <span className={cn('font-semibold', TONE[tone].text)}>{eventTitle(e)}</span>
                        {e.acknowledgedAt && <span className="text-ink-muted text-[12px]">acknowledged</span>}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-ink">{e.zoneName}</span>
                      <span className="text-ink-muted ml-2 text-[12px]">{e.parameterName}</span>
                    </td>
                    <td className="text-ink-soft px-3 py-2 whitespace-nowrap">{formatManilaShort(Date.parse(e.openedAt))}</td>
                    <td className="text-ink px-3 py-2 whitespace-nowrap tabular-nums">{duration(now - Date.parse(e.openedAt))}</td>
                    <td className="text-ink-soft px-3 py-2 font-mono text-[12px]">
                      {e.kind === 'HMI_MISMATCH'
                        ? `HMI ${withUnit(e.hmi, e.unit)}, target ${withUnit(e.target, e.unit)}`
                        : `actual ${withUnit(e.actual, e.unit)}, HMI ${withUnit(e.hmi, e.unit)}`}
                    </td>
                    <td className="text-ink-soft px-3 py-2">{e.sku}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </SectionCard>
      {openId && (
        <EventSheet key={openId} id={openId} onOpen={(id) => setParams({ event: id })}
                    onClose={() => {
                      setParams({})
                      load()
                    }} />
      )}
    </div>
  )
}
