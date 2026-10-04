import { CalendarClock, CheckCircle2, CloudOff, FilePlus2, History, ListChecks, Loader2, Pencil, Plus, Trash2, TriangleAlert, Undo2, Zap } from 'lucide-react'
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
import type { LatestValue, RegisterView, RulesOverview, RulesVersion, RulesVersionStatus, Sku } from '@/types/configApi'
import { formatManilaFull } from '@/utils/manilaTime'

import { ActivateDialog, ReasonDialog } from '../VersionDialogs'
import { RulesReadiness, SkuDialog } from './RuleDialogs'
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
 * Monitoring rules (ADR-0012): targets per SKU and zone, Warning/Critical limits and
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
  const [skuDialog, setSkuDialog] = useState<{ sku: Sku | null } | null>(null)
  const [removing, setRemoving] = useState<Sku | null>(null)

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
        setEditing({ number, source: `Rules v${number}`, settings: v.settings, rules: v.rules })
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
        onOverview={show}
        onSaved={(next) => {
          setEditing(null)
          show(next)
        }}
      />
    )
  }

  const ready = overview.skus.filter((s) => (overview.readiness[s.code] ?? []).length === 0)

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
            {active ? <RulesSummary version={active} register={register} skus={overview.skus} /> : <Skeleton className="h-40 w-full" />}
          </div>
        ) : (
          <div className="text-[13px]">
            <p className="text-ink font-medium">No rules are in effect yet.</p>
            <p className="text-ink-soft mt-1 max-w-3xl">
              {overview.latest === null
                ? 'Start from the Phase 0 proposal: the delays accepted in ADR-0002, the limits proposed from 28 days of Timebase history and the stop pause from ADR-0010. Review it, add the SKUs and their targets, save it, then activate it. With a placeholder SKU on the Mappings tab, it can go into effect without SKUs: the line is then judged on actual values. Add the placeholder code to the SKU list and give it targets to judge the HMI setpoints too (ADR-0022).'
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

      <SectionCard
        title="SKUs"
        description={
          overview.active
            ? `${ready.length} of ${overview.skus.length} ready under Rules v${overview.active.number}. A SKU that isn't ready pauses monitoring while it runs (OPC-08).`
            : 'The SKU codes the machine publishes (O-15). Targets are set per SKU in a rules version.'
        }
        icon={ListChecks}
        actions={
          canEdit ? (
            <Button type="button" variant="outline" size="sm" onClick={() => setSkuDialog({ sku: null })}>
              <Plus className="size-3.5" aria-hidden /> Add SKU
            </Button>
          ) : undefined
        }
        flush
      >
        {overview.skus.length === 0 ? (
          <p className="text-ink-soft px-5 py-4 text-[13px]">
            No SKUs yet. Process engineering has the list and each SKU's target per zone (their centerline sheets).
          </p>
        ) : (
          <table className="w-full text-[13px]">
            <tbody>
              {overview.skus.map((s) => {
                const gaps = overview.readiness[s.code]
                return (
                  <tr key={s.code} className="border-line-soft border-b">
                    <td className="w-[160px] px-5 py-2 font-mono">{s.code}</td>
                    <td className="text-ink px-3 py-2">{s.name}</td>
                    <td className="px-3 py-2">
                      {!overview.active ? (
                        <span className="text-ink-muted text-[12px]">no rules in effect</span>
                      ) : gaps && gaps.length === 0 ? (
                        <span className="text-normal inline-flex items-center gap-1 text-[12px]">
                          <CheckCircle2 className="size-3.5" aria-hidden /> ready
                        </span>
                      ) : (
                        <span className="text-warning inline-flex items-center gap-1 text-[12px]">
                          <TriangleAlert className="size-3.5" aria-hidden /> {gaps?.length ?? 0} zone(s) without a target or limits
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {canEdit && (
                        <>
                          <Button type="button" variant="ghost" size="sm" onClick={() => setSkuDialog({ sku: s })}>
                            <Pencil className="size-3.5" aria-hidden /> Rename
                          </Button>
                          <Button type="button" variant="ghost" size="sm" onClick={() => setRemoving(s)}>
                            <Trash2 className="size-3.5" aria-hidden /> Remove
                          </Button>
                        </>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
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
              <RulesSummary version={viewing} register={register} skus={overview.skus} />
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
      {skuDialog && (
        <SkuDialog
          sku={skuDialog.sku}
          onClose={() => setSkuDialog(null)}
          onSaved={(next) => {
            setSkuDialog(null)
            show(next)
          }}
        />
      )}
      {removing && (
        <ReasonDialog
          title={`Remove SKU ${removing.code}`}
          description="Only a SKU that no saved version uses can be removed, e.g. one added with a typo."
          confirm="Remove"
          destructive
          required={false}
          onClose={() => setRemoving(null)}
          onConfirm={async (reason) => {
            show(await configApi.deleteSku(removing.code, reason))
            setRemoving(null)
          }}
        />
      )}
    </div>
  )
}
