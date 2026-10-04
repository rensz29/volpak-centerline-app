import { CalendarClock, CheckCircle2, CloudOff, Download, FilePlus2, History, Loader2, TriangleAlert, Undo2, Waypoints, Zap } from 'lucide-react'
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
import type { MappingsOverview, MappingVersion, RulesVersionStatus } from '@/types/configApi'
import { formatManilaFull } from '@/utils/manilaTime'

import { STATUS_LABELS } from '../rules/ruleModel'
import { ActivateDialog, ReasonDialog } from '../VersionDialogs'
import { asProblem } from '../versionUtils'
import { MappingEditor, type MappingBase } from './MappingEditor'
import { MappingRowsTable } from './MappingRowsTable'

const STATUS_VARIANT: Record<RulesVersionStatus, 'normal' | 'warning' | 'neutral' | 'outline'> = {
  active: 'normal',
  scheduled: 'warning',
  previous: 'neutral',
  saved: 'outline',
}

const when = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`

/**
 * Tag mappings (ADR-0013): where monitor-core finds each register tag on MQTT.
 * Versioned like the rules; only a version with a place for every tag can be activated.
 */
/** `canEdit`: only an Administrator changes the mappings (ADR-0016); others see them read-only. */
export function MappingsTab({ canEdit = true }: { canEdit?: boolean }) {
  const [overview, setOverview] = useState<MappingsOverview | null>(null)
  const [error, setError] = useState<ApiProblem | null>(null)
  const [editing, setEditing] = useState<MappingBase | null>(null)
  const [opening, setOpening] = useState(false)
  const [viewing, setViewing] = useState<MappingVersion | null>(null)
  const [activating, setActivating] = useState<MappingVersion | null>(null)
  const [cancelling, setCancelling] = useState<MappingsOverview['scheduled'][number] | null>(null)

  const load = useCallback(() => {
    configApi
      .mappings()
      .then(setOverview)
      .catch((caught: unknown) => setError(asProblem(caught)))
  }, [])

  useEffect(load, [load])

  const startFrom = async (number: number | null) => {
    setOpening(true)
    try {
      if (number === null) {
        setEditing({ number: null, source: 'by hand', rows: [], sku: null, skuPlaceholder: null })
      } else {
        const v = await configApi.mappingVersion(number)
        setEditing({ number, source: `Mapping v${number}`, rows: v.rows, sku: v.sku, skuPlaceholder: v.skuPlaceholder })
      }
    } catch (caught) {
      toast.error("Couldn't open the mapping", { description: asProblem(caught).message })
    } finally {
      setOpening(false)
    }
  }

  const open = (number: number, then: (v: MappingVersion) => void) =>
    void configApi
      .mappingVersion(number)
      .then(then)
      .catch((caught: unknown) => toast.error(asProblem(caught).message))

  if (error) {
    return (
      <div className="bg-surface border-critical-border shadow-card rounded-lg border">
        <EmptyState icon={CloudOff} title="Can't load the mappings" description={error.message} />
      </div>
    )
  }
  if (!overview) return <Skeleton className="h-[420px] w-full rounded-lg" />

  if (editing) {
    return (
      <MappingEditor
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

  const coverage = overview.coverage

  return (
    <div className="flex flex-col gap-4">
      <SectionCard
        title="Mapping in effect"
        description={`Where monitor-core finds each tag on the broker (register ${overview.registerVersion})`}
        icon={Waypoints}
        actions={
          canEdit ? (
            <Button type="button" size="sm" disabled={opening} onClick={() => void startFrom(overview.latest)}>
              {opening ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FilePlus2 className="size-4" aria-hidden />}
              {overview.latest === null ? 'Start the first mapping' : `New version from v${overview.latest}`}
            </Button>
          ) : undefined
        }
      >
        {overview.active ? (
          <div className="flex flex-col gap-2 text-[13px]">
            <p>
              <Badge variant="normal">Mapping v{overview.active.number}</Badge>{' '}
              <span className="text-ink">since {when(overview.active.since)}</span>
              <span className="text-ink-soft"> · “{overview.active.reason}”{overview.active.by && ` · by ${overview.active.by}`}</span>
            </p>
            {coverage && coverage.missing.length === 0 ? (
              <p className="text-normal inline-flex items-center gap-1.5">
                <CheckCircle2 className="size-4" aria-hidden /> Every tag monitor-core needs has a place ({coverage.mapped} of{' '}
                {coverage.required})
              </p>
            ) : (
              coverage && (
                <p className="border-critical-border bg-critical-surface text-critical flex items-start gap-2 rounded-md border px-3 py-2">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  The register now needs {coverage.missing.length} tag{coverage.missing.length === 1 ? '' : 's'} this mapping has no
                  place for ({coverage.missing.map((m) => m.label).join(', ')}). Monitoring pauses until a new mapping is activated.
                </p>
              )
            )}
            <p className={overview.sku ? 'text-ink' : 'text-warning'}>
              {overview.sku
                ? `SKU field: ${overview.sku.field} on ${overview.sku.topic}`
                : overview.skuPlaceholder
                  ? `Placeholder SKU: ${overview.skuPlaceholder}, until the machine publishes its SKU (O-15). Actual values are judged, and HMI setpoints where the Rules tab gives the placeholder targets (ADR-0022)`
                  : 'SKU field: none yet, so monitoring of the real machine pauses (O-15)'}
            </p>
          </div>
        ) : (
          <div className="text-[13px]">
            <p className="text-ink font-medium">No mapping is in effect yet.</p>
            <p className="text-ink-soft mt-1 max-w-3xl">
              Monitor-core can't read the machine until one is. Start one, then fill it from the broker (a 10-second read-only
              listen) or import the probe's <code className="text-[12px]">topic-map.json</code>. Check it and activate it.
            </p>
          </div>
        )}
        {overview.scheduled.length > 0 && (
          <ul className="border-line mt-4 flex flex-col gap-1.5 border-t pt-3 text-[13px]">
            {overview.scheduled.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  <CalendarClock className="text-warning size-4" aria-hidden />
                  Mapping v{s.number} takes effect {when(s.at)} <span className="text-ink-soft">· “{s.reason}”{s.by && ` · by ${s.by}`}</span>
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
                <th className="px-3 py-2 font-semibold">Source</th>
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
                  <td className="text-ink-soft px-3 py-2">{v.source}</td>
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
                    <Button type="button" variant="ghost" size="sm" asChild>
                      <a href={configApi.mappingCsvUrl(v.number)} download>
                        <Download className="size-3.5" aria-hidden /> CSV
                      </a>
                    </Button>
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
          <DialogContent className="sm:max-w-[980px]">
            <DialogHeader>
              <DialogTitle>Mapping v{viewing.number}</DialogTitle>
              <DialogDescription>
                Saved {when(viewing.createdAt)} against register {viewing.registerVersion} · {viewing.source} · “{viewing.reason}”
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-3">
              {!viewing.intact && (
                <p className="text-critical text-[13px]">
                  This version's stored content no longer matches its fingerprint: it was changed outside Centerline. Don't activate it.
                </p>
              )}
              <MappingRowsTable required={overview.required} rows={viewing.rows} sku={viewing.sku} skuPlaceholder={viewing.skuPlaceholder} />
            </DialogBody>
          </DialogContent>
        </Dialog>
      )}
      {activating && (
        <ActivateDialog
          label="Mapping"
          number={activating.number}
          rollback={overview.versions.find((v) => v.number === activating.number)?.status === 'previous'}
          activeNumber={overview.active?.number ?? null}
          scheduled={overview.scheduled}
          placeholder="e.g. Checked against the probe run on the plant broker"
          blocked={
            !activating.intact
              ? 'Its stored content no longer matches its fingerprint.'
              : activating.coverage.missing.length
                ? `${activating.coverage.missing.length} tag(s) the register needs have no place in it: ${activating.coverage.missing
                    .map((m) => m.label)
                    .join(', ')}.`
                : null
          }
          details={
            <p className="text-ink-soft text-[12px]">
              {activating.coverage.mapped} of {activating.coverage.required} tags have a place ·{' '}
              {activating.sku
                ? `SKU field: ${activating.sku.field}`
                : activating.skuPlaceholder
                  ? `placeholder SKU ${activating.skuPlaceholder}: actual values, and HMI where it has targets`
                  : 'SKU field: none yet'}
            </p>
          }
          onClose={() => setActivating(null)}
          onActivate={async (at, reason) => {
            const next = await configApi.activateMapping(activating.number, { expectedActive: overview.active?.number ?? null, at, reason })
            setActivating(null)
            setOverview(next)
            toast.success(next.active?.number === activating.number ? `Mapping v${activating.number} is in effect` : `Mapping v${activating.number} scheduled`)
          }}
        />
      )}
      {cancelling && (
        <ReasonDialog
          title={`Cancel the switch to Mapping v${cancelling.number}`}
          description={`It was due ${when(cancelling.at)}. The mapping in effect stays as it is.`}
          confirm="Cancel the switch"
          onClose={() => setCancelling(null)}
          onConfirm={async (reason) => {
            setOverview(await configApi.cancelMappingActivation(cancelling.id, reason))
            setCancelling(null)
          }}
        />
      )}
    </div>
  )
}
