import type {
  BriefChangeMode,
  RegisterView,
  RuleDefaults,
  RuleField,
  RuleRow,
  RulesProposal,
  RulesVersionStatus,
} from '@/types/configApi'

/**
 * Client-side helpers for the Rules tab (ADR-0012). The api is the authority on
 * validation and readiness; the layering here only shows what a blank field
 * inherits: this zone > every zone of the parameter > line defaults
 * (services/common/centerline_common/rules.py, ADR-0027).
 */

export const LIMIT_FIELDS = ['warnLow', 'warnHigh', 'critLow', 'critHigh'] as const
export const DELAY_FIELDS = ['mismatchDelayS', 'warningDelayS', 'criticalDelayS', 'recoveryDelayS'] as const
export const RULE_FIELDS: RuleField[] = [
  'target',
  ...LIMIT_FIELDS,
  ...DELAY_FIELDS,
  'briefChangeMode',
  'warningNotifications',
]

export const FIELD_LABELS: Record<RuleField, string> = {
  target: 'Target',
  // Distances from the HMI setpoint (A-02), not temperatures: say so in the label itself
  warnLow: 'Warning: setpoint −',
  warnHigh: 'Warning: setpoint +',
  critLow: 'Critical: setpoint −',
  critHigh: 'Critical: setpoint +',
  mismatchDelayS: 'HMI mismatch delay',
  warningDelayS: 'Warning delay',
  criticalDelayS: 'Critical delay',
  recoveryDelayS: 'Recovery delay',
  briefChangeMode: 'Short setpoint changes',
  warningNotifications: 'Warning notifications',
}

export const DELAY_HELP: Record<(typeof DELAY_FIELDS)[number], string> = {
  mismatchDelayS: 'HMI setpoint off target this long before an event opens',
  warningDelayS: 'In the Warning band this long before a Warning; also Critical → Warning',
  criticalDelayS: 'In the Critical band this long before a Critical',
  recoveryDelayS: 'Back in the Normal band this long before recovery (URS default 15 s)',
}

export const BRIEF_LABELS: Record<BriefChangeMode, string> = {
  lightweight: 'Lightweight record',
  cleared_before_trigger: 'Full record, cleared before trigger',
  do_not_record: 'Do not record',
}

export const STATUS_LABELS: Record<RulesVersionStatus, string> = {
  active: 'In effect',
  scheduled: 'Scheduled',
  previous: 'Was in effect',
  saved: 'Saved, never activated',
}

export interface MonitoredParameter {
  id: string
  name: string
  unit: string | null
  zones: { id: string; name: string; setpoint: string; actual: string }[]
}

/** Parameters the rules apply to: Monitored, with a setpoint and an actual tag per zone. */
export function monitoredParameters(register: RegisterView): MonitoredParameter[] {
  return register.parameters
    .filter((p) => p.status === 'active')
    .map((p) => ({
      id: p.id,
      name: p.name,
      unit: p.unit,
      zones: p.zones.flatMap((z) => (z.setpoint && z.actual ? [{ id: z.id, name: z.name, setpoint: z.setpoint, actual: z.actual }] : [])),
    }))
    .filter((p) => p.zones.length > 0)
}

export interface Scope {
  parameterId: string
  zoneId: string | null
}

export function emptyRow(scope: Scope): RuleRow {
  return {
    ...scope,
    target: null,
    warnLow: null,
    warnHigh: null,
    critLow: null,
    critHigh: null,
    mismatchDelayS: null,
    warningDelayS: null,
    criticalDelayS: null,
    recoveryDelayS: null,
    briefChangeMode: null,
    warningNotifications: null,
  }
}

const same = (r: RuleRow, s: Scope) => r.parameterId === s.parameterId && r.zoneId === s.zoneId

export function rowIndex(rules: RuleRow[], scope: Scope): number {
  return rules.findIndex((r) => same(r, scope))
}

export function isEmpty(row: RuleRow): boolean {
  return RULE_FIELDS.every((f) => row[f] === null)
}

/** Set one field of one scope, adding the row when needed and dropping it once it's empty. */
export function setField<F extends RuleField>(rules: RuleRow[], scope: Scope, field: F, value: RuleRow[F]): RuleRow[] {
  const i = rowIndex(rules, scope)
  const base = i >= 0 ? rules[i]! : emptyRow(scope)
  const next = { ...base, [field]: value }
  const list = i >= 0 ? rules.map((r, k) => (k === i ? next : r)) : [...rules, next]
  return isEmpty(next) ? list.filter((r) => !same(r, scope)) : list
}

export interface Effective {
  value: number | string | boolean
  from: 'zone' | 'parameter' | 'default'
}

/** A field's value for a zone, or for every zone of the parameter (zoneId null). */
export function resolve(rules: RuleRow[], defaults: RuleDefaults, scope: Scope, field: RuleField): Effective | null {
  const layers: [string | null, Effective['from']][] = []
  if (scope.zoneId !== null) layers.push([scope.zoneId, 'zone'])
  layers.push([null, 'parameter'])
  for (const [zoneId, from] of layers) {
    const value = rules.find((r) => same(r, { zoneId, parameterId: scope.parameterId }))?.[field]
    if (value !== null && value !== undefined) return { value, from }
  }
  const fallback = field in defaults ? defaults[field as keyof RuleDefaults] : undefined
  return fallback === undefined ? null : { value: fallback, from: 'default' }
}

/** What a blank field at this scope would inherit. */
export function inherited(rules: RuleRow[], defaults: RuleDefaults, scope: Scope, field: RuleField): Effective | null {
  return resolve(
    rules.filter((r) => !same(r, scope)),
    defaults,
    scope,
    field,
  )
}

export function valueOf(rules: RuleRow[], scope: Scope, field: RuleField): RuleRow[RuleField] {
  const i = rowIndex(rules, scope)
  return i >= 0 ? rules[i]![field] : null
}

/** The proposal's rows carry only the fields they set. */
export function normalizeRows(rows: RulesProposal['rules']): RuleRow[] {
  return rows.map((r) => ({ ...emptyRow({ parameterId: r.parameterId, zoneId: r.zoneId ?? null }), ...r }))
}

/** "rules[3].critLow" → the message for that row's field. */
export function fieldError(errors: { field: string; message: string }[], rules: RuleRow[], scope: Scope, field: RuleField) {
  const i = rowIndex(rules, scope)
  if (i < 0) return undefined
  return errors.find((e) => e.field === `rules[${i}].${field}`)?.message
}

export function formatValue(v: Effective['value'] | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'On' : 'Off'
  if (typeof v === 'string') return BRIEF_LABELS[v as BriefChangeMode] ?? v
  return unit ? `${v} ${unit}` : String(v)
}
