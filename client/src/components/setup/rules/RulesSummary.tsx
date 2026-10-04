import { CheckCircle2, ShieldAlert, TriangleAlert } from 'lucide-react'
import { useMemo } from 'react'

import type { RegisterView, RulesVersion, Sku } from '@/types/configApi'

import {
  BRIEF_LABELS,
  DELAY_FIELDS,
  FIELD_LABELS,
  LIMIT_FIELDS,
  formatValue,
  monitoredParameters,
  resolve,
} from './ruleModel'

const signed = (low: unknown, high: unknown, unit: string | null) =>
  low === null && high === null ? '—' : `−${formatValue(low as number | null)} / +${formatValue(high as number | null)}${unit ? ` ${unit}` : ''}`

/** A version at a glance: when rules run, defaults, limits per parameter, SKUs and their readiness. */
export function RulesSummary({ version, register, skus }: { version: RulesVersion; register: RegisterView; skus: Sku[] }) {
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
            <th className="px-2 py-2 font-semibold">Other settings</th>
          </tr>
        </thead>
        <tbody>
          {params.map((p) => {
            const scope = { sku: null, parameterId: p.id, zoneId: null }
            const get = (f: (typeof LIMIT_FIELDS)[number]) => resolve(rules, d, scope, f)?.value ?? null
            const own = rules.find((r) => r.parameterId === p.id && r.sku === null && r.zoneId === null)
            const notes = [
              ...DELAY_FIELDS.filter((f) => own?.[f] !== null && own?.[f] !== undefined).map((f) => `${FIELD_LABELS[f]} ${own?.[f]} s`),
              own?.briefChangeMode ? BRIEF_LABELS[own.briefChangeMode] : null,
              own?.warningNotifications === false ? 'no Warning notifications' : null,
            ].filter(Boolean)
            const zoneOverrides = rules.filter((r) => r.parameterId === p.id && r.sku === null && r.zoneId !== null).length
            const skuOverrides = new Set(rules.filter((r) => r.parameterId === p.id && r.sku !== null && LIMIT_FIELDS.some((f) => r[f] !== null)).map((r) => r.sku)).size
            if (zoneOverrides) notes.push(`${zoneOverrides} zone override${zoneOverrides === 1 ? '' : 's'}`)
            if (skuOverrides) notes.push(`different limits for ${skuOverrides} SKU${skuOverrides === 1 ? '' : 's'}`)
            return (
              <tr key={p.id} className="border-line-soft border-b">
                <td className="py-1.5 pr-3">
                  {p.name} <span className="text-ink-muted text-[11px]">{p.id}</span>
                </td>
                <td className="px-2 py-1.5 font-mono text-[12px]">{signed(get('warnLow'), get('warnHigh'), p.unit)}</td>
                <td className="px-2 py-1.5 font-mono text-[12px]">{signed(get('critLow'), get('critHigh'), p.unit)}</td>
                <td className="text-ink-soft px-2 py-1.5 text-[12px]">{notes.length ? notes.join(' · ') : 'defaults'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div>
        <p className="micro-label mb-1.5">SKUs</p>
        {skus.length === 0 ? (
          <p className="text-ink-soft">No SKUs in the list yet, so none can be monitored.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {skus.map((s) => {
              const gaps = version.readiness[s.code] ?? []
              const zones = params.reduce((n, p) => n + p.zones.length, 0)
              return (
                <li key={s.code} className="flex items-center gap-2">
                  {gaps.length === 0 ? (
                    <CheckCircle2 className="text-normal size-4" aria-hidden />
                  ) : (
                    <TriangleAlert className="text-warning size-4" aria-hidden />
                  )}
                  <span className="font-mono">{s.code}</span>
                  <span className="text-ink">{s.name}</span>
                  <span className="text-ink-soft text-[12px]">
                    {gaps.length === 0 ? 'ready' : `${zones - gaps.length} of ${zones} zones complete; monitoring pauses while it runs`}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
