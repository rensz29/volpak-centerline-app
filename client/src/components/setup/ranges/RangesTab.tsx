import { CalendarClock, CloudOff, Download, FileCheck2, FileUp, History, Loader2, Ruler, TriangleAlert, Undo2, XCircle, Zap } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/shared/EmptyState'
import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ApiProblem } from '@/services/http'
import { rangesApi, readUpload } from '@/services/rangesApi'
import type { RulesVersionStatus } from '@/types/configApi'
import type { RangeRow, RangesCheck, RangesDraft, RangesOverview, RangesUpload, RangesVersion } from '@/types/rangesApi'
import { fromManilaInput, formatManilaFull, toUtcIso } from '@/utils/manilaTime'

import { FormField } from '../FormParts'
import { STATUS_LABELS } from '../rules/ruleModel'
import { ActivateDialog, ReasonDialog } from '../VersionDialogs'
import { asProblem, nextHourInput } from '../versionUtils'

const STATUS_VARIANT: Record<RulesVersionStatus, 'normal' | 'warning' | 'neutral' | 'outline'> = {
  active: 'normal',
  scheduled: 'warning',
  previous: 'neutral',
  saved: 'outline',
}

const when = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`

function Problems({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <ul className="text-critical flex flex-col gap-1 text-[12px]">
      {items.map((p) => (
        <li key={p} className="flex items-start gap-1.5">
          <XCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {p}
        </li>
      ))}
    </ul>
  )
}

/** One version's ranges: what a value must lie within to count in Analytics. */
export function RangeRowsTable({ rows }: { rows: RangeRow[] }) {
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
          <th className="py-2 pr-3 font-semibold">Parameter</th>
          <th className="px-3 py-2 font-semibold">Unit</th>
          <th className="px-3 py-2 text-right font-semibold">Valid from</th>
          <th className="px-3 py-2 text-right font-semibold">Valid to</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.parameterId} className="border-line-soft border-b">
            <td className="py-1.5 pr-3">
              {r.parameterName ?? r.parameterId} <span className="text-ink-muted text-[11px]">{r.parameterId}</span>
            </td>
            <td className="text-ink-soft px-3 py-1.5">{r.unit || '—'}</td>
            <td className="px-3 py-1.5 text-right font-mono text-[12px] tabular-nums">{r.validMin}</td>
            <td className="px-3 py-1.5 text-right font-mono text-[12px] tabular-nums">{r.validMax}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Upload a ranges file: checked as a whole before it can be saved, kept exactly as uploaded. */
function UploadCard({ overview, onSaved }: { overview: RangesOverview; onSaved: (next: RangesOverview) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [upload, setUpload] = useState<RangesUpload | null>(null)
  const [check, setCheck] = useState<RangesCheck | null>(null)
  const [reason, setReason] = useState('')
  const [activate, setActivate] = useState<RangesDraft['activate']>('now')
  const [activateAt, setActivateAt] = useState(nextHourInput)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [busy, setBusy] = useState(false)

  const choose = async (file: File) => {
    setProblem(null)
    setCheck(null)
    try {
      const read = await readUpload(file)
      setUpload(read)
      setCheck(await rangesApi.check(read))
    } catch (caught) {
      setProblem(asProblem(caught))
    }
  }

  const save = async () => {
    if (!upload) return
    setBusy(true)
    setProblem(null)
    try {
      const next = await rangesApi.save({
        ...upload,
        expectedLatest: overview.latest,
        reason,
        activate,
        activateAt: activate === 'at' ? toUtcIso(fromManilaInput(activateAt) ?? Date.now()) : null,
      })
      toast.success(`Analytics ranges v${next.created} saved`, {
        description: activate === 'no' ? 'Not in effect until you activate it' : activate === 'now' ? 'Now in effect' : 'Activation scheduled',
      })
      setUpload(null)
      setCheck(null)
      setReason('')
      onSaved(next)
    } catch (caught) {
      setProblem(asProblem(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SectionCard
      title="Upload a ranges file"
      description="One row per parameter: parameter_id, unit, valid_min, valid_max. The whole file is accepted or rejected."
      icon={FileUp}
      actions={
        <Button asChild variant="outline" size="sm">
          <a href={rangesApi.templateUrl} download>
            <Download className="size-3.5" aria-hidden /> Template
          </a>
        </Button>
      }
    >
      <div className="flex flex-col gap-4 text-[13px]">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void choose(file)
              e.target.value = ''
            }}
          />
          <Button type="button" size="sm" variant="outline" onClick={() => input.current?.click()}>
            <FileUp className="size-4" aria-hidden /> Choose the CSV
          </Button>
          {upload && <span className="font-mono text-[12px]">{upload.source}</span>}
        </div>

        {check && check.problems.length > 0 && (
          <div className="border-critical-border bg-critical-surface rounded-md border px-3 py-2">
            <p className="text-critical mb-1 font-medium">The file is rejected: fix these and upload it again</p>
            <Problems items={check.problems} />
          </div>
        )}
        {check?.rows && (
          <>
            <p className="text-normal flex items-center gap-1.5">
              <FileCheck2 className="size-4" aria-hidden /> Every parameter has a valid range · SHA-256{' '}
              <span className="font-mono text-[11px]">{check.sha256?.slice(0, 16)}…</span>
            </p>
            <RangeRowsTable rows={check.rows} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <FormField label="Reason" error={problem?.forField('reason')} hint="Required. Kept with the version.">
                <Textarea
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Ranges approved by process engineering on 6 Oct"
                  className="text-[13px]"
                  aria-label="Reason"
                />
              </FormField>
              <fieldset className="flex flex-col gap-2">
                <legend className="micro-label mb-1.5">After saving</legend>
                <label className="flex items-center gap-2">
                  <input type="radio" name="ranges-activate" checked={activate === 'now'} onChange={() => setActivate('now')} />
                  Activate now
                </label>
                <label className="flex flex-wrap items-center gap-2">
                  <input type="radio" name="ranges-activate" checked={activate === 'at'} onChange={() => setActivate('at')} />
                  Activate at
                  <Input
                    type="datetime-local"
                    value={activateAt}
                    onChange={(e) => {
                      setActivateAt(e.target.value)
                      setActivate('at')
                    }}
                    className="h-8 w-auto text-[13px]"
                    aria-label="Activation time, Manila"
                  />
                  <span className="text-ink-muted text-[12px]">Manila</span>
                </label>
                <label className="flex items-center gap-2">
                  <input type="radio" name="ranges-activate" checked={activate === 'no'} onChange={() => setActivate('no')} />
                  Keep it saved; activate later
                </label>
              </fieldset>
            </div>
            <div className="flex justify-end">
              <Button type="button" size="sm" disabled={busy} onClick={() => void save()}>
                {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Save version
              </Button>
            </div>
          </>
        )}
        {problem && (
          <div className="flex flex-col gap-1">
            <p className="text-critical">{problem.fieldErrors.length ? 'It can’t be saved:' : problem.message}</p>
            <Problems items={problem.fieldErrors.map((e) => e.message)} />
          </div>
        )}
      </div>
    </SectionCard>
  )
}

/**
 * Analytics-valid ranges (ANA-10/11, ADR-0029): what a sample must lie within to count in Analytics,
 * separate from the monitoring limits. Versioned like the rules; `canEdit`: only an Administrator uploads
 * and activates them (ADR-0016), a Manager sees them read-only.
 */
export function RangesTab({ canEdit = true }: { canEdit?: boolean }) {
  const [overview, setOverview] = useState<RangesOverview | null>(null)
  const [error, setError] = useState<ApiProblem | null>(null)
  const [viewing, setViewing] = useState<RangesVersion | null>(null)
  const [activating, setActivating] = useState<RangesVersion | null>(null)
  const [cancelling, setCancelling] = useState<RangesOverview['scheduled'][number] | null>(null)

  const load = useCallback(() => {
    rangesApi
      .overview()
      .then(setOverview)
      .catch((caught: unknown) => setError(asProblem(caught)))
  }, [])

  useEffect(load, [load])

  const open = (number: number, then: (v: RangesVersion) => void) =>
    void rangesApi
      .version(number)
      .then(then)
      .catch((caught: unknown) => toast.error(asProblem(caught).message))

  if (error) {
    return (
      <div className="bg-surface border-critical-border shadow-card rounded-lg border">
        <EmptyState icon={CloudOff} title="Can't load the Analytics ranges" description={error.message} />
      </div>
    )
  }
  if (!overview) return <Skeleton className="h-[420px] w-full rounded-lg" />

  return (
    <div className="flex flex-col gap-4">
      <SectionCard
        title="Ranges in effect"
        description="A sample outside its parameter's range is left out of every analysis and counted as out of range. They aren't the monitoring limits."
        icon={Ruler}
      >
        {overview.active && overview.rows ? (
          <div className="flex flex-col gap-3 text-[13px]">
            <p>
              <Badge variant="normal">Analytics ranges v{overview.active.number}</Badge>{' '}
              <span className="text-ink">since {when(overview.active.since)}</span>
              <span className="text-ink-soft"> · “{overview.active.reason}”{overview.active.by && ` · by ${overview.active.by}`}</span>
            </p>
            {overview.problems.length > 0 && (
              <div className="border-warning-border bg-warning-surface rounded-md border px-3 py-2">
                <p className="text-ink flex items-center gap-1.5 font-medium">
                  <TriangleAlert className="text-warning size-4" aria-hidden /> Not applied: the register changed since this file was
                  uploaded. Upload a new one.
                </p>
                <Problems items={overview.problems} />
              </div>
            )}
            <RangeRowsTable rows={overview.rows} />
          </div>
        ) : (
          <div className="text-[13px]">
            <p className="text-ink font-medium">No ranges are in effect, so Analytics excludes no sample as out of range.</p>
            <p className="text-ink-soft mt-1 max-w-3xl">
              Download the template: it lists the {overview.parameters.length} parameters of register {overview.registerVersion} with their
              units. Fill in each one's valid range from process engineering, then upload it.
            </p>
          </div>
        )}
        {overview.scheduled.length > 0 && (
          <ul className="border-line mt-4 flex flex-col gap-1.5 border-t pt-3 text-[13px]">
            {overview.scheduled.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  <CalendarClock className="text-warning size-4" aria-hidden />
                  Analytics ranges v{s.number} take effect {when(s.at)}{' '}
                  <span className="text-ink-soft">· “{s.reason}”{s.by && ` · by ${s.by}`}</span>
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

      {canEdit && <UploadCard overview={overview} onSaved={setOverview} />}

      <SectionCard title="Versions" description="Every uploaded file is kept exactly as it was uploaded" icon={History} flush>
        {overview.versions.length === 0 ? (
          <p className="text-ink-soft px-5 py-4 text-[13px]">No file uploaded yet.</p>
        ) : (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
                <th className="px-5 py-2 font-semibold">Version</th>
                <th className="px-3 py-2 font-semibold">Saved</th>
                <th className="px-3 py-2 font-semibold">File</th>
                <th className="px-3 py-2 font-semibold">Reason</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {overview.versions.map((v) => (
                <tr key={v.number} className="border-line-soft border-b">
                  <td className="px-5 py-2 font-medium">v{v.number}</td>
                  <td className="text-ink-soft px-3 py-2">
                    {when(v.createdAt)}
                    {v.by && <span className="block text-[11px]">by {v.by}</span>}
                  </td>
                  <td className="px-3 py-2">
                    <span className="font-mono text-[12px]">{v.source}</span>
                    <span className="text-ink-muted block font-mono text-[11px]" title={v.sha256}>
                      {v.sha256.slice(0, 12)}…
                    </span>
                  </td>
                  <td className="text-ink px-3 py-2">{v.reason}</td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS_VARIANT[v.status]}>{STATUS_LABELS[v.status]}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <Button type="button" variant="ghost" size="sm" onClick={() => open(v.number, setViewing)}>
                      View
                    </Button>
                    <Button asChild variant="ghost" size="sm">
                      <a href={rangesApi.originalUrl(v.number)} download>
                        <Download className="size-3.5" aria-hidden /> File
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
          <DialogContent className="sm:max-w-[760px]">
            <DialogHeader>
              <DialogTitle>Analytics ranges v{viewing.number}</DialogTitle>
              <DialogDescription>
                {viewing.source}, uploaded {when(viewing.createdAt)}
                {viewing.by ? ` by ${viewing.by}` : ''} against register {viewing.registerVersion} · “{viewing.reason}”
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-3">
              {!viewing.intact && (
                <p className="text-critical text-[13px]">
                  The stored file no longer matches its SHA-256: it was changed outside Centerline. Don't activate it.
                </p>
              )}
              <p className="text-ink-muted font-mono text-[11px]">SHA-256 {viewing.sha256}</p>
              <RangeRowsTable rows={viewing.rows} />
              {viewing.problems.length > 0 && (
                <div>
                  <p className="text-ink text-[13px] font-medium">It no longer fits the register:</p>
                  <Problems items={viewing.problems} />
                </div>
              )}
            </DialogBody>
          </DialogContent>
        </Dialog>
      )}
      {activating && (
        <ActivateDialog
          label="Analytics ranges"
          number={activating.number}
          rollback={overview.versions.find((v) => v.number === activating.number)?.status === 'previous'}
          activeNumber={overview.active?.number ?? null}
          scheduled={overview.scheduled}
          placeholder="e.g. Back to the ranges approved in September"
          blocked={
            !activating.intact
              ? 'Its stored file no longer matches its SHA-256.'
              : activating.problems.length
                ? `It no longer fits the register: ${activating.problems.join('; ')}`
                : null
          }
          details={<RangeRowsTable rows={activating.rows} />}
          onClose={() => setActivating(null)}
          onActivate={async (at, reason) => {
            const next = await rangesApi.activate(activating.number, { expectedActive: overview.active?.number ?? null, at, reason })
            setActivating(null)
            setOverview(next)
            toast.success(
              next.active?.number === activating.number ? `Analytics ranges v${activating.number} are in effect` : `Analytics ranges v${activating.number} scheduled`,
            )
          }}
        />
      )}
      {cancelling && (
        <ReasonDialog
          title={`Cancel the switch to Analytics ranges v${cancelling.number}`}
          description={`It was due ${when(cancelling.at)}. The ranges in effect stay as they are.`}
          confirm="Cancel the switch"
          onClose={() => setCancelling(null)}
          onConfirm={async (reason) => {
            setOverview(await rangesApi.cancelActivation(cancelling.id, reason))
            setCancelling(null)
          }}
        />
      )}
    </div>
  )
}
