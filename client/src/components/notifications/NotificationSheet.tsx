import { ExternalLink, Loader2, Mail, MessageSquare, RotateCcw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { ReasonDialog } from '@/components/setup/VersionDialogs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useRoles } from '@/hooks/useAuth'
import { notificationsApi } from '@/services/notificationsApi'
import type { DeliveryDetail, NotificationDetail } from '@/types/notificationsApi'
import { formatManilaFull } from '@/utils/manilaTime'

import { ATTEMPT_LABEL, DELIVERY_HINT, DELIVERY_LABEL, DELIVERY_TONE, OUTCOME_LABEL } from './notificationModel'

const at = (iso: string | null) => (iso ? `${formatManilaFull(Date.parse(iso))} Manila` : '—')

function Delivery({ d, canRedrive, onRedrive }: { d: DeliveryDetail; canRedrive: boolean; onRedrive: () => void }) {
  const [showSent, setShowSent] = useState(false)
  const Icon = d.channel === 'teams' ? MessageSquare : Mail
  return (
    <li className="border-line flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-medium">
          <Icon className="text-ink-muted size-4" aria-hidden /> {d.channel === 'teams' ? 'Teams' : 'Email'} · {d.target}
        </span>
        <Badge variant={DELIVERY_TONE[d.status]} title={DELIVERY_HINT[d.status]}>
          {DELIVERY_LABEL[d.status]}
        </Badge>
      </div>
      <p className="text-ink-soft text-[12px]">{DELIVERY_HINT[d.status]}</p>
      <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-0.5 text-[12px]">
        {d.rule && (
          <>
            <dt className="text-ink-muted">Rule</dt>
            <dd>{d.rule}</dd>
          </>
        )}
        <dt className="text-ink-muted">Attempts</dt>
        <dd>{d.attempts}</dd>
        {d.nextAttemptAt && d.status === 'RETRYING' && (
          <>
            <dt className="text-ink-muted">Next attempt</dt>
            <dd>{at(d.nextAttemptAt)}</dd>
          </>
        )}
        {d.finishedAt && (
          <>
            <dt className="text-ink-muted">Finished</dt>
            <dd>{at(d.finishedAt)}</dd>
          </>
        )}
        {d.lastError && (
          <>
            <dt className="text-ink-muted">Last error</dt>
            <dd className="text-critical font-mono">{d.lastError}</dd>
          </>
        )}
        {d.redriveOf && (
          <>
            <dt className="text-ink-muted">Re-driven by</dt>
            <dd>
              {d.redrivenBy}: “{d.redriveReason}”
            </dd>
          </>
        )}
        <dt className="text-ink-muted">{d.channel === 'email' ? 'Message-ID' : 'Dedup key'}</dt>
        <dd className="font-mono break-all">{d.channel === 'email' ? d.messageId : d.dedupKey}</dd>
      </dl>
      {d.attemptLog.length > 0 && (
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-ink-muted text-left text-[11px] uppercase">
              <th className="py-1 pr-2 font-semibold">#</th>
              <th className="px-2 py-1 font-semibold">When</th>
              <th className="px-2 py-1 font-semibold">Outcome</th>
              <th className="px-2 py-1 font-semibold">What it said</th>
            </tr>
          </thead>
          <tbody>
            {d.attemptLog.map((a) => (
              <tr key={a.attempt} className="border-line-soft border-t align-top">
                <td className="py-1 pr-2">{a.attempt}</td>
                <td className="text-ink-soft px-2 py-1 whitespace-nowrap">{formatManilaFull(Date.parse(a.startedAt))}</td>
                <td className="px-2 py-1">{ATTEMPT_LABEL[a.outcome]}</td>
                <td className="text-ink-soft px-2 py-1 font-mono break-all">{a.response}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={() => setShowSent((s) => !s)}>
          {showSent ? 'Hide what was sent' : 'What was sent'}
        </Button>
        {canRedrive && d.status === 'PERMANENT_FAILURE' && (
          <Button type="button" variant="outline" size="sm" onClick={onRedrive}>
            <RotateCcw className="size-3.5" aria-hidden /> Re-drive
          </Button>
        )}
      </div>
      {showSent && (
        <div className="border-line bg-surface-muted rounded-md border p-3 text-[12px]">
          <p className="text-ink font-medium">{d.content.subject}</p>
          {d.channel === 'email' && d.content.body ? (
            <pre className="text-ink mt-1 font-sans whitespace-pre-wrap">{d.content.body}</pre>
          ) : (
            <>
              <p className="text-ink mt-1">{d.content.text}</p>
              <dl className="mt-1 grid grid-cols-[110px_1fr] gap-x-3">
                {d.content.facts.map((f) => (
                  <div key={f.name} className="contents">
                    <dt className="text-ink-muted">{f.name}</dt>
                    <dd>{f.value}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-ink-muted mt-1">{d.content.footer}</p>
            </>
          )}
        </div>
      )}
    </li>
  )
}

/** One message: how it was routed, and each delivery with what was sent and every attempt (ADR-0023). */
export function NotificationSheet({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const [n, setN] = useState<NotificationDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [redriving, setRedriving] = useState<DeliveryDetail | null>(null)
  const { isAdministrator } = useRoles()

  const load = useCallback(() => {
    notificationsApi
      .get(id)
      .then(setN)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [id])
  useEffect(load, [load])
  // Follow the deliveries still on their way, or a message not routed yet
  const moving = n !== null && (n.outcome === 'pending' || n.deliveries.some((d) => ['PENDING', 'ATTEMPTING', 'RETRYING'].includes(d.status)))
  useEffect(() => {
    if (!moving) return
    const t = window.setInterval(load, 3000)
    return () => window.clearInterval(t)
  }, [moving, load])

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-[600px]">
        <SheetHeader>
          <SheetTitle>{n ? n.subject : 'Message'}</SheetTitle>
          <SheetDescription>{n ? `${n.typeLabel} · ${at(n.createdAt)}` : ' '}</SheetDescription>
        </SheetHeader>
        <SheetBody className="flex flex-col gap-4 px-5 py-4 text-[13px]">
          {error && <p className="text-critical">{error}</p>}
          {!n && !error && <Loader2 className="text-ink-muted size-5 animate-spin" aria-label="Loading" />}
          {n && (
            <>
              <dl className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-1">
                <dt className="text-ink-muted">Routing</dt>
                <dd>
                  {OUTCOME_LABEL[n.outcome]}
                  {n.route?.routingVersion ? ` by Routing v${n.route.routingVersion}` : ''}
                  {n.route ? `, ${at(n.route.routedAt)}` : ''}
                </dd>
                {n.route && n.route.matched.length > 0 && (
                  <>
                    <dt className="text-ink-muted">Rules that matched</dt>
                    <dd>{n.route.matched.map((r) => r.name).join(', ')}</dd>
                  </>
                )}
                <dt className="text-ink-muted">Reference</dt>
                <dd className="font-mono text-[12px] break-all">{n.dedupKey}</dd>
                {n.eventId && (
                  <>
                    <dt className="text-ink-muted">Event</dt>
                    <dd>
                      <Link to={`/alarms/history?event=${n.eventId}`} className="text-brand inline-flex items-center gap-1 underline-offset-2 hover:underline">
                        Its evidence <ExternalLink className="size-3.5" aria-hidden />
                      </Link>
                    </dd>
                  </>
                )}
              </dl>
              <div>
                <p className="micro-label mb-1.5">Deliveries</p>
                {n.deliveries.length === 0 ? (
                  <p className="text-ink-soft">
                    {n.outcome === 'pending' ? 'The notifier hasn’t routed it yet.' : 'None: nobody was to get it.'}
                  </p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {n.deliveries.map((d) => (
                      <Delivery key={d.id} d={d} canRedrive={isAdministrator} onRedrive={() => setRedriving(d)} />
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </SheetBody>
      </SheetContent>
      {redriving && (
        <ReasonDialog
          title={`Re-drive the ${redriving.channel === 'teams' ? 'Teams' : 'email'} delivery to ${redriving.target}`}
          description="It failed for 24 h. Sending it again starts a new delivery, tried on the same schedule. Say why: it's kept in the change history (NOT-05)."
          confirm="Re-drive"
          onClose={() => setRedriving(null)}
          onConfirm={async (reason) => {
            setN(await notificationsApi.redrive(redriving.id, reason))
            setRedriving(null)
            onChanged()
            toast.success('Sent again', { description: 'The notifier tries the new delivery within seconds.' })
          }}
        />
      )}
    </Sheet>
  )
}
