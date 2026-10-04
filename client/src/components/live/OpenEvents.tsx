import { BellRing, CheckCircle2 } from 'lucide-react'

import { SectionCard } from '@/components/shared/SectionCard'
import type { MonitorEvent } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { formatManilaShort } from '@/utils/manilaTime'

import { TONE, duration, eventTitle, eventTone, withUnit } from './liveModel'

const ORDER = (e: MonitorEvent) => (e.kind === 'ACTUAL' ? (e.severity === 'CRITICAL' ? 0 : 1) : 2)

/** The open events: Criticals first, then Warnings, then HMI mismatches; each opens its details. */
export function OpenEvents({ events, now, onOpen }: { events: MonitorEvent[]; now: number; onOpen: (id: string) => void }) {
  const sorted = [...events].sort((a, b) => ORDER(a) - ORDER(b) || Date.parse(a.openedAt) - Date.parse(b.openedAt))
  return (
    <SectionCard title="Open events" description={events.length ? `${events.length} open` : 'None open'} icon={BellRing} flush>
      {sorted.length === 0 ? (
        <p className="text-ink-soft flex items-center gap-2 px-5 py-6 text-[13px]">
          <CheckCircle2 className="text-normal size-4" aria-hidden /> Nothing needs attention.
        </p>
      ) : (
        <ul className="divide-line-soft divide-y">
          {sorted.map((e) => {
            const tone = eventTone(e)
            return (
              <li key={e.id}>
                <button type="button" onClick={() => onOpen(e.id)} className="hover:bg-surface-muted flex w-full gap-3 px-4 py-2.5 text-left">
                  <span className={cn('w-1 shrink-0 rounded-full', TONE[tone].rail)} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-baseline justify-between gap-x-2">
                      <span className={cn('text-[13px] font-semibold', TONE[tone].text)}>{eventTitle(e)}</span>
                      <span className="text-ink-muted text-[11px]">
                        {formatManilaShort(Date.parse(e.openedAt))} · open {duration(now - Date.parse(e.openedAt))}
                      </span>
                    </span>
                    <span className="text-ink block text-[13px]">
                      {e.parameterName} · {e.zoneName}
                    </span>
                    <span className="text-ink-soft block text-[12px]">
                      {e.kind === 'HMI_MISMATCH'
                        ? `Opened at HMI ${withUnit(e.hmi, e.unit)} against target ${withUnit(e.target, e.unit)}`
                        : `Opened at actual ${withUnit(e.actual, e.unit)} with the HMI at ${withUnit(e.hmi, e.unit)}`}
                      {e.acknowledgedAt ? ' · acknowledged' : ''}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </SectionCard>
  )
}
