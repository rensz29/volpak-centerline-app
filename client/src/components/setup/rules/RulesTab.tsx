import { CalendarClock, CloudOff, FilePlus2, History, Loader2, Undo2, Zap } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/shared/EmptyState'
import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiProblem } from '@/services/http'
import { configApi } from '@/services/configApi'
import type { LatestValue, RegisterView, RulesOverview, RulesVersion, RulesVersionStatus } from '@/types/configApi'
import { formatManilaFull } from '@/utils/manilaTime'

import { ActivateDialog, ReasonDialog } from '../VersionDialogs'
import { RulesReadiness } from './RuleDialogs'
import { RulesEditor, type EditorBase } from './RulesEditor'
import { RulesSummary } from './RulesSummary'
import { STATUS_LABELS, normalizeRows } from './ruleModel'

const STATUS_VARIANT: Record<RulesVersionStatus, 'normal' | 'warning' | 'neutral' | 'outline'> = {
  active: 'normal',
  scheduled: 'warning',
  previous: 'neutral',
  saved: 'outline',
}

const when = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`

/**
 * Monitoring rules (ADR-0012, ADR-0027): a target per zone, Warning/Critical limits and
 * delays, versioned. A saved version never changes; it takes effect when activated.
 */
export function RulesTab({
  register,
  latest,
  canEdit = true,
}: {
  register: RegisterView
  latest: Record<string, LatestValue | null>
  /** Only a Manager changes the rules (ADR-0016); others see them read-only. */
  canEdit?: boolean
}) {
  const [overview, setOverview] = useState<RulesOverview | null>(null)
  const [active, setActive] = useState<RulesVersion | null>(null)
  const [error, setError] = useState<ApiProblem | null>(null)
  const [editing, setEditing] = useState<EditorBase | null>(null)
  const [opening, setOpening] = useState(false)
  const [viewing, setViewing] = useState<RulesVersion | null>(null)
  const [activating, setActivating] = useState<number | null>(null)
  const [cancelling, setCancelling] = useState<RulesOverview['scheduled'][number] | null>(null)

  const show = useCallback((next: RulesOverview) => {
    setOverview(next)
    if (next.active) {
      configApi
        .rulesVersion(next.active.number)
        .then(setActive)
        .catch(() => setActive(null))
    } else {
      setActive(null)
    }
  }, [])

  useEffect(() => {
    configApi
      .rules()
      .then(show)
      .catch((caught: unknown) => setError(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) })))
  }, [show])

  const startFrom = async (number: number | null) => {
    setOpening(true)
    try {
      if (number === null) {
        const proposal = await configApi.rulesProposal()
        setEditing({ number: null, source: `the ${proposal.source}`, settings: proposal.settings, rules: normalizeRows(proposal.rules) })
      } else {
        const v = await configApi.rulesVersion(number)
        // Saved for a product code before ADR-0027: its targets become the zones' own
        setEditing(
          v.carryOver
            ? { number, source: `Rules v${number}, with the targets it had for ${v.carryOver.from}`, settings: v.settings, rules: v.carryOver.rules }
            : { number, source: `Rules v${number}`, settings: v.settings, rules: v.rules },
        )
      }
    } catch (caught) {
      toast.error("Couldn't open the rules", { description: caught instanceof Error ? caught.message : String(caught) })
    } finally {
      setOpening(false)
    }
  }

  if (error) {
    return (
      <div className="bg-surface border-critical-border shadow-card rounded-lg border">
        <EmptyState icon={CloudOff} title="Can't load the rules" description={error.message} />
      </div>
    )
  }
  if (!overview) return <Skeleton className="h-[420px] w-full rounded-lg" />

  if (editing) {
    return (
      <RulesEditor
        key={`${editing.number ?? 'proposal'}-${overview.latest ?? 0}`}
        base={editing}
        overview={overview}
        register={register}
        latest={latest}
        onCancel={() => setEditing(null)}
        onSaved={(next) => {
          setEditing(null)
          show(next)
        }}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <SectionCard
        title="Rules in effect"
        description={`Targets, limits and delays that monitor-core will judge against (register ${overview.registerVersion})`}
        icon={Zap}
        actions={
          canEdit ? (
            <span className="flex flex-wrap gap-2">
              {/* The proposal again: e.g. to replace test values with ADR-0002's limits and delays */}
              {overview.latest !== null && (
                <Button type="button" size="sm" variant="outline" disabled={opening} onClick={() => void startFrom(null)}>
                  <FilePlus2 className="size-4" aria-hidden /> New version from the Phase 0 proposal
                </Button>
              )}
              <Button type="button" size="sm" disabled={opening} onClick={() => void startFrom(overview.latest)}>
                {opening ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FilePlus2 className="size-4" aria-hidden />}
                {overview.latest === null ? 'Start from the Phase 0 proposal' : `New version from v${overview.latest}`}
              </Button>
            </span>
          ) : undefined
        }
      >
        {overview.active ? (
          <div className="flex flex-col gap-4">
            <p className="text-[13px]">
              <Badge variant="normal">Rules v{overview.active.number}</Badge>{' '}
              <span className="text-ink">since {when(overview.active.since)}</span>
              <span className="text-ink-soft"> · “{overview.active.reason}”{overview.active.by && ` · by ${overview.active.by}`}</span>
            </p>
            {active ? <RulesSummary version={active} register={register} /> : <Skeleton className="h-40 w-full" />}
          </div>
        ) : (
          <div className="text-[13px]">
            <p className="text-ink font-medium">No rules are in effect yet.</p>
            <p className="text-ink-soft mt-1 max-w-3xl">
              {overview.latest === null
                ? 'Start from the Phase 0 proposal: the delays accepted in ADR-0002, the limits proposed from 28 days of Timebase history and the stop pause from ADR-0010. Review it, give each zone its target from the centerline sheet, save it, then activate it. A zone without a target has only its actual value judged (ADR-0027).'
                : 'A version is saved but not active. Activate it from the list below when its delays and limits are accepted.'}
            </p>
          </div>
        )}
        {overview.scheduled.length > 0 && (
          <ul className="border-line mt-4 flex flex-col gap-1.5 border-t pt-3 text-[13px]">
            {overview.scheduled.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  <CalendarClock className="text-warning size-4" aria-hidden />
                  Rules v{s.number} takes effect {when(s.at)} <span className="text-ink-soft">· “{s.reason}”{s.by && ` · by ${s.by}`}</span>
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
                  <td className="text-ink px-3 py-2">{v.reason}</td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS_VARIANT[v.status]}>{STATUS_LABELS[v.status]}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        void configApi
                          .rulesVersion(v.number)
                          .then(setViewing)
                          .catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))
                      }
                    >
                      View
                    </Button>
                    {canEdit && (
                      <Button type="button" variant="ghost" size="sm" onClick={() => void startFrom(v.number)}>
                        <FilePlus2 className="size-3.5" aria-hidden /> Edit as new
                      </Button>
                    )}
                    {canEdit && v.status !== 'active' && (
                      <Button type="button" variant="outline" size="sm" onClick={() => setActivating(v.number)}>
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
        <Dialog open onOpenChange={(open) => !open && setViewing(null)}>
          <DialogContent className="sm:max-w-[980px]">
            <DialogHeader>
              <DialogTitle>Rules v{viewing.number}</DialogTitle>
              <DialogDescription>
                Saved {when(viewing.createdAt)} against register {viewing.registerVersion}
                {viewing.basedOn !== null ? `, from v${viewing.basedOn}` : ''} · “{viewing.reason}”
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <RulesSummary version={viewing} register={register} />
            </DialogBody>
          </DialogContent>
        </Dialog>
      )}
      {activating !== null && (
        <ActivateDialog
          label="Rules"
          number={activating}
          rollback={overview.versions.find((v) => v.number === activating)?.status === 'previous'}
          activeNumber={overview.active?.number ?? null}
          scheduled={overview.scheduled}
          details={<RulesReadiness number={activating} />}
          placeholder="e.g. Limits confirmed by process engineering"
          onClose={() => setActivating(null)}
          onActivate={async (at, reason) => {
            const next = await configApi.activateRules(activating, { expectedActive: overview.active?.number ?? null, at, reason })
            setActivating(null)
            show(next)
            toast.success(next.active?.number === activating ? `Rules v${activating} is in effect` : `Rules v${activating} scheduled`)
          }}
        />
      )}
      {cancelling && (
        <ReasonDialog
          title={`Cancel the switch to Rules v${cancelling.number}`}
          description={`It was due ${when(cancelling.at)}. The rules in effect stay as they are.`}
          confirm="Cancel the switch"
          onClose={() => setCancelling(null)}
          onConfirm={async (reason) => {
            show(await configApi.cancelActivation(cancelling.id, reason))
            setCancelling(null)
          }}
        />
      )}
    </div>
  )
}
