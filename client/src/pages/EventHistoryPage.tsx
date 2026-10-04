import { Download, History, Loader2, Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { EventSheet } from '@/components/live/EventSheet'
import { EVENT_STATE_LABEL, duration, eventTitle } from '@/components/live/liveModel'
import { FormField } from '@/components/setup/FormParts'
import { EmptyState } from '@/components/shared/EmptyState'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useRoles } from '@/hooks/useAuth'
import { monitoringApi } from '@/services/monitoringApi'
import type { EventFilters, LiveParameter, MonitorEvent } from '@/types/monitoringApi'
import { formatManilaShort, fromManilaInput } from '@/utils/manilaTime'

const PAGE = 50
const KINDS: Record<string, { label: string; filters: EventFilters }> = {
  all: { label: 'Every kind', filters: {} },
  hmi: { label: 'HMI mismatch', filters: { kind: 'HMI_MISMATCH' } },
  actual: { label: 'Actual, any severity', filters: { kind: 'ACTUAL' } },
  critical: { label: 'Actual that reached Critical', filters: { kind: 'ACTUAL', reached: 'CRITICAL' } },
}

const iso = (manila: string) => {
  const ms = manila ? fromManilaInput(manila) : null
  return ms === null ? undefined : new Date(ms).toISOString()
}

/** Alarm History: every closed event, newest first, with filters; Managers and Administrators export it (EXP-01). */
export function EventHistoryPage() {
  const { isPrivileged } = useRoles()
  const [params, setParams] = useSearchParams()
  const openId = params.get('event')
  const [kind, setKind] = useState('all')
  const [zone, setZone] = useState('all')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [applied, setApplied] = useState<EventFilters>({ open: false })
  const [events, setEvents] = useState<MonitorEvent[] | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [parameters, setParameters] = useState<LiveParameter[]>([])

  // Busy is set by the buttons; the first load shows a skeleton instead
  const load = useCallback((filters: EventFilters, before?: string) => {
    monitoringApi
      .events({ ...filters, limit: PAGE, before })
      .then((r) => {
        setEvents((old) => (before ? [...(old ?? []), ...r.events] : r.events))
        setNext(r.next)
        setError(null)
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
      .finally(() => setBusy(false))
  }, [])

  useEffect(() => {
    load({ open: false })
    monitoringApi
      .live()
      .then((v) => setParameters(v.parameters))
      .catch(() => undefined)
  }, [load])

  const apply = () => {
    const filters: EventFilters = { open: false, ...KINDS[kind]!.filters, channel: zone === 'all' ? undefined : zone,
                                    since: iso(since), until: iso(until) }
    setApplied(filters)
    setBusy(true)
    load(filters)
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Alarm History"
        description="Every event that closed, newest first, with how it ended. Open one for its evidence: the rule, each change of state, the notifications."
        breadcrumbs={[{ label: 'Alarms' }, { label: 'Alarm History' }]}
        actions={
          isPrivileged ? (
            <Button type="button" variant="outline" size="sm" asChild>
              <a href={monitoringApi.exportUrl(applied)} download>
                <Download className="size-4" aria-hidden /> Export CSV
              </a>
            </Button>
          ) : undefined
        }
      />

      <SectionCard title="Filters" icon={Search} bodyClassName="px-5 py-4">
        <form className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 xl:grid-cols-5"
              onSubmit={(e) => {
                e.preventDefault()
                apply()
              }}>
          <FormField label="Kind">
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger size="sm" aria-label="Kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(KINDS).map(([k, v]) => (
                  <SelectItem key={k} value={k}>
                    {v.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Zone">
            <Select value={zone} onValueChange={setZone}>
              <SelectTrigger size="sm" aria-label="Zone">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Every zone</SelectItem>
                {parameters.flatMap((p) =>
                  p.zones.map((z) => (
                    <SelectItem key={z.channel} value={z.channel}>
                      {p.name} · {z.name}
                    </SelectItem>
                  )),
                )}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Opened from (Manila)">
            <Input type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} />
          </FormField>
          <FormField label="Until (Manila)">
            <Input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
          </FormField>
          <Button type="submit" size="sm" disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Search className="size-4" aria-hidden />} Show
          </Button>
        </form>
      </SectionCard>

      <SectionCard title="Closed events" icon={History} flush description={events ? `${events.length}${next ? '+' : ''} shown` : ' '}>
        {error ? (
          <EmptyState icon={History} title="Can't load the history" description={error} />
        ) : !events ? (
          <TableSkeleton rows={6} />
        ) : events.length === 0 ? (
          <p className="text-ink-soft px-5 py-6 text-[13px]">No closed events match.</p>
        ) : (
          <>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-ink-muted border-line border-b text-left text-[11px] whitespace-nowrap uppercase">
                  <th className="px-5 py-2 font-semibold">Opened</th>
                  <th className="px-3 py-2 font-semibold">Event</th>
                  <th className="px-3 py-2 font-semibold">Zone</th>
                  <th className="px-3 py-2 font-semibold">Lasted</th>
                  <th className="px-3 py-2 font-semibold">How it ended</th>
                  <th className="px-3 py-2 font-semibold">SKU</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} tabIndex={0} onClick={() => setParams({ event: e.id })}
                      onKeyDown={(k) => (k.key === 'Enter' || k.key === ' ') && (k.preventDefault(), setParams({ event: e.id }))}
                      className="border-line-soft hover:bg-surface-muted focus-visible:bg-surface-muted cursor-pointer border-b focus-visible:outline-none">
                    <td className="text-ink-soft px-5 py-2 whitespace-nowrap">{formatManilaShort(Date.parse(e.openedAt))}</td>
                    <td className="text-ink px-3 py-2">{eventTitle(e)}</td>
                    <td className="px-3 py-2">
                      <span className="text-ink">{e.zoneName}</span>
                      <span className="text-ink-muted ml-2 text-[12px]">{e.parameterName}</span>
                    </td>
                    <td className="text-ink-soft px-3 py-2 whitespace-nowrap tabular-nums">
                      {e.closedAt ? duration(Date.parse(e.closedAt) - Date.parse(e.openedAt)) : '—'}
                    </td>
                    <td className="text-ink-soft px-3 py-2">{EVENT_STATE_LABEL[e.state] ?? e.state}</td>
                    <td className="text-ink-soft px-3 py-2">{e.sku}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {next && (
              <div className="border-line border-t px-5 py-3">
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => {
                  setBusy(true)
                  load(applied, next)
                }}>
                  {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Show older
                </Button>
              </div>
            )}
          </>
        )}
      </SectionCard>
      {openId && <EventSheet key={openId} id={openId} onOpen={(id) => setParams({ event: id })} onClose={() => setParams({})} />}
    </div>
  )
}
