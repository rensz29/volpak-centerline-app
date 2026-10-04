import { CalendarClock, CloudOff, FilePlus2, History, Loader2, Send, TriangleAlert, Undo2, Zap } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/shared/EmptyState'
import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import type { ApiProblem } from '@/services/http'
import { notificationsApi } from '@/services/notificationsApi'
import type { RulesVersionStatus } from '@/types/configApi'
import type { RoutingOverview, RoutingRule, RoutingType, RoutingVersion } from '@/types/notificationsApi'
import { formatManilaFull } from '@/utils/manilaTime'

import { STATUS_LABELS } from '../rules/ruleModel'
import { ActivateDialog, ReasonDialog } from '../VersionDialogs'
import { asProblem } from '../versionUtils'
import { RoutingEditor, type RoutingBase } from './RoutingEditor'

const STATUS_VARIANT: Record<RulesVersionStatus, 'normal' | 'warning' | 'neutral' | 'outline'> = {
  active: 'normal',
  scheduled: 'warning',
  previous: 'neutral',
  saved: 'outline',
}

const when = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`

function Warnings({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <ul className="text-warning flex flex-col gap-1 text-[12px]">
      {items.map((w) => (
        <li key={w} className="flex items-start gap-1.5">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {w}
        </li>
      ))}
    </ul>
  )
}

/** Who gets what, as a table: each rule's channel, the kinds of message it sends, and its recipients. */
export function RoutingRulesTable({ rules, types }: { rules: RoutingRule[]; types: RoutingType[] }) {
  const label = (id: string) => types.find((t) => t.id === id)?.label ?? id
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
          <th className="py-2 pr-3 font-semibold">Rule</th>
          <th className="px-3 py-2 font-semibold">Channel</th>
          <th className="px-3 py-2 font-semibold">Sends</th>
          <th className="px-3 py-2 font-semibold">To</th>
        </tr>
      </thead>
      <tbody>
        {rules.map((r) => (
          <tr key={r.name} className="border-line-soft border-b align-top">
            <td className="text-ink py-2 pr-3 font-medium">{r.name}</td>
            <td className="text-ink-soft px-3 py-2">{r.channel === 'teams' ? 'Teams' : 'Email'}</td>
            <td className="text-ink-soft px-3 py-2">
              {r.types.length === types.length ? 'Every kind' : r.types.map(label).join(', ')}
            </td>
            <td className="px-3 py-2 font-mono text-[12px]">
              {r.targets.map((t) => (
                <div key={t}>{t}</div>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * Notification routing (ADR-0023): who gets which messages, on which channel. Versioned like the
 * rules; a version that leaves a kind of Critical with nobody to tell can't be activated (ACT-03).
 * `canEdit`: only an Administrator changes it (ADR-0016); a Manager sees it read-only.
 */
export function RoutingTab({ canEdit = true }: { canEdit?: boolean }) {
  const [overview, setOverview] = useState<RoutingOverview | null>(null)
  const [error, setError] = useState<ApiProblem | null>(null)
  const [editing, setEditing] = useState<RoutingBase | null>(null)
  const [opening, setOpening] = useState(false)
  const [viewing, setViewing] = useState<RoutingVersion | null>(null)
  const [activating, setActivating] = useState<RoutingVersion | null>(null)
  const [cancelling, setCancelling] = useState<RoutingOverview['scheduled'][number] | null>(null)

  const load = useCallback(() => {
    notificationsApi
      .routing()
      .then(setOverview)
      .catch((caught: unknown) => setError(asProblem(caught)))
  }, [])

  useEffect(load, [load])

  const startFrom = async (number: number | null) => {
    setOpening(true)
    try {
      if (number === null) {
        const p = await notificationsApi.routingProposal()
        setEditing({ number: null, source: `the ${p.source}`, rules: p.rules })
      } else {
        const v = await notificationsApi.routingVersion(number)
        setEditing({ number, source: `Routing v${number}`, rules: v.rules })
      }
    } catch (caught) {
      toast.error("Couldn't open the routing", { description: asProblem(caught).message })
    } finally {
      setOpening(false)
    }
  }

  const open = (number: number, then: (v: RoutingVersion) => void) =>
    void notificationsApi
      .routingVersion(number)
      .then(then)
      .catch((caught: unknown) => toast.error(asProblem(caught).message))

  if (error) {
    return (
      <div className="bg-surface border-critical-border shadow-card rounded-lg border">
        <EmptyState icon={CloudOff} title="Can't load the routing" description={error.message} />
      </div>
    )
  }
  if (!overview) return <Skeleton className="h-[420px] w-full rounded-lg" />

  if (editing) {
    return (
      <RoutingEditor
        key={`${editing.number ?? 'new'}-${overview.latest ?? 0}`}
        base={editing}
        overview={overview}
        onCancel={() => setEditing(null)}
        onSaved={(next) => {
          setEditing(null)
          setOverview(next)
        }}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <SectionCard
        title="Routing in effect"
        description="Who gets which messages from the notifier, on Teams and by email"
        icon={Send}
        actions={
          canEdit ? (
            <Button type="button" size="sm" disabled={opening} onClick={() => void startFrom(overview.latest)}>
              {opening ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FilePlus2 className="size-4" aria-hidden />}
              {overview.latest === null ? 'Start from the Phase 2 proposal' : `New version from v${overview.latest}`}
            </Button>
          ) : undefined
        }
      >
        {overview.active && overview.rules ? (
          <div className="flex flex-col gap-3 text-[13px]">
            <p>
              <Badge variant="normal">Routing v{overview.active.number}</Badge>{' '}
              <span className="text-ink">since {when(overview.active.since)}</span>
              <span className="text-ink-soft"> · “{overview.active.reason}”{overview.active.by && ` · by ${overview.active.by}`}</span>
            </p>
            <RoutingRulesTable rules={overview.rules} types={overview.types} />
            <Warnings items={overview.warnings} />
          </div>
        ) : (
          <div className="text-[13px]">
            <p className="text-ink font-medium">No routing is in effect yet, so no message leaves Centerline.</p>
            <p className="text-ink-soft mt-1 max-w-3xl">
              Messages still show on the Notifications page, marked “not sent”. Start from the proposal: Management gets every kind
              of message on Teams and by email. Replace its placeholder recipients with the real ones from IT, then activate it.
            </p>
          </div>
        )}
        {overview.scheduled.length > 0 && (
          <ul className="border-line mt-4 flex flex-col gap-1.5 border-t pt-3 text-[13px]">
            {overview.scheduled.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  <CalendarClock className="text-warning size-4" aria-hidden />
                  Routing v{s.number} takes effect {when(s.at)} <span className="text-ink-soft">· “{s.reason}”{s.by && ` · by ${s.by}`}</span>
                </span>
                {canEdit && (
                  <Button type="button" variant="outline" size="sm" onClick={() => setCancelling(s)}>
                    Cancel
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard title="Versions" description="Every saved version is kept as it was saved" icon={History} flush>
        {overview.versions.length === 0 ? (
          <p className="text-ink-soft px-5 py-4 text-[13px]">No versions saved yet.</p>
        ) : (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
                <th className="px-5 py-2 font-semibold">Version</th>
                <th className="px-3 py-2 font-semibold">Saved</th>
                <th className="px-3 py-2 font-semibold">By</th>
                <th className="px-3 py-2 font-semibold">Reason</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {overview.versions.map((v) => (
                <tr key={v.number} className="border-line-soft border-b">
                  <td className="px-5 py-2 font-medium">
                    v{v.number}
                    {v.basedOn !== null && <span className="text-ink-muted text-[11px] font-normal"> from v{v.basedOn}</span>}
                  </td>
                  <td className="text-ink-soft px-3 py-2">{when(v.createdAt)}</td>
                  <td className="text-ink-soft px-3 py-2">{v.by ?? '—'}</td>
                  <td className="text-ink px-3 py-2">{v.reason}</td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS_VARIANT[v.status]}>{STATUS_LABELS[v.status]}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <Button type="button" variant="ghost" size="sm" onClick={() => open(v.number, setViewing)}>
                      View
                    </Button>
                    {canEdit && (
                      <Button type="button" variant="ghost" size="sm" onClick={() => void startFrom(v.number)}>
                        <FilePlus2 className="size-3.5" aria-hidden /> Edit as new
                      </Button>
                    )}
                    {canEdit && v.status !== 'active' && (
                      <Button type="button" variant="outline" size="sm" onClick={() => open(v.number, setActivating)}>
                        {v.status === 'previous' ? <Undo2 className="size-3.5" aria-hidden /> : <Zap className="size-3.5" aria-hidden />}
                        {v.status === 'previous' ? 'Roll back to' : 'Activate'}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {viewing && (
        <Dialog open onOpenChange={(o) => !o && setViewing(null)}>
          <DialogContent className="sm:max-w-[860px]">
            <DialogHeader>
              <DialogTitle>Routing v{viewing.number}</DialogTitle>
              <DialogDescription>
                Saved {when(viewing.createdAt)}
                {viewing.by ? ` by ${viewing.by}` : ''} · “{viewing.reason}”
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-3">
              {!viewing.intact && (
                <p className="text-critical text-[13px]">
                  This version's stored content no longer matches its fingerprint: it was changed outside Centerline. Don't activate it.
                </p>
              )}
              <RoutingRulesTable rules={viewing.rules} types={overview.types} />
              <Warnings items={viewing.warnings} />
            </DialogBody>
          </DialogContent>
        </Dialog>
      )}
      {activating && (
        <ActivateDialog
          label="Routing"
          number={activating.number}
          rollback={overview.versions.find((v) => v.number === activating.number)?.status === 'previous'}
          activeNumber={overview.active?.number ?? null}
          scheduled={overview.scheduled}
          placeholder="e.g. Addresses confirmed by IT"
          blocked={
            !activating.intact
              ? 'Its stored content no longer matches its fingerprint.'
              : (activating.warnings.find((w) => w.includes('ACT-03')) ?? null)
          }
          details={<RoutingRulesTable rules={activating.rules} types={overview.types} />}
          onClose={() => setActivating(null)}
          onActivate={async (at, reason) => {
            const next = await notificationsApi.activateRouting(activating.number, { expectedActive: overview.active?.number ?? null, at, reason })
            setActivating(null)
            setOverview(next)
            toast.success(next.active?.number === activating.number ? `Routing v${activating.number} is in effect` : `Routing v${activating.number} scheduled`)
          }}
        />
      )}
      {cancelling && (
        <ReasonDialog
          title={`Cancel the switch to Routing v${cancelling.number}`}
          description={`It was due ${when(cancelling.at)}. The routing in effect stays as it is.`}
          confirm="Cancel the switch"
          onClose={() => setCancelling(null)}
          onConfirm={async (reason) => {
            setOverview(await notificationsApi.cancelRoutingActivation(cancelling.id, reason))
            setCancelling(null)
          }}
        />
      )}
    </div>
  )
}
