import { ArrowLeftRight, Loader2, Play, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { AnalysisForm } from '@/hooks/useCorrelationAnalysis'
import type {
  AggregationCode,
  AnalyticsOptions,
  AnalyticsVariable,
  BucketCode,
  GroupByCode,
  ShiftCode,
  VariableKind,
} from '@/types/analyticsApi'
import { cn } from '@/utils/cn'
import { fromManilaInput, toManilaInput } from '@/utils/manilaTime'

interface AnalysisQueryPanelProps {
  options: AnalyticsOptions
  form: AnalysisForm
  onChange: (patch: Partial<AnalysisForm>) => void
  onRun: () => void
  running: boolean
  fieldErrors: { field: string; message: string }[]
}

export function AnalysisQueryPanel({
  options,
  form,
  onChange,
  onRun,
  running,
  fieldErrors,
}: AnalysisQueryPanelProps) {
  const same = form.x !== '' && form.x === form.y
  const errorFor = (field: string) =>
    field === 'y' && same
      ? 'X and Y must be different: pick another zone, or Actual against Setpoint'
      : fieldErrors.find((e) => e.field === field)?.message
  const groups = groupZones(options.variables)
  const presets = [
    { label: '24 h', hours: 24 },
    { label: '7 days', hours: 24 * 7 },
    { label: `${options.limits.maxRangeDays} days`, hours: 24 * options.limits.maxRangeDays },
  ]

  return (
    <form
      className="bg-surface border-line shadow-card rounded-lg border"
      onSubmit={(event) => {
        event.preventDefault()
        onRun()
      }}
    >
      <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-[1fr_auto_1fr]">
        <Field label="X variable" error={errorFor('x')}>
          <VariablePicker
            label="X"
            value={form.x}
            variables={options.variables}
            groups={groups}
            onChange={(x) => onChange({ x })}
          />
        </Field>
        <div className="flex items-end justify-center">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Swap X and Y"
            title="Swap X and Y"
            onClick={() => onChange({ x: form.y, y: form.x })}
          >
            <ArrowLeftRight className="size-4" aria-hidden />
          </Button>
        </div>
        <Field label="Y variable" error={errorFor('y')}>
          <VariablePicker
            label="Y"
            value={form.y}
            variables={options.variables}
            groups={groups}
            onChange={(y) => onChange({ y })}
          />
        </Field>
      </div>

      <div className="border-line grid grid-cols-1 gap-3 border-t p-4 sm:grid-cols-2 lg:grid-cols-[minmax(210px,1fr)_minmax(210px,1fr)_auto]">
        <Field label="From (Manila)" error={errorFor('from')}>
          <Input
            type="datetime-local"
            value={toManilaInput(form.fromMs)}
            onChange={(event) => {
              const ms = fromManilaInput(event.target.value)
              if (ms !== null) onChange({ fromMs: ms })
            }}
            className="h-8 text-[13px]"
            aria-label="From, Manila time"
          />
        </Field>
        <Field label="To (Manila)" error={errorFor('to')}>
          <Input
            type="datetime-local"
            value={toManilaInput(form.toMs)}
            onChange={(event) => {
              const ms = fromManilaInput(event.target.value)
              if (ms !== null) onChange({ toMs: ms })
            }}
            className="h-8 text-[13px]"
            aria-label="To, Manila time"
          />
        </Field>
        <Field label="Quick range">
          <div className="flex gap-1">
            {presets.map((preset) => (
              <Button
                key={preset.label}
                type="button"
                variant="outline"
                size="sm"
                className="flex-1 px-2.5 whitespace-nowrap"
                onClick={() => {
                  const now = Date.now()
                  onChange({ fromMs: now - preset.hours * 3_600_000, toMs: now })
                }}
              >
                {preset.label}
              </Button>
            ))}
          </div>
        </Field>
      </div>

      <div className="border-line grid grid-cols-1 gap-3 border-t p-4 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Shift">
          <SimpleSelect<ShiftCode>
            label="Shift"
            value={form.shift}
            items={options.shifts}
            onChange={(shift) => onChange({ shift })}
          />
        </Field>
        <Field label="Bucket">
          <SimpleSelect<BucketCode>
            label="Bucket"
            value={form.bucket}
            items={options.buckets}
            onChange={(bucket) => onChange({ bucket })}
          />
        </Field>
        <Field label="Aggregation">
          <SimpleSelect<AggregationCode>
            label="Aggregation"
            value={form.aggregation}
            items={options.aggregations}
            onChange={(aggregation) => onChange({ aggregation })}
          />
        </Field>
        <Field label="Group scatter by">
          <SimpleSelect<GroupByCode>
            label="Group scatter by"
            value={form.groupBy}
            items={options.groupings}
            onChange={(groupBy) => onChange({ groupBy, groupStats: groupBy === 'NONE' ? false : form.groupStats })}
          />
        </Field>
        <Field label="SKU" error={errorFor('sku')}>
          <Select value="ALL" disabled>
            <SelectTrigger size="sm" aria-label="SKU" title={options.sku.reason ?? undefined}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All products</SelectItem>
            </SelectContent>
          </Select>
        </Field>
      </div>

      <div className="border-line flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
        <div className="flex flex-wrap items-center gap-4">
          <label
            className={cn(
              'text-ink-soft flex items-center gap-2 text-[13px]',
              form.groupBy === 'NONE' && 'opacity-50',
            )}
          >
            <Checkbox
              checked={form.groupStats}
              disabled={form.groupBy === 'NONE'}
              onCheckedChange={(checked) => onChange({ groupStats: checked === true })}
            />
            Show statistics by group
          </label>
          {!options.sku.available && (
            <span className="text-ink-muted flex items-center gap-1.5 text-[12px]">
              <TriangleAlert className="text-warning size-3.5" aria-hidden />
              No SKU tag in Timebase yet: results cover every product
            </span>
          )}
        </div>
        <Button type="submit" size="sm" disabled={running || !form.x || !form.y || same}>
          {running ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Play className="size-4" aria-hidden />
          )}
          {running ? 'Analysing…' : 'Analyse'}
        </Button>
      </div>
    </form>
  )
}

interface ZoneOption {
  zoneChannel: string
  zoneName: string
  hasSetpoint: boolean
  caution: boolean
}

interface ZoneGroup {
  parameterName: string
  unit: string | null
  zones: ZoneOption[]
}

/** Zones grouped under their parameter's name ("Vertical Temperature"); no parameter IDs (ADR-0009). */
function groupZones(variables: AnalyticsVariable[]): ZoneGroup[] {
  const groups = new Map<string, ZoneGroup>()
  for (const v of variables) {
    const group = groups.get(v.parameterId) ?? { parameterName: v.parameterName, unit: v.unit, zones: [] }
    let zone = group.zones.find((z) => z.zoneChannel === v.zoneChannel)
    if (!zone) {
      zone = { zoneChannel: v.zoneChannel, zoneName: v.zoneName, hasSetpoint: false, caution: Boolean(v.caution) }
      group.zones.push(zone)
    }
    if (v.kind === 'setpoint') zone.hasSetpoint = true
    groups.set(v.parameterId, group)
  }
  return [...groups.values()]
}

/** A zone ("Vertical 1") plus whether to use its actual value or its setpoint. */
function VariablePicker({
  label,
  value,
  variables,
  groups,
  onChange,
}: {
  label: string
  value: string
  variables: AnalyticsVariable[]
  groups: ZoneGroup[]
  onChange: (channel: string) => void
}) {
  const current = variables.find((v) => v.channel === value)
  const zone = groups.flatMap((g) => g.zones).find((z) => z.zoneChannel === current?.zoneChannel)
  const pick = (zoneChannel: string, kind: VariableKind) => {
    const target =
      variables.find((v) => v.zoneChannel === zoneChannel && v.kind === kind) ??
      variables.find((v) => v.zoneChannel === zoneChannel && v.kind === 'actual')
    if (target) onChange(target.channel)
  }
  return (
    <div className="flex gap-2">
      <Select value={current?.zoneChannel ?? ''} onValueChange={(zc) => pick(zc, current?.kind ?? 'actual')}>
        <SelectTrigger size="sm" aria-label={`${label} zone`} className="min-w-0 flex-1">
          <SelectValue placeholder="Choose a zone" />
        </SelectTrigger>
        <SelectContent>
          {groups.map((group) => (
            <SelectGroup key={group.parameterName}>
              <SelectLabel>
                {group.parameterName}
                {group.unit ? ` (${group.unit})` : ''}
              </SelectLabel>
              {group.zones.map((z) => (
                <SelectItem key={z.zoneChannel} value={z.zoneChannel}>
                  {z.zoneName}
                  {z.caution ? ' · under review' : ''}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
      <KindToggle
        label={label}
        value={current?.kind ?? 'actual'}
        hasSetpoint={Boolean(zone?.hasSetpoint)}
        onChange={(kind) => current && pick(current.zoneChannel, kind)}
      />
    </div>
  )
}

const KINDS: { kind: VariableKind; text: string }[] = [
  { kind: 'actual', text: 'Actual' },
  { kind: 'setpoint', text: 'Setpoint' },
]

function KindToggle({
  label,
  value,
  hasSetpoint,
  onChange,
}: {
  label: string
  value: VariableKind
  hasSetpoint: boolean
  onChange: (kind: VariableKind) => void
}) {
  return (
    <div
      role="group"
      aria-label={`${label}: actual value or setpoint`}
      className="border-line bg-surface-muted inline-flex h-8 shrink-0 rounded-md border p-0.5"
    >
      {KINDS.map(({ kind, text }) => {
        const disabled = kind === 'setpoint' && !hasSetpoint
        const active = value === kind
        return (
          <button
            key={kind}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            title={disabled ? 'This zone has no setpoint tag yet' : undefined}
            onClick={() => onChange(kind)}
            className={cn(
              'focus-visible:ring-brand-ring rounded px-2.5 text-[12px] font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none',
              active ? 'bg-surface text-ink shadow-card' : 'text-ink-soft hover:text-ink',
              disabled && 'hover:text-ink-soft cursor-not-allowed opacity-40',
            )}
          >
            {text}
          </button>
        )
      })}
    </div>
  )
}

function SimpleSelect<T extends string>({
  label,
  value,
  items,
  onChange,
}: {
  label: string
  value: T
  items: { code: T; label: string }[]
  onChange: (value: T) => void
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger size="sm" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.code} value={item.code}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <span className="micro-label mb-1.5 block">{label}</span>
      {children}
      {error && <p className="text-critical mt-1 text-[12px] leading-snug">{error}</p>}
    </div>
  )
}
