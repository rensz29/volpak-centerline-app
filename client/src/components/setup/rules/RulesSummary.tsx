import { ShieldAlert } from 'lucide-react'
import { useMemo } from 'react'

import type { RegisterView, RulesVersion } from '@/types/configApi'

import { GapsSummary } from './RuleDialogs'
import {
  BRIEF_LABELS,
  DELAY_FIELDS,
  FIELD_LABELS,
  LIMIT_FIELDS,
  RULE_FIELDS,
  formatValue,
  monitoredParameters,
  resolve,
} from './ruleModel'

const signed = (low: unknown, high: unknown, unit: string | null) =>
  low === null && high === null ? '—' : `−${formatValue(low as number | null)} / +${formatValue(high as number | null)}${unit ? ` ${unit}` : ''}`

/** A version at a glance: when rules run, defaults, limits and targets per parameter, and what it leaves unjudged. */
export function RulesSummary({ version, register }: { version: RulesVersion; register: RegisterView }) {
  const params = useMemo(() => monitoredParameters(register), [register])
  const { settings, rules } = version
  const d = settings.defaults
  const pause = settings.pauseWhenStopped

  return (
    <div className="flex flex-col gap-4 text-[13px]">
      {!version.intact && (
        <p className="border-critical-border bg-critical-surface text-critical flex items-center gap-2 rounded-md border px-3 py-2">
          <ShieldAlert className="size-4 shrink-0" aria-hidden />
          This version's stored content no longer matches its fingerprint: it was changed outside Centerline. Don't activate it.
        </p>
      )}
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-[200px_1fr]">
        <dt className="text-ink-muted">Actual rules</dt>
        <dd className="text-ink">
          {pause.enabled
            ? `Paused while the machine is stopped, and for ${pause.warmupMin} min after stops of ${pause.longStopMin} min or more`
            : 'Run at all times, even while the machine is stopped'}
        </dd>
        <dt className="text-ink-muted">Default delays</dt>
        <dd className="text-ink">
          {DELAY_FIELDS.map((f) => `${FIELD_LABELS[f].replace(' delay', '')} ${d[f]} s`).join(' · ')}
        </dd>
        <dt className="text-ink-muted">Short setpoint changes</dt>
        <dd className="text-ink">{BRIEF_LABELS[d.briefChangeMode]}</dd>
        <dt className="text-ink-muted">Warning notifications</dt>
        <dd className="text-ink">{d.warningNotifications ? 'On' : 'Off'} (Critical ones always go out)</dd>
      </dl>

      <table className="w-full">
        <thead>
          <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
            <th className="py-2 pr-3 font-semibold">Parameter</th>
            <th className="px-2 py-2 font-semibold">Warning</th>
            <th className="px-2 py-2 font-semibold">Critical</th>
            <th className="px-2 py-2 font-semibold">Targets</th>
            <th className="px-2 py-2 font-semibold">Other settings</th>
          </tr>
        </thead>
        <tbody>
          {params.map((p) => {
            const scope = { parameterId: p.id, zoneId: null }
            const get = (f: (typeof LIMIT_FIELDS)[number]) => resolve(rules, d, scope, f)?.value ?? null
            const own = rules.find((r) => r.parameterId === p.id && r.zoneId === null)
            const notes = [
              ...DELAY_FIELDS.filter((f) => own?.[f] !== null && own?.[f] !== undefined).map((f) => `${FIELD_LABELS[f]} ${own?.[f]} s`),
              own?.briefChangeMode ? BRIEF_LABELS[own.briefChangeMode] : null,
              own?.warningNotifications === false ? 'no Warning notifications' : null,
            ].filter(Boolean)
            // A zone's own target isn't an override: targets are set per zone
            const zoneOverrides = rules.filter(
              (r) => r.parameterId === p.id && r.zoneId !== null && RULE_FIELDS.some((f) => f !== 'target' && r[f] !== null),
            ).length
            if (zoneOverrides) notes.push(`${zoneOverrides} zone override${zoneOverrides === 1 ? '' : 's'}`)
            const targets = p.zones.filter((z) => resolve(rules, d, { parameterId: p.id, zoneId: z.id }, 'target') !== null).length
            return (
              <tr key={p.id} className="border-line-soft border-b">
                <td className="py-1.5 pr-3">
                  {p.name} <span className="text-ink-muted text-[11px]">{p.id}</span>
                </td>
                <td className="px-2 py-1.5 font-mono text-[12px]">{signed(get('warnLow'), get('warnHigh'), p.unit)}</td>
                <td className="px-2 py-1.5 font-mono text-[12px]">{signed(get('critLow'), get('critHigh'), p.unit)}</td>
                <td className={targets < p.zones.length ? 'text-ink-soft px-2 py-1.5 text-[12px]' : 'text-ink px-2 py-1.5 text-[12px]'}>
                  {targets} of {p.zones.length} zone{p.zones.length === 1 ? '' : 's'}
                </td>
                <td className="text-ink-soft px-2 py-1.5 text-[12px]">{notes.length ? notes.join(' · ') : 'defaults'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div>
        <p className="micro-label mb-1.5">Zones</p>
        {version.carryOver && (
          <p className="border-line bg-surface-muted/50 text-ink-soft mb-2 rounded-md border px-3 py-2">
            Saved before product codes were dropped (ADR-0027), with targets for {version.carryOver.from}. Those rows judge nothing
            now. “Edit as new” carries them over as the zones' own targets.
          </p>
        )}
        <GapsSummary gaps={version.gaps} />
      </div>
    </div>
  )
}
