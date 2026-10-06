import { AlertOctagon, AlertTriangle, CheckCircle2, Hourglass, MinusCircle, Power, PowerOff, Wrench } from 'lucide-react'
import { Fragment } from 'react'

import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import type { LiveParameter, LiveZone, ZoneControl } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { formatManilaShort } from '@/utils/manilaTime'

import { SEVERITY_LABEL, SEVERITY_TONE, TONE, secondsLeft, withUnit } from './liveModel'
import { StateBadge } from './StateBadge'

const SEVERITY_ICON = { NORMAL: CheckCircle2, WARNING: AlertTriangle, CRITICAL: AlertOctagon }

/** An open event keeps the rule it opened under (OPC-07), so a zone can be judged by an older version. */
const judgedBy = (version: number | null | undefined) => (version ? ` · judged by rules v${version}` : '')

function Value({ value, unit, accent, className }: { value: string | null | undefined; unit: string | null; accent: string; className?: string }) {
  return (
    <td className={cn('border-l-2 px-3 py-2 text-right font-mono text-[13px] whitespace-nowrap tabular-nums', accent, className)}>
      {withUnit(value, unit)}
    </td>
  )
}

export function HmiCell({ z, now, onOpenEvent }: { z: LiveZone; now: number; onOpenEvent: (id: string) => void }) {
  if (!z.known) return <StateBadge tone="nodata" icon={MinusCircle} label="No data" />
  if (z.hmi === 'NO_TARGET') {
    return (
      <StateBadge tone="nodata" icon={MinusCircle} label="Not judged"
                  title="The rules give this zone no target: give it one on Configuration → Rules to judge its HMI setpoint (ADR-0027)" />
    )
  }
  if (z.hmi === 'OPEN' && z.hmiEvent) {
    return (
      <button type="button" onClick={() => onOpenEvent(z.hmiEvent!)} className="rounded-md" aria-label={`Open the mismatch event on ${z.name}`}>
        <StateBadge tone="warning" icon={AlertTriangle} label="Mismatch" title={`The HMI setpoint is off target: an event is open${judgedBy(z.hmiRulesVersion)}`} />
      </button>
    )
  }
  // A machine's starting state isn't a judgement: without a value, only an open event is a fact
  if (z.setpoint === null || z.setpoint === undefined) {
    return <StateBadge tone="nodata" icon={MinusCircle} label="No data" title="No valid HMI setpoint from the machine" />
  }
  if (z.hmi === 'PENDING') {
    const left = secondsLeft(z.hmiDue, now)
    return (
      <StateBadge tone="warning" icon={Hourglass} label={left === null ? 'Off target' : `Off target · event in ${left} s`}
                  title={`The HMI setpoint differs from the target; an event opens if it stays so for the mismatch delay${judgedBy(z.hmiRulesVersion)}`} />
    )
  }
  return <StateBadge tone="normal" icon={CheckCircle2} label="At target" title={`The HMI setpoint is on target${judgedBy(z.hmiRulesVersion)}`} />
}

export function ActualCell({ z, unit, now, onOpenEvent }: { z: LiveZone; unit: string | null; now: number; onOpenEvent: (id: string) => void }) {
  if (!z.known || !z.actualSeverity) return <StateBadge tone="nodata" icon={MinusCircle} label="No data" />
  if ((z.actual === null || z.actual === undefined) && !z.actualEvent) {
    return <StateBadge tone="nodata" icon={MinusCircle} label="No data" title="No valid actual value from the machine" />
  }
  const bands = z.bands
    ? `Normal ${z.bands.warnLow}–${z.bands.warnHigh}${unit ? ` ${unit}` : ''} · Warning up to ${z.bands.critLow}–${z.bands.critHigh}${unit ? ` ${unit}` : ''}${judgedBy(z.actualRulesVersion)}`
    : undefined
  const badge = <StateBadge tone={SEVERITY_TONE[z.actualSeverity]} icon={SEVERITY_ICON[z.actualSeverity]} label={SEVERITY_LABEL[z.actualSeverity]} title={bands} />
  const left = secondsLeft(z.actualDue, now)
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {z.actualEvent ? (
        <button type="button" onClick={() => onOpenEvent(z.actualEvent!)} className="rounded-md" aria-label={`Open the Actual event on ${z.name}`}>
          {badge}
        </button>
      ) : (
        badge
      )}
      {z.actualPending && (
        <span className={cn('text-[11px] font-medium', TONE[SEVERITY_TONE[z.actualPending]].text)}>
          → {SEVERITY_LABEL[z.actualPending]}
          {left !== null ? ` in ${left} s` : ''}
        </span>
      )}
    </span>
  )
}

/** Why the zone isn't judged right now (ADR-0017): switched off, under maintenance, or back on and waiting. */
export function ControlCell({ c, z, onOpenEvent }: { c: ZoneControl; z: LiveZone; onOpenEvent: (id: string) => void }) {
  const event = z.actualEvent ?? z.hmiEvent
  const badge =
    c.state === 'off' ? (
      <StateBadge tone="nodata" icon={PowerOff} label="Monitoring off"
                  title={`Switched off ${formatManilaShort(Date.parse(c.since))} by ${c.by}${c.reason ? `: ${c.reason}` : ''}`} />
    ) : c.state === 'maintenance' ? (
      <StateBadge tone="nodata" icon={Wrench} label={c.scope === 'line' ? 'Line maintenance' : 'Maintenance'}
                  title={`${c.reason}; planned to end ${formatManilaShort(Date.parse(c.plannedEnd))} Manila. Delays and repeats wait; open events stay open.`} />
    ) : (
      <StateBadge tone="nodata" icon={Hourglass} label="Waiting for fresh values"
                  title="Back on: judged again on its next fresh values, its delays starting from zero (MNT-02)" />
    )
  return (
    <span className="flex flex-wrap items-center gap-2">
      {badge}
      {event && (
        <button type="button" onClick={() => onOpenEvent(event)} className="text-brand text-[12px] font-medium hover:underline">
          event open
        </button>
      )}
      {c.state === 'off' && c.reason && <span className="text-ink-soft truncate text-[12px]">{c.reason}</span>}
    </span>
  )
}

/** Every monitored zone: target, HMI setpoint and actual, with the states monitor-core has judged. */
export function ZoneTable({ parameters, now, onOpenEvent, onSwitch }: {
  parameters: LiveParameter[]
  now: number
  onOpenEvent: (id: string) => void
  /** Given to Managers only (MON-01): switch a zone off, or on again. */
  onSwitch?: (zone: LiveZone, parameter: LiveParameter, on: boolean) => void
}) {
  const zones = parameters.reduce((n, p) => n + p.zones.length, 0)
  const columns = onSwitch ? 7 : 6
  return (
    <SectionCard title="Zones" description={`${zones} monitored zones, grouped by URS parameter`} flush>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] text-[13px]">
          <thead>
            <tr className="text-ink-muted border-line border-b text-left text-[11px] whitespace-nowrap uppercase">
              <th className="px-4 py-2 font-semibold">Zone</th>
              <th className="px-3 py-2 text-right font-semibold">Target</th>
              <th className="px-3 py-2 text-right font-semibold">HMI setpoint</th>
              <th className="px-3 py-2 text-right font-semibold">Actual</th>
              <th className="w-[200px] px-3 py-2 font-semibold">HMI check</th>
              <th className="w-[220px] px-3 py-2 font-semibold">Actual check</th>
              {onSwitch && <th className="w-[52px] px-2 py-2" aria-label="Monitoring" />}
            </tr>
          </thead>
          <tbody>
            {parameters.map((p) => (
              <Fragment key={p.id}>
                <tr className="bg-surface-muted/50 border-line-soft border-b">
                  <td colSpan={columns} className="px-4 py-1.5">
                    <span className="text-ink font-medium">{p.name}</span>
                    {p.unit && <span className="text-ink-muted"> ({p.unit})</span>}
                    <span className="text-ink-muted ml-2 text-[11px]">{p.id}</span>
                  </td>
                </tr>
                {p.zones.map((z) => (
                  <tr key={z.channel} className="border-line-soft border-b">
                    <td className="py-2 pr-3 pl-7 whitespace-nowrap">
                      <span className="text-ink">{z.name}</span>
                      <span className="text-ink-muted ml-2 font-mono text-[11px]">{z.id}</span>
                    </td>
                    <Value value={z.target} unit={p.unit} accent="border-l-series-target/60" />
                    <Value value={z.setpoint} unit={p.unit} accent="border-l-series-hmi/60"
                           className={z.hmi === 'PENDING' || z.hmi === 'OPEN' ? 'text-warning font-semibold' : undefined} />
                    <Value value={z.actual} unit={p.unit} accent="border-l-series-actual/60"
                           className={z.actualSeverity && z.actualSeverity !== 'NORMAL' ? cn(TONE[SEVERITY_TONE[z.actualSeverity]].text, 'font-semibold') : undefined} />
                    {z.known && z.control ? (
                      <td colSpan={2} className="px-3 py-2">
                        <ControlCell c={z.control} z={z} onOpenEvent={onOpenEvent} />
                      </td>
                    ) : (
                      <>
                        <td className="px-3 py-2">
                          <HmiCell z={z} now={now} onOpenEvent={onOpenEvent} />
                        </td>
                        <td className="px-3 py-2">
                          <ActualCell z={z} unit={p.unit} now={now} onOpenEvent={onOpenEvent} />
                        </td>
                      </>
                    )}
                    {onSwitch && (
                      <td className="px-2 py-1 text-right">
                        {z.control?.state === 'off' ? (
                          <Button type="button" variant="ghost" size="icon-sm" title="Switch monitoring on again"
                                  aria-label={`Switch monitoring on for ${z.name}`} onClick={() => onSwitch(z, p, true)}>
                            <Power className="size-4" aria-hidden />
                          </Button>
                        ) : (
                          <Button type="button" variant="ghost" size="icon-sm" className="text-ink-muted" title="Switch monitoring off"
                                  aria-label={`Switch monitoring off for ${z.name}`} onClick={() => onSwitch(z, p, false)}>
                            <PowerOff className="size-4" aria-hidden />
                          </Button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  )
}
