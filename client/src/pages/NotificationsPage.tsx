import { Loader2, Mail, MessageSquare, Send, SendHorizontal } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { DELIVERY_LABEL, DELIVERY_TONE, OUTCOME_LABEL } from '@/components/notifications/notificationModel'
import { NotificationSheet } from '@/components/notifications/NotificationSheet'
import { FormField } from '@/components/setup/FormParts'
import { ProblemLine } from '@/components/setup/VersionDialogs'
import { asProblem } from '@/components/setup/versionUtils'
import { EmptyState } from '@/components/shared/EmptyState'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useRoles } from '@/hooks/useAuth'
import type { ApiProblem } from '@/services/http'
import { notificationsApi } from '@/services/notificationsApi'
import type { Channel, LogState, NotificationSummary, NotificationsList } from '@/types/notificationsApi'
import { cn } from '@/utils/cn'
import { formatManilaShort } from '@/utils/manilaTime'

const EVERY_MS = 10_000
const FILTERS: { id: LogState; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'waiting', label: 'On their way' },
  { id: 'failed', label: 'Failed' },
  { id: 'unrouted', label: 'Not sent' },
  { id: 'test', label: 'TEST' },
]

/** An Administrator sends a TEST - NO PRODUCTION EVENT message to one recipient (NOT-07). */
function TestDialog({ onClose, onSent }: { onClose: () => void; onSent: (id: string) => void }) {
  const [channel, setChannel] = useState<Channel>('email')
  const [target, setTarget] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  const send = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const n = await notificationsApi.sendTest(channel, target, note)
      toast.success('TEST message queued', { description: 'The notifier sends it within seconds; open it to follow the delivery.' })
      onSent(n.id)
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Send a TEST message</DialogTitle>
          <DialogDescription>
            It says “TEST - NO PRODUCTION EVENT” and goes to the one recipient you name, outside the routing: a way to try an address
            or the Teams flow before the routing uses it. It's kept in the change history.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <div className="grid grid-cols-[140px_1fr] gap-3">
            <FormField label="Channel">
              <Select value={channel} onValueChange={(v) => setChannel(v as Channel)}>
                <SelectTrigger size="sm" aria-label="Channel">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="email">Email</SelectItem>
                  <SelectItem value="teams">Teams</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <FormField label={channel === 'email' ? 'Email address' : 'Teams channel or chat'} error={problem?.forField('target')}>
              <Input value={target} onChange={(e) => setTarget(e.target.value)}
                     placeholder={channel === 'email' ? 'shift.lead@plant.local' : 'Centerline alerts'} className="h-8 text-[13px]"
                     aria-label="Recipient" />
            </FormField>
          </div>
          <FormField label="Note" hint="Optional; it's in the message and the change history">
            <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Checking the relay from IT"
                      className="text-[13px]" aria-label="Note" />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy || !target.trim()} onClick={() => void send()}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <SendHorizontal className="size-4" aria-hidden />} Send the TEST
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Deliveries({ n }: { n: NotificationSummary }) {
  const shown = n.deliveries.filter((d) => d.status !== 'REDRIVEN')
  if (shown.length === 0) return <span className="text-ink-muted text-[12px]">{OUTCOME_LABEL[n.outcome]}</span>
  return (
    <span className="flex flex-col gap-1">
      {shown.map((d) => (
        <span key={d.id} className="flex items-center gap-1.5 text-[12px]">
          {d.channel === 'teams' ? <MessageSquare className="text-ink-muted size-3.5" aria-label="Teams" /> : <Mail className="text-ink-muted size-3.5" aria-label="Email" />}
          <span className="text-ink-soft max-w-[220px] truncate">{d.target}</span>
          <Badge variant={DELIVERY_TONE[d.status]}>{DELIVERY_LABEL[d.status]}</Badge>
        </span>
      ))}
    </span>
  )
}

/**
 * Notifications (ADR-0023): every message Centerline sent or meant to send, how it was routed,
 * each delivery to Teams and email and every attempt. Managers and Administrators read it; an
 * Administrator sends TEST messages (NOT-07) and re-drives a delivery that failed for good (NOT-05).
 */
export function NotificationsPage() {
  const { isAdministrator } = useRoles()
  const [params, setParams] = useSearchParams()
  const openId = params.get('id')
  const [state, setState] = useState<LogState>('all')
  const [list, setList] = useState<NotificationsList | null>(null)
  const [older, setOlder] = useState<NotificationSummary[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)

  const load = useCallback(() => {
    notificationsApi
      .list(state)
      .then((r) => {
        setList(r)
        setError(null)
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [state])

  useEffect(() => {
    load()
    const t = window.setInterval(load, EVERY_MS)
    return () => window.clearInterval(t)
  }, [load])

  const choose = (s: LogState) => {
    setState(s)
    setList(null)
    setOlder([])
    setNext(null)
  }
  const more = () => {
    const cursor = next ?? list?.next
    if (!cursor) return
    setBusy(true)
    notificationsApi
      .list(state, cursor)
      .then((r) => {
        setOlder((o) => [...o, ...r.notifications])
        setNext(r.next)
      })
      .catch((caught: unknown) => toast.error(caught instanceof Error ? caught.message : String(caught)))
      .finally(() => setBusy(false))
  }

  const rows = list ? [...list.notifications, ...older.filter((o) => !list.notifications.some((n) => n.id === o.id))] : null
  const hasMore = older.length > 0 ? next !== null : Boolean(list?.next)

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Notifications"
        description="Every message Centerline sent or meant to send: how it was routed, each delivery to Teams and email, and every attempt."
        breadcrumbs={[{ label: 'Alarms' }, { label: 'Notifications' }]}
        actions={
          isAdministrator ? (
            <Button type="button" size="sm" onClick={() => setTesting(true)}>
              <SendHorizontal className="size-4" aria-hidden /> Send a TEST message
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
        {FILTERS.map((f) => {
          const count = f.id === 'waiting' ? list?.counts.waiting : f.id === 'failed' ? list?.counts.failed : undefined
          return (
            <Button key={f.id} type="button" size="sm" variant={state === f.id ? 'default' : 'outline'} onClick={() => choose(f.id)}
                    aria-pressed={state === f.id}>
              {f.label}
              {count ? (
                <span className={cn('rounded px-1.5 text-[11px] font-semibold', f.id === 'failed' ? 'bg-critical text-white' : 'bg-surface-muted text-ink')}>
                  {count}
                </span>
              ) : null}
            </Button>
          )
        })}
      </div>

      <SectionCard title="Messages" icon={Send} flush description={rows ? `${rows.length}${hasMore ? '+' : ''} shown, newest first` : ' '}>
        {error ? (
          <EmptyState icon={Send} title="Can't load the notifications" description={error} />
        ) : !rows ? (
          <TableSkeleton rows={6} />
        ) : rows.length === 0 ? (
          <p className="text-ink-soft px-5 py-6 text-[13px]">
            {state === 'all' ? 'No messages yet. They appear here as monitor-core raises them.' : 'None match.'}
          </p>
        ) : (
          <>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-ink-muted border-line border-b text-left text-[11px] whitespace-nowrap uppercase">
                  <th className="px-5 py-2 font-semibold">Created</th>
                  <th className="px-3 py-2 font-semibold">Message</th>
                  <th className="px-3 py-2 font-semibold">Deliveries</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((n) => (
                  <tr key={n.id} tabIndex={0} onClick={() => setParams({ id: n.id })}
                      onKeyDown={(k) => (k.key === 'Enter' || k.key === ' ') && (k.preventDefault(), setParams({ id: n.id }))}
                      className="border-line-soft hover:bg-surface-muted focus-visible:bg-surface-muted cursor-pointer border-b align-top focus-visible:outline-none">
                    <td className="text-ink-soft px-5 py-2 whitespace-nowrap">{formatManilaShort(Date.parse(n.createdAt))}</td>
                    <td className="px-3 py-2">
                      <span className="text-ink block">{n.subject}</span>
                      <span className="text-ink-muted text-[12px]">{n.typeLabel}</span>
                    </td>
                    <td className="px-3 py-2">
                      <Deliveries n={n} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hasMore && (
              <div className="border-line border-t px-5 py-3">
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={more}>
                  {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Show older
                </Button>
              </div>
            )}
          </>
        )}
      </SectionCard>

      {openId && <NotificationSheet key={openId} id={openId} onClose={() => setParams({})} onChanged={load} />}
      {testing && (
        <TestDialog
          onClose={() => setTesting(false)}
          onSent={(id) => {
            setTesting(false)
            load()
            setParams({ id })
          }}
        />
      )}
    </div>
  )
}
