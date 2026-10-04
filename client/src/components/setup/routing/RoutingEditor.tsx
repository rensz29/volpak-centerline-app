import { Loader2, Plus, Save, Trash2, TriangleAlert, XCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { ApiProblem } from '@/services/http'
import { notificationsApi } from '@/services/notificationsApi'
import type { Channel, RoutingCheck, RoutingDraft, RoutingOverview, RoutingRule } from '@/types/notificationsApi'
import { cn } from '@/utils/cn'
import { fromManilaInput, toUtcIso } from '@/utils/manilaTime'

import { FormField } from '../FormParts'
import { asProblem, nextHourInput } from '../versionUtils'

export interface RoutingBase {
  /** The version the form starts from; null for the proposal. */
  number: number | null
  source: string
  rules: RoutingRule[]
}

interface RuleForm {
  key: number
  name: string
  channel: Channel
  types: string[]
  targets: string
}

let nextKey = 1
const toForm = (r: RoutingRule): RuleForm => ({ key: nextKey++, name: r.name, channel: r.channel, types: r.types, targets: r.targets.join('\n') })
const toRule = (f: RuleForm): RoutingRule => ({
  name: f.name,
  channel: f.channel,
  types: f.types,
  targets: f.targets.split(/[\n,;]/).map((t) => t.trim()).filter(Boolean),
})

/** Edits a new routing version: who gets which messages, on which channel (ADR-0023). */
export function RoutingEditor({
  base,
  overview,
  onCancel,
  onSaved,
}: {
  base: RoutingBase
  overview: RoutingOverview
  onCancel: () => void
  onSaved: (overview: RoutingOverview) => void
}) {
  const [rules, setRules] = useState<RuleForm[]>(() => base.rules.map(toForm))
  const [reason, setReason] = useState('')
  const [activate, setActivate] = useState<RoutingDraft['activate']>('no')
  const [activateAt, setActivateAt] = useState(nextHourInput)
  const [check, setCheck] = useState<RoutingCheck | null>(null)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [saving, setSaving] = useState(false)
  const draftRules = useMemo(() => rules.map(toRule), [rules])

  const draftOf = (extra: Partial<RoutingDraft> = {}): RoutingDraft => ({
    expectedLatest: overview.latest,
    basedOn: base.number,
    rules: draftRules,
    reason: '',
    activate: 'no',
    activateAt: null,
    ...extra,
  })

  // Live check: the api's validation and warnings, a moment after each change
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      notificationsApi
        .checkRouting(
          { expectedLatest: overview.latest, basedOn: base.number, rules: draftRules, reason: '', activate: 'no', activateAt: null },
          controller.signal,
        )
        .then(setCheck)
        .catch(() => undefined)
    }, 400)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [draftRules, overview.latest, base.number])

  const errors = problem?.fieldErrors.length ? problem.fieldErrors : (check?.errors ?? [])
  const errorAt = (i: number, field: string) => errors.find((e) => e.field === `rules[${i}].${field}`)?.message
  const criticalGap = (check?.warnings ?? []).find((w) => w.includes('ACT-03'))
  const set = (key: number, patch: Partial<RuleForm>) => setRules((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const save = async () => {
    setSaving(true)
    setProblem(null)
    try {
      const at = activate === 'at' ? fromManilaInput(activateAt) : null
      const next = await notificationsApi.saveRouting(draftOf({ reason, activate, activateAt: at === null ? null : toUtcIso(at) }))
      toast.success(`Routing v${next.created} saved`, {
        description: activate === 'no' ? 'Not in effect until you activate it' : activate === 'now' ? 'Now in effect' : 'Activation scheduled',
      })
      onSaved(next)
    } catch (caught) {
      setProblem(asProblem(caught))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="border-brand/30 bg-brand-surface flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-2.5 text-[13px]">
        <p className="text-ink">
          <b>{overview.latest === null ? 'First routing' : `New version: Routing v${overview.latest + 1}`}</b>, starting from {base.source}.
          Nothing changes until you save, and nothing takes effect until the version is activated.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Discard
        </Button>
      </div>

      {rules.map((r, i) => (
        <SectionCard
          key={r.key}
          title={r.name.trim() || `Rule ${i + 1}`}
          description={r.channel === 'teams' ? 'Posted in Teams by the flow' : 'Sent through the SMTP relay'}
          actions={
            <Button type="button" variant="ghost" size="sm" className="text-critical" onClick={() => setRules((rs) => rs.filter((x) => x.key !== r.key))}>
              <Trash2 className="size-3.5" aria-hidden /> Remove
            </Button>
          }
        >
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-[1fr_140px] gap-3">
                <FormField label="Name" error={errorAt(i, 'name')}>
                  <Input value={r.name} onChange={(e) => set(r.key, { name: e.target.value })} placeholder="e.g. Management by email"
                         className="h-8 text-[13px]" aria-label={`Rule ${i + 1} name`} />
                </FormField>
                <FormField label="Channel" error={errorAt(i, 'channel')}>
                  <Select value={r.channel} onValueChange={(v) => set(r.key, { channel: v as Channel })}>
                    <SelectTrigger size="sm" aria-label={`Rule ${i + 1} channel`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {overview.channels.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormField>
              </div>
              <FormField
                label={r.channel === 'teams' ? 'Teams channels or chats, one a line' : 'Email addresses, one a line'}
                error={errorAt(i, 'targets')}
                hint={r.channel === 'teams' ? 'The flow decides where each name posts (O-05)' : undefined}
              >
                <Textarea rows={3} value={r.targets} onChange={(e) => set(r.key, { targets: e.target.value })}
                          placeholder={r.channel === 'teams' ? 'Centerline alerts' : 'shift.leads@plant.local'}
                          className="font-mono text-[12px]" aria-label={`Rule ${i + 1} recipients`} />
              </FormField>
            </div>
            <fieldset>
              <legend className="micro-label mb-1.5">Sends</legend>
              {errorAt(i, 'types') && <p className="text-critical mb-1 text-[12px]">{errorAt(i, 'types')}</p>}
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {overview.types.map((t) => (
                  <label key={t.id} className="flex items-center gap-2 text-[13px]">
                    <Checkbox
                      checked={r.types.includes(t.id)}
                      onCheckedChange={(on) =>
                        set(r.key, { types: on === true ? [...r.types, t.id] : r.types.filter((x) => x !== t.id) })
                      }
                    />
                    <span>{t.label}</span>
                    {t.critical && <span className="text-critical text-[11px] font-medium">Critical</span>}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        </SectionCard>
      ))}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => setRules((rs) => [...rs, toForm({ name: '', channel: 'email', types: overview.types.map((t) => t.id), targets: [] })])}
      >
        <Plus className="size-4" aria-hidden /> Add a rule
      </Button>

      <SectionCard title="Save" description="A new version, kept for good; the routing in effect stays until you activate another" icon={Save}>
        {check && check.warnings.length > 0 && (
          <ul className="text-warning mb-3 flex flex-col gap-1 text-[12px]">
            {check.warnings.map((w) => (
              <li key={w} className="flex items-start gap-1.5">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {w}
              </li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
          <FormField label="Reason for the change" error={problem?.forField('reason')} hint="Required. Kept with the version.">
            <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Addresses from IT, 1 Oct"
                      className="text-[13px]" aria-label="Reason for the change" />
          </FormField>
          <fieldset className="flex flex-col gap-2 text-[13px]">
            <legend className="micro-label mb-1.5">After saving</legend>
            <label className="flex items-center gap-2">
              <input type="radio" name="activate" checked={activate === 'no'} onChange={() => setActivate('no')} />
              Keep it saved; activate later
            </label>
            <label className={cn('flex items-center gap-2', criticalGap && 'opacity-50')}>
              <input type="radio" name="activate" disabled={Boolean(criticalGap)} checked={activate === 'now'} onChange={() => setActivate('now')} />
              Activate now
            </label>
            <label className={cn('flex flex-wrap items-center gap-2', criticalGap && 'opacity-50')}>
              <input type="radio" name="activate" disabled={Boolean(criticalGap)} checked={activate === 'at'} onChange={() => setActivate('at')} />
              Activate at
              <Input
                type="datetime-local"
                value={activateAt}
                disabled={Boolean(criticalGap)}
                onChange={(e) => {
                  setActivateAt(e.target.value)
                  setActivate('at')
                }}
                className="h-8 w-auto text-[13px]"
                aria-label="Activation time, Manila"
              />
              <span className="text-ink-muted text-[12px]">Manila</span>
            </label>
            {criticalGap && <p className="text-ink-muted text-[12px]">Activating needs every kind of Critical sent to someone (ACT-03).</p>}
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
    </div>
  )
}
