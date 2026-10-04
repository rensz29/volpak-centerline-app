import { History } from 'lucide-react'
import { useEffect, useState } from 'react'

import { SectionCard } from '@/components/shared/SectionCard'
import { monitoringApi } from '@/services/monitoringApi'
import type { BriefChange, MonitorEvent } from '@/types/monitoringApi'
import { formatManilaShort } from '@/utils/manilaTime'

import { EVENT_STATE_LABEL, duration, eventTitle, withUnit } from './liveModel'

const EVERY_MS = 10_000

/** What closed recently, and the brief setpoint changes that never became events (HMI-05). */
export function RecentActivity({ onOpen }: { onOpen: (id: string) => void }) {
  const [events, setEvents] = useState<MonitorEvent[]>([])
  const [brief, setBrief] = useState<BriefChange[]>([])

  useEffect(() => {
    let timer: number | undefined
    const load = () => {
      Promise.all([monitoringApi.events({ open: false, limit: 15 }), monitoringApi.briefChanges(10)])
        .then(([e, b]) => {
          setEvents(e.events)
          setBrief(b.briefChanges)
        })
        .catch(() => undefined)
        .finally(() => {
          timer = window.setTimeout(load, EVERY_MS)
        })
    }
    load()
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <SectionCard title="Recently closed" description="The last 15 events that closed" icon={History} flush>
        {events.length === 0 ? (
          <p className="text-ink-soft px-5 py-4 text-[13px]">None yet.</p>
        ) : (
          <table className="w-full text-[13px]">
            <tbody>
              {events.map((e) => (
                <tr key={e.id} tabIndex={0} className="border-line-soft hover:bg-surface-muted focus-visible:bg-surface-muted cursor-pointer border-b focus-visible:outline-none"
                    onClick={() => onOpen(e.id)} onKeyDown={(k) => (k.key === 'Enter' || k.key === ' ') && (k.preventDefault(), onOpen(e.id))}>
                  <td className="text-ink-muted px-4 py-1.5 text-[12px] whitespace-nowrap">{formatManilaShort(Date.parse(e.openedAt))}</td>
                  <td className="px-2 py-1.5">{eventTitle(e)}</td>
                  <td className="px-2 py-1.5">{e.zoneName}</td>
                  <td className="text-ink-soft px-2 py-1.5 text-[12px]">
                    {EVENT_STATE_LABEL[e.state] ?? e.state}
                    {e.closedAt ? ` after ${duration(Date.parse(e.closedAt) - Date.parse(e.openedAt))}` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
      <SectionCard title="Brief changes" description="Back on target before the delay ended: recorded, never notified" icon={History} flush>
        {brief.length === 0 ? (
          <p className="text-ink-soft px-5 py-4 text-[13px]">None yet.</p>
        ) : (
          <table className="w-full text-[13px]">
            <tbody>
              {brief.map((b) => (
                <tr key={b.id} className="border-line-soft border-b">
                  <td className="text-ink-muted px-4 py-1.5 text-[12px] whitespace-nowrap">{formatManilaShort(Date.parse(b.startedAt))}</td>
                  <td className="px-2 py-1.5">{b.zoneName}</td>
                  <td className="text-ink-soft px-2 py-1.5 font-mono text-[12px]">
                    {withUnit(b.hmi, b.unit)} for {b.seconds} s
                  </td>
                  <td className="text-ink-muted px-2 py-1.5 text-[12px]">{b.mode === 'lightweight' ? 'lightweight' : 'full record'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
    </div>
  )
}
