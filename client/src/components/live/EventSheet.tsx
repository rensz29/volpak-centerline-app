import { CheckCheck, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { STATUS_LABEL as REQUEST_LABEL, STATUS_TONE as REQUEST_TONE } from '@/components/workflow/workflowModel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { useRoles } from '@/hooks/useAuth'
import { monitoringApi } from '@/services/monitoringApi'
import type { EventDetail } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { formatManilaFull } from '@/utils/manilaTime'

import { DELIVERY_STATE, EVENT_STATE_LABEL, NOTIFICATION_LABEL, STATE_TONE, TONE, eventTitle, transitionFacts, withUnit } from './liveModel'

type Rule = { target?: string; limits?: Record<string, string>; delays_s?: Record<string, number>; brief_change_mode?: string }

const APPLY_WAIT_MS = 2500 // monitor-core reads new acknowledgments every 2 s

/** A Manager acknowledges an open Critical, which stops its repeats (ACT-04). */
function Acknowledge({ id, onDone }: { id: string; onDone: () => void }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    try {
      await monitoringApi.acknowledge(id, note)
      toast.success('Acknowledged', { description: 'The Critical repeats stop once monitor-core applies it, within 2 s.' })
      onDone()
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : String(caught))
      setBusy(false)
    }
  }
  return (
    <div className="border-critical-border bg-critical-surface/40 flex flex-col gap-2 rounded-lg border p-3">
      <p className="text-ink font-medium">Acknowledge this Critical</p>
      <p className="text-ink-soft text-[12px]">
        Stops its repeats to Management. It stays open until the actual is back to Normal; if it goes Critical again after a
        downgrade, that needs a new acknowledgment.
      </p>
      <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional), e.g. what's being done" />
      <Button type="button" size="sm" className="self-end" disabled={busy} onClick={() => void submit()}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <CheckCheck className="size-4" aria-hidden />} Acknowledge
      </Button>
    </div>
  )
}

/** One event's evidence: every change of state with its inputs, the notifications, and the rule it's judged by. */
export function EventSheet({ id, onClose, onOpen }: { id: string; onClose: () => void; onOpen: (id: string) => void }) {
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { isManager } = useRoles()

  const load = useCallback(() => {
    monitoringApi
      .event(id)
      .then(setEvent)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [id])
  useEffect(load, [load])

  const rule = (event?.rule ?? {}) as Rule
  const at = (iso: string | null) => (iso ? `${formatManilaFull(Date.parse(iso))} Manila` : '—')

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-[560px]">
        <SheetHeader>
          <SheetTitle>{event ? `${eventTitle(event)} · ${event.zoneName}` : 'Event'}</SheetTitle>
          <SheetDescription>
            {event ? `${event.parameterName} · SKU ${event.sku} · ${EVENT_STATE_LABEL[event.state] ?? event.state}${event.open ? '' : ' (closed)'}` : ' '}
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="flex flex-col gap-4 px-5 py-4 text-[13px]">
          {error && <p className="text-critical">{error}</p>}
          {!event && !error && <Loader2 className="text-ink-muted size-5 animate-spin" aria-label="Loading" />}
          {event && (
            <>
              <dl className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-1">
                <dt className="text-ink-muted">Opened</dt>
                <dd>{at(event.openedAt)}</dd>
                <dt className="text-ink-muted">Closed</dt>
                <dd>{at(event.closedAt)}</dd>
                <dt className="text-ink-muted">At opening</dt>
                <dd>
                  {event.kind === 'HMI_MISMATCH'
                    ? `HMI ${withUnit(event.hmi, event.unit)}, target ${withUnit(event.target, event.unit)}`
                    : `Actual ${withUnit(event.actual, event.unit)}, HMI ${withUnit(event.hmi, event.unit)}`}
                </dd>
                <dt className="text-ink-muted">Judged under</dt>
                <dd>
                  Rules v{event.versions.rules} · Mapping v{event.versions.mapping} · register {event.versions.register}
                </dd>
                <dt className="text-ink-muted">Target</dt>
                <dd>{withUnit(rule.target ?? null, event.unit)}</dd>
                {rule.limits && (
                  <>
                    <dt className="text-ink-muted">Limits</dt>
                    <dd>
                      Warning −{rule.limits.warn_low}/+{rule.limits.warn_high}, Critical −{rule.limits.crit_low}/+{rule.limits.crit_high}
                      {event.unit ? ` ${event.unit}` : ''} around the HMI setpoint
                    </dd>
                  </>
                )}
                {rule.delays_s && (
                  <>
                    <dt className="text-ink-muted">Delays</dt>
                    <dd>
                      mismatch {rule.delays_s.mismatch} s · Warning {rule.delays_s.warning} s · Critical {rule.delays_s.critical} s · recovery{' '}
                      {rule.delays_s.recovery} s
                    </dd>
                  </>
                )}
                {event.supersedes && (
                  <>
                    <dt className="text-ink-muted">Supersedes</dt>
                    <dd>
                      <button type="button" className="text-brand underline-offset-2 hover:underline" onClick={() => onOpen(event.supersedes!)}>
                        the earlier event
                      </button>
                    </dd>
                  </>
                )}
                {event.acknowledgments.length > 0 && (
                  <>
                    <dt className="text-ink-muted">Acknowledged</dt>
                    <dd className="flex flex-col gap-0.5">
                      {event.acknowledgments.map((a) => (
                        <span key={a.at}>
                          {at(a.at)} by {a.by ?? 'unknown'}
                          {event.acknowledgments.length > 1 && a.criticalPeriod ? ` (Critical period ${a.criticalPeriod})` : ''}
                          {a.note ? ` · “${a.note}”` : ''}
                        </span>
                      ))}
                      {event.open && event.kind === 'ACTUAL' && event.severity === 'CRITICAL' && !event.acknowledgedAt &&
                        !event.acknowledgeable && (
                          <span className="text-ink-muted text-[12px]">Waiting for monitor-core to apply it (within 2 s while it runs)</span>
                        )}
                    </dd>
                  </>
                )}
              </dl>

              {isManager && event.acknowledgeable && <Acknowledge id={event.id} onDone={() => window.setTimeout(load, APPLY_WAIT_MS)} />}

              <div>
                <p className="micro-label mb-1.5">What happened</p>
                <ol className="border-line relative ml-1.5 flex flex-col gap-2.5 border-l pl-4">
                  {event.transitions.map((t) => (
                    <li key={t.seq} className="relative">
                      <span className={cn('absolute top-1.5 -left-[21px] size-2 rounded-full', TONE[STATE_TONE[t.state] ?? 'nodata'].dot)} aria-hidden />
                      <p className="text-ink font-medium">{EVENT_STATE_LABEL[t.state] ?? t.state}</p>
                      <p className="text-ink-muted text-[12px]">
                        {[at(t.at), ...transitionFacts(t.inputs, event.unit)].join(' · ')}
                      </p>
                    </li>
                  ))}
                </ol>
              </div>

              {event.kind === 'HMI_MISMATCH' && (
                <div>
                  <p className="micro-label mb-1.5">Reasons</p>
                  {event.requests.length === 0 ? (
                    <p className="text-ink-soft">None asked yet.</p>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {event.requests.map((r) => (
                        <li key={r.id} className="border-line-soft border-l-2 pl-3">
                          <p className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-ink">{r.shift.label}</span>
                            <Badge variant={REQUEST_TONE[r.status]}>{REQUEST_LABEL[r.status]}</Badge>
                          </p>
                          {r.entries.map((x, i) => (
                            <p key={i} className="text-ink-soft mt-1 text-[12px]">
                              <span className="text-ink-muted">{x.kind === 'answer' ? x.question : x.kind} · {x.by}:</span> {x.body || '✓'}
                            </p>
                          ))}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div>
                <p className="micro-label mb-1.5">Notifications</p>
                {event.notifications.length === 0 ? (
                  <p className="text-ink-soft">None: Warnings can be set to stay quiet (ACT-03).</p>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {event.notifications.map((n, i) => (
                      <li key={`${n.kind}-${i}`} className="flex justify-between gap-3">
                        <span>{NOTIFICATION_LABEL[n.kind] ?? n.kind}</span>
                        <span className="text-ink-muted text-[12px]">
                          {at(n.at)} · {DELIVERY_STATE[n.status] ?? n.status}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-ink-muted mt-1 text-[11px]">Each message's deliveries to Teams and email, and every attempt, are on the Notifications page.</p>
              </div>
            </>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  )
}
