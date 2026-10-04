import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Gauge,
  Loader2,
  PauseCircle,
  Plus,
  Save,
  SlidersHorizontal,
  Tag,
  Trash2,
  TriangleAlert,
  Wand2,
  XCircle,
} from 'lucide-react'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { ApiProblem } from '@/services/http'
import { configApi } from '@/services/configApi'
import type {
  BriefChangeMode,
  LatestValue,
  RegisterView,
  RuleDefaults,
  RuleField,
  RuleRow,
  RulesCheck,
  RulesDraft,
  RulesOverview,
  RulesSettings,
} from '@/types/configApi'
import { cn } from '@/utils/cn'
import { fromManilaInput, toUtcIso } from '@/utils/manilaTime'

import { CheckRow, FormField } from '../FormParts'
import { nextHourInput } from '../versionUtils'
import { NumberField } from './NumberField'
import { SkuDialog } from './RuleDialogs'
import {
  BRIEF_LABELS,
  DELAY_FIELDS,
  DELAY_HELP,
  FIELD_LABELS,
  LIMIT_FIELDS,
  fieldError,
  formatValue,
  inherited,
  monitoredParameters,
  setField,
  valueOf,
  type MonitoredParameter,
  type Scope,
} from './ruleModel'

export interface EditorBase {
  /** The version the form starts from; null for the Phase 0 proposal. */
  number: number | null
  source: string
  settings: RulesSettings
  rules: RuleRow[]
}

const INHERIT = '__inherit__'

function placeholderFor(rules: RuleRow[], defaults: RuleDefaults, scope: Scope, field: RuleField, unit?: string | null) {
  const from = inherited(rules, defaults, scope, field)
  if (!from) return '—'
  const where = from.from === 'default' ? 'default' : from.from === 'parameter' ? 'all zones' : from.from === 'sku' ? 'this SKU' : 'this zone'
  return `${formatValue(from.value, unit)} (${where})`
}

/** Edits a new rules version. Nothing changes until it's saved; nothing takes effect until it's activated. */
export function RulesEditor({
  base,
  overview,
  register,
  latest,
  onCancel,
  onSaved,
  onOverview,
}: {
  base: EditorBase
  overview: RulesOverview
  register: RegisterView
  latest: Record<string, LatestValue | null>
  onCancel: () => void
  onSaved: (overview: RulesOverview) => void
  onOverview: (overview: RulesOverview) => void
}) {
  const [settings, setSettings] = useState<RulesSettings>(base.settings)
  const [rules, setRules] = useState<RuleRow[]>(base.rules)
  const [reason, setReason] = useState('')
  const [activate, setActivate] = useState<RulesDraft['activate']>('no')
  const [activateAt, setActivateAt] = useState(nextHourInput)
  const [check, setCheck] = useState<RulesCheck | null>(null)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [skuCode, setSkuCode] = useState<string | null>(overview.skus[0]?.code ?? null)
  const [skuOverrides, setSkuOverrides] = useState(false)
  const [addingSku, setAddingSku] = useState(false)

  const params = useMemo(() => monitoredParameters(register), [register])
  const defaults = settings.defaults
  const skus = overview.skus
  const selectedSku = skus.find((s) => s.code === skuCode) ?? skus[0] ?? null

  const draft = (): RulesDraft => ({
    expectedLatest: overview.latest,
    basedOn: base.number,
    settings,
    rules,
    reason,
    activate,
    activateAt: activate === 'at' ? toUtcIso(fromManilaInput(activateAt) ?? Date.now()) : null,
  })

  // Live check: the api's own validation and readiness, a moment after each change
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      configApi
        .checkRules(
          { expectedLatest: overview.latest, basedOn: base.number, settings, rules, reason: '', activate: 'no', activateAt: null },
          controller.signal,
        )
        .then(setCheck)
        .catch(() => undefined)
    }, 500)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [settings, rules, overview.latest, base.number])

  const errors = problem?.fieldErrors.length ? problem.fieldErrors : (check?.errors ?? [])
  const errorAt = (scope: Scope, field: RuleField) => fieldError(errors, rules, scope, field)
  const update = <F extends RuleField>(scope: Scope, field: F, value: RuleRow[F]) => {
    setProblem(null)
    setRules((list) => setField(list, scope, field, value))
  }
  const setDefault = <K extends keyof RuleDefaults>(key: K, value: RuleDefaults[K]) =>
    setSettings((s) => ({ ...s, defaults: { ...s.defaults, [key]: value } }))

  const known = new Set(params.flatMap((p) => [`${p.id}|*`, ...p.zones.map((z) => `${p.id}|${z.id}`)]))
  const stale = rules.filter(
    (r) => !known.has(`${r.parameterId}|${r.zoneId ?? '*'}`) || (r.sku !== null && !skus.some((s) => s.code === r.sku)),
  )

  const save = async () => {
    setSaving(true)
    setProblem(null)
    try {
      const next = await configApi.saveRules(draft())
      toast.success(`Rules v${next.created} saved`, {
        description: activate === 'no' ? 'Not in effect until you activate it' : activate === 'now' ? 'Now in effect' : 'Activation scheduled',
      })
      onSaved(next)
    } catch (caught) {
      setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
    } finally {
      setSaving(false)
    }
  }

  const limitCells = (p: MonitoredParameter, scope: Scope) =>
    LIMIT_FIELDS.map((f) => (
      <td key={f} className="px-2 py-1.5">
        <NumberField
          value={valueOf(rules, scope, f) as number | null}
          onChange={(v) => update(scope, f, v)}
          label={`${p.name}${scope.zoneId ? ` ${scope.zoneId}` : ''}${scope.sku ? ` SKU ${scope.sku}` : ''} ${FIELD_LABELS[f]}`}
          placeholder={placeholderFor(rules, defaults, scope, f, p.unit)}
          unit={p.unit}
          min={0}
          invalid={Boolean(errorAt(scope, f))}
        />
        {errorAt(scope, f) && <p className="text-critical mt-1 text-[11px] leading-snug">{errorAt(scope, f)}</p>}
      </td>
    ))

  const readinessOf = (code: string) => check?.readiness[code]

  return (
    <div className="flex flex-col gap-4">
      <div className="border-brand/30 bg-brand-surface flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-2.5 text-[13px]">
        <p className="text-ink">
          <b>{overview.latest === null ? 'First rules version' : `New version: Rules v${overview.latest + 1}`}</b>, starting
          from {base.source}. Nothing changes until you save, and nothing takes effect until the version is activated.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Discard
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <SectionCard title="When Actual rules run" description="The stop pause (ADR-0010)" icon={PauseCircle}>
          <div className="flex flex-col gap-3">
            <CheckRow
              checked={settings.pauseWhenStopped.enabled}
              onChange={(enabled) => setSettings((s) => ({ ...s, pauseWhenStopped: { ...s.pauseWhenStopped, enabled } }))}
              label="Pause Actual rules while the machine is stopped"
              description="Warning and Critical timers stop with the machine; HMI mismatch monitoring carries on."
            />
            <div className={cn('flex flex-wrap items-center gap-2 text-[13px]', !settings.pauseWhenStopped.enabled && 'opacity-50')}>
              After a stop of at least
              <NumberField
                value={settings.pauseWhenStopped.longStopMin}
                onChange={(v) => v !== null && setSettings((s) => ({ ...s, pauseWhenStopped: { ...s.pauseWhenStopped, longStopMin: v } }))}
                label="Long stop, minutes"
                unit="min"
                integer
                min={1}
                disabled={!settings.pauseWhenStopped.enabled}
                className="w-24"
              />
              skip the first
              <NumberField
                value={settings.pauseWhenStopped.warmupMin}
                onChange={(v) => v !== null && setSettings((s) => ({ ...s, pauseWhenStopped: { ...s.pauseWhenStopped, warmupMin: v } }))}
                label="Warm-up, minutes"
                unit="min"
                integer
                min={0}
                disabled={!settings.pauseWhenStopped.enabled}
                className="w-24"
              />
              of running (warm-up).
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Defaults" description="For every parameter and SKU, unless set below" icon={Clock}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {DELAY_FIELDS.map((f) => (
              <FormField key={f} label={FIELD_LABELS[f]} hint={DELAY_HELP[f]} error={problem?.forField(`settings.defaults.${f}`)}>
                <NumberField
                  value={defaults[f]}
                  onChange={(v) => v !== null && setDefault(f, v)}
                  label={`Default ${FIELD_LABELS[f]}`}
                  unit="s"
                  integer
                  min={0}
                />
              </FormField>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-1 items-start gap-3 sm:grid-cols-2">
            <FormField label={FIELD_LABELS.briefChangeMode} hint="A setpoint back on target before the mismatch delay ends (HMI-05)">
              <Select value={defaults.briefChangeMode} onValueChange={(v) => setDefault('briefChangeMode', v as BriefChangeMode)}>
                <SelectTrigger size="sm" aria-label="Default for short setpoint changes">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(BRIEF_LABELS) as BriefChangeMode[]).map((m) => (
                    <SelectItem key={m} value={m}>
                      {BRIEF_LABELS[m]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <div className="pt-5">
              <CheckRow
                checked={defaults.warningNotifications}
                onChange={(v) => setDefault('warningNotifications', v)}
                label="Send Warning notifications"
                description="Critical notifications always go out (ACT-03)."
              />
            </div>
          </div>
        </SectionCard>
      </div>

      <SectionCard
        title="Limits by parameter"
        description="For every SKU. Distances from the HMI setpoint (A-02); Critical must be at least as far out as Warning."
        icon={Gauge}
        flush
      >
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
              <th className="px-3 py-2 font-semibold">Parameter</th>
              {LIMIT_FIELDS.map((f) => (
                <th key={f} className="w-[160px] px-2 py-2 font-semibold">
                  {FIELD_LABELS[f]}
                </th>
              ))}
              <th className="w-[150px] px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {params.map((p) => {
              const scope: Scope = { sku: null, parameterId: p.id, zoneId: null }
              const expanded = open.has(p.id)
              const overrides = rules.filter((r) => r.parameterId === p.id && r.sku === null && r.zoneId !== null).length
              return (
                <Fragment key={p.id}>
                  <tr className="border-line-soft border-b align-top">
                    <td className="px-3 py-2">
                      <span className="text-ink font-medium">{p.name}</span>
                      {p.unit && <span className="text-ink-muted"> ({p.unit})</span>}
                      <span className="text-ink-muted ml-2 text-[11px]">
                        {p.id} · {p.zones.length} zone{p.zones.length === 1 ? '' : 's'}
                      </span>
                    </td>
                    {limitCells(p, scope)}
                    <td className="px-2 py-1.5 text-right">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setOpen((s) => {
                            const next = new Set(s)
                            if (next.has(p.id)) next.delete(p.id)
                            else next.add(p.id)
                            return next
                          })
                        }
                        aria-expanded={expanded}
                      >
                        {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                        Delays, zones{overrides > 0 ? ` (${overrides})` : ''}
                      </Button>
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="bg-surface-muted/40 border-line-soft border-b">
                      <td colSpan={6} className="px-4 py-3">
                        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
                          {DELAY_FIELDS.map((f) => (
                            <FormField key={f} label={FIELD_LABELS[f]}>
                              <NumberField
                                value={valueOf(rules, scope, f) as number | null}
                                onChange={(v) => update(scope, f, v)}
                                label={`${p.name} ${FIELD_LABELS[f]}`}
                                placeholder={placeholderFor(rules, defaults, scope, f, 's')}
                                unit="s"
                                integer
                                min={0}
                              />
                            </FormField>
                          ))}
                          <FormField label={FIELD_LABELS.briefChangeMode}>
                            <Select
                              value={(valueOf(rules, scope, 'briefChangeMode') as string | null) ?? INHERIT}
                              onValueChange={(v) => update(scope, 'briefChangeMode', v === INHERIT ? null : (v as BriefChangeMode))}
                            >
                              <SelectTrigger size="sm" aria-label={`${p.name} short setpoint changes`}>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={INHERIT}>Default ({BRIEF_LABELS[defaults.briefChangeMode]})</SelectItem>
                                {(Object.keys(BRIEF_LABELS) as BriefChangeMode[]).map((m) => (
                                  <SelectItem key={m} value={m}>
                                    {BRIEF_LABELS[m]}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </FormField>
                          <FormField label={FIELD_LABELS.warningNotifications}>
                            <Select
                              value={
                                valueOf(rules, scope, 'warningNotifications') === null
                                  ? INHERIT
                                  : String(valueOf(rules, scope, 'warningNotifications'))
                              }
                              onValueChange={(v) => update(scope, 'warningNotifications', v === INHERIT ? null : v === 'true')}
                            >
                              <SelectTrigger size="sm" aria-label={`${p.name} Warning notifications`}>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={INHERIT}>Default ({defaults.warningNotifications ? 'on' : 'off'})</SelectItem>
                                <SelectItem value="true">On</SelectItem>
                                <SelectItem value="false">Off</SelectItem>
                              </SelectContent>
                            </Select>
                          </FormField>
                        </div>
                        <p className="micro-label mt-4 mb-1">Zone overrides (blank: as the whole parameter)</p>
                        <table className="w-full text-[13px]">
                          <tbody>
                            {p.zones.map((z) => (
                              <tr key={z.id} className="align-top">
                                <td className="text-ink py-1.5 pr-3">
                                  {z.name} <span className="text-ink-muted font-mono text-[11px]">{z.id}</span>
                                </td>
                                {limitCells(p, { sku: null, parameterId: p.id, zoneId: z.id })}
                                <td className="w-[150px]" />
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </SectionCard>

      <SectionCard
        title="SKUs and targets"
        description="The target each zone should run at, per SKU (A-01). A SKU is monitored only once every zone has a target and limits."
        icon={Tag}
        actions={
          <Button type="button" variant="outline" size="sm" onClick={() => setAddingSku(true)}>
            <Plus className="size-3.5" aria-hidden /> Add SKU
          </Button>
        }
      >
        {skus.length === 0 ? (
          <p className="text-ink-soft text-[13px]">
            No SKUs yet. Add the SKUs the line runs, with the codes the machine will publish (O-15), then enter their targets
            from process engineering's centerline sheets.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="SKU">
              {skus.map((s) => {
                const gaps = readinessOf(s.code)
                return (
                  <button
                    key={s.code}
                    type="button"
                    role="tab"
                    aria-selected={selectedSku?.code === s.code}
                    onClick={() => setSkuCode(s.code)}
                    className={cn(
                      'border-line flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[13px]',
                      selectedSku?.code === s.code ? 'bg-brand-surface border-brand/40 text-ink' : 'bg-surface text-ink-soft hover:bg-surface-muted',
                    )}
                  >
                    {gaps === undefined ? null : gaps.length === 0 ? (
                      <CheckCircle2 className="text-normal size-3.5" aria-label="ready" />
                    ) : (
                      <TriangleAlert className="text-warning size-3.5" aria-label={`${gaps.length} zones incomplete`} />
                    )}
                    <span className="font-mono">{s.code}</span>
                    <span className="max-w-[180px] truncate">{s.name}</span>
                  </button>
                )
              })}
            </div>

            {selectedSku && (
              <SkuTargets
                sku={selectedSku.code}
                params={params}
                rules={rules}
                defaults={defaults}
                latest={latest}
                gaps={readinessOf(selectedSku.code)}
                errorAt={errorAt}
                update={update}
                onFill={(filled) => setRules(filled)}
              />
            )}

            {selectedSku && (
              <div>
                <Button type="button" variant="ghost" size="sm" onClick={() => setSkuOverrides((o) => !o)} aria-expanded={skuOverrides}>
                  {skuOverrides ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                  Different limits or short-change handling for {selectedSku.code}
                </Button>
                {skuOverrides && (
                  <table className="mt-1 w-full text-[13px]">
                    <thead>
                      <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
                        <th className="px-3 py-2 font-semibold">Parameter</th>
                        {LIMIT_FIELDS.map((f) => (
                          <th key={f} className="w-[160px] px-2 py-2 font-semibold">
                            {FIELD_LABELS[f]}
                          </th>
                        ))}
                        <th className="w-[210px] px-2 py-2 font-semibold">{FIELD_LABELS.briefChangeMode}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {params.map((p) => {
                        const scope: Scope = { sku: selectedSku.code, parameterId: p.id, zoneId: null }
                        const mode = valueOf(rules, scope, 'briefChangeMode') as string | null
                        const inheritedMode = inherited(rules, defaults, scope, 'briefChangeMode')
                        return (
                          <tr key={p.id} className="border-line-soft border-b align-top">
                            <td className="px-3 py-2">{p.name}</td>
                            {limitCells(p, scope)}
                            <td className="px-2 py-1.5">
                              <Select
                                value={mode ?? INHERIT}
                                onValueChange={(v) => update(scope, 'briefChangeMode', v === INHERIT ? null : (v as BriefChangeMode))}
                              >
                                <SelectTrigger size="sm" aria-label={`${p.name} short setpoint changes for ${selectedSku.code}`}>
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value={INHERIT}>As every SKU ({formatValue(inheritedMode?.value)})</SelectItem>
                                  {(Object.keys(BRIEF_LABELS) as BriefChangeMode[]).map((m) => (
                                    <SelectItem key={m} value={m}>
                                      {BRIEF_LABELS[m]}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        )}
      </SectionCard>

      {stale.length > 0 && (
        <SectionCard
          title="Rows the register no longer has"
          description="Rules for zones, parameters or SKUs that aren't monitored any more. Remove them before saving."
          icon={TriangleAlert}
        >
          <ul className="flex flex-col gap-1.5 text-[13px]">
            {stale.map((r) => (
              <li key={`${r.sku}|${r.parameterId}|${r.zoneId}`} className="flex items-center justify-between gap-2">
                <span>
                  {r.parameterId} · {r.zoneId ?? 'every zone'} · {r.sku ? `SKU ${r.sku}` : 'every SKU'}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setRules((list) => list.filter((x) => !(x.parameterId === r.parameterId && x.zoneId === r.zoneId && x.sku === r.sku)))
                  }
                >
                  <Trash2 className="size-3.5" aria-hidden /> Remove
                </Button>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      <SectionCard title="Save" description="A new version, kept for good; the one in effect stays until you activate another" icon={Save}>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
          <FormField label="Reason for the change" error={problem?.forField('reason')} hint="Required. Kept with the version.">
            <Textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Limits confirmed by process engineering on 1 Oct"
              className="text-[13px]"
              aria-label="Reason for the change"
            />
          </FormField>
          <fieldset className="flex flex-col gap-2 text-[13px]">
            <legend className="micro-label mb-1.5">After saving</legend>
            <label className="flex items-center gap-2">
              <input type="radio" name="activate" checked={activate === 'no'} onChange={() => setActivate('no')} />
              Keep it saved; activate later
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="activate" checked={activate === 'now'} onChange={() => setActivate('now')} />
              Activate now
            </label>
            <label className="flex flex-wrap items-center gap-2">
              <input type="radio" name="activate" checked={activate === 'at'} onChange={() => setActivate('at')} />
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
            {problem?.forField('activateAt') && <p className="text-critical text-[12px]">{problem.forField('activateAt')}</p>}
          </fieldset>
        </div>

        {(errors.length > 0 || (problem && problem.fieldErrors.length === 0)) && (
          <div className="border-critical-border bg-critical-surface mt-4 rounded-md border px-3 py-2 text-[13px]">
            {problem && problem.fieldErrors.length === 0 ? (
              <p className="text-critical flex items-center gap-1.5">
                <XCircle className="size-4 shrink-0" aria-hidden /> {problem.message}
              </p>
            ) : (
              <>
                <p className="text-critical font-medium">
                  {errors.length} thing{errors.length === 1 ? '' : 's'} to fix before saving:
                </p>
                <ul className="text-ink mt-1 list-disc pl-5 text-[12px]">
                  {errors.slice(0, 8).map((e) => (
                    <li key={e.field + e.message}>{e.message}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onCancel}>
            Discard
          </Button>
          <Button type="button" size="sm" disabled={saving} onClick={() => void save()}>
            {saving ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />}
            {activate === 'no' ? 'Save version' : activate === 'now' ? 'Save and activate' : 'Save and schedule'}
          </Button>
        </div>
      </SectionCard>

      {addingSku && (
        <SkuDialog
          sku={null}
          onClose={() => setAddingSku(false)}
          onSaved={(next) => {
            onOverview(next)
            setAddingSku(false)
            const added = next.skus.find((s) => !skus.some((old) => old.code === s.code))
            if (added) setSkuCode(added.code)
          }}
        />
      )}
    </div>
  )
}

function SkuTargets({
  sku,
  params,
  rules,
  defaults,
  latest,
  gaps,
  errorAt,
  update,
  onFill,
}: {
  sku: string
  params: MonitoredParameter[]
  rules: RuleRow[]
  defaults: RuleDefaults
  latest: Record<string, LatestValue | null>
  gaps: { zoneId: string; parameterId: string; missing: RuleField[] }[] | undefined
  errorAt: (scope: Scope, field: RuleField) => string | undefined
  update: <F extends RuleField>(scope: Scope, field: F, value: RuleRow[F]) => void
  onFill: (rules: RuleRow[]) => void
}) {
  const hmi = (tag: string) => {
    const v = latest[tag]?.value
    return typeof v === 'number' ? v : null
  }

  const fill = () => {
    let next = rules
    let n = 0
    for (const p of params) {
      for (const z of p.zones) {
        const scope: Scope = { sku, parameterId: p.id, zoneId: z.id }
        const value = hmi(z.setpoint)
        if (value !== null && valueOf(next, scope, 'target') === null && inherited(next, defaults, scope, 'target') === null) {
          next = setField(next, scope, 'target', value)
          n += 1
        }
      }
    }
    onFill(next)
    toast.info(n ? `${n} target${n === 1 ? '' : 's'} filled from the current HMI setpoints` : 'No empty targets to fill', {
      description: n ? 'Check them against the centerline sheet: the HMI shows what is dialled in, not what should be.' : undefined,
    })
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-ink-soft text-[12px]">
          {gaps === undefined
            ? 'Checking…'
            : gaps.length === 0
              ? `${sku} is ready: every zone has a target and limits.`
              : `${sku}: ${gaps.length} zone${gaps.length === 1 ? '' : 's'} still need a target or limits. Monitoring pauses while it runs.`}
        </p>
        <Button type="button" variant="outline" size="sm" onClick={fill}>
          <Wand2 className="size-3.5" aria-hidden /> Fill empty targets from current HMI setpoints
        </Button>
      </div>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
            <th className="px-3 py-2 font-semibold">Zone</th>
            <th className="w-[140px] px-2 py-2 text-right font-semibold">HMI setpoint now</th>
            <th className="w-[200px] px-2 py-2 font-semibold">Target for {sku}</th>
            <th className="px-2 py-2 font-semibold" />
          </tr>
        </thead>
        <tbody>
          {params.map((p) => {
            const all: Scope = { sku, parameterId: p.id, zoneId: null }
            return (
              <Fragment key={p.id}>
                <tr className="bg-surface-muted/50 border-line-soft border-b">
                  <td className="px-3 py-1.5 font-medium" colSpan={2}>
                    {p.name}
                    {p.unit && <span className="text-ink-muted font-normal"> ({p.unit})</span>}
                  </td>
                  <td className="px-2 py-1.5">
                    <NumberField
                      value={valueOf(rules, all, 'target') as number | null}
                      onChange={(v) => update(all, 'target', v)}
                      label={`${p.name} target for every zone, SKU ${sku}`}
                      placeholder="Same for every zone"
                      unit={p.unit}
                      invalid={Boolean(errorAt(all, 'target'))}
                    />
                  </td>
                  <td className="text-ink-muted px-2 py-1.5 text-[11px]">optional: one target for all its zones</td>
                </tr>
                {p.zones.map((z) => {
                  const scope: Scope = { sku, parameterId: p.id, zoneId: z.id }
                  const gap = gaps?.find((g) => g.parameterId === p.id && g.zoneId === z.id)
                  const now = hmi(z.setpoint)
                  return (
                    <tr key={z.id} className="border-line-soft border-b">
                      <td className="py-1.5 pr-3 pl-6">
                        {z.name} <span className="text-ink-muted font-mono text-[11px]">{z.id}</span>
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-[12px] tabular-nums">
                        {now === null ? '—' : `${now}${p.unit ? ` ${p.unit}` : ''}`}
                      </td>
                      <td className="px-2 py-1.5">
                        <NumberField
                          value={valueOf(rules, scope, 'target') as number | null}
                          onChange={(v) => update(scope, 'target', v)}
                          label={`${z.name} target, SKU ${sku}`}
                          placeholder={placeholderFor(rules, defaults, scope, 'target', p.unit)}
                          unit={p.unit}
                          invalid={Boolean(errorAt(scope, 'target'))}
                        />
                      </td>
                      <td className="px-2 py-1.5 text-[11px]">
                        {gap ? (
                          <span className="text-warning inline-flex items-center gap-1">
                            <TriangleAlert className="size-3" aria-hidden />
                            no {gap.missing.includes('target') ? 'target' : ''}
                            {gap.missing.includes('target') && gap.missing.length > 1 ? ' or ' : ''}
                            {gap.missing.some((f) => f !== 'target') ? 'limits' : ''}
                          </span>
                        ) : gaps ? (
                          <span className="text-normal inline-flex items-center gap-1">
                            <SlidersHorizontal className="size-3" aria-hidden /> set
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  )
                })}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
