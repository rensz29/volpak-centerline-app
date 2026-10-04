import { CheckCheck, Eye, ShieldCheck } from 'lucide-react'

import { AlarmSeverityBadge, AlarmStatusBadge } from '@/components/alarms/AlarmBadges'
import { Button } from '@/components/ui/button'
import type { AlarmRow } from '@/types'
import { cn } from '@/utils/cn'
import {
  NO_VALUE,
  formatDeviationPct,
  formatNumber,
  formatRelativeTime,
  formatTimestamp,
} from '@/utils/format'
import { SEVERITY_META } from '@/utils/status'

interface AlarmCardProps {
  alarm: AlarmRow
  onView: (alarm: AlarmRow) => void
  onAcknowledge: (alarm: AlarmRow) => void
  onResolve: (alarm: AlarmRow) => void
}

export function AlarmCard({ alarm, onView, onAcknowledge, onResolve }: AlarmCardProps) {
  const meta = SEVERITY_META[alarm.severity]
  const drift = alarm.hmiValue !== alarm.targetValue

  return (
    <article className="bg-surface border-line shadow-card relative overflow-hidden rounded-lg border">
      {/* Severity rail rather than a wash of colour across the whole card. */}
      <span className={cn('absolute inset-y-0 left-0 w-1', meta.rail)} aria-hidden />

      <div className="py-3.5 pr-4 pl-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <AlarmSeverityBadge severity={alarm.severity} />
              <AlarmStatusBadge status={alarm.status} />
              <span className="text-ink-muted tnum text-[11px]">{alarm.reference}</span>
            </div>

            <h3 className="text-ink mt-2 text-[14px] font-semibold">
              {alarm.parameterName}
            </h3>
            <p className="text-ink-soft mt-0.5 text-[12px]">
              {alarm.machineName} · {alarm.lineName} · {alarm.skuCode}
            </p>
          </div>

          <div className="text-right">
            <p className="text-ink-soft tnum text-[12px]">
              {formatRelativeTime(alarm.raisedAt)}
            </p>
            <p className="text-ink-muted tnum text-[11px]">
              {formatTimestamp(alarm.raisedAt)}
            </p>
          </div>
        </div>

        {/* The three-value comparison in compact form. */}
        <div className="border-line bg-surface-muted mt-3 grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border px-3 py-2.5 sm:grid-cols-4">
          <CompactValue
            label="Target"
            value={formatNumber(alarm.targetValue, alarm.parameterDecimals)}
            unit={alarm.unit}
          />
          <CompactValue
            label="HMI"
            value={formatNumber(alarm.hmiValue, alarm.parameterDecimals)}
            unit={alarm.unit}
            flagged={drift}
            flagLabel="Drift"
          />
          <CompactValue
            label="Actual"
            value={
              alarm.actualValue === null
                ? NO_VALUE
                : formatNumber(alarm.actualValue, alarm.parameterDecimals)
            }
            unit={alarm.actualValue === null ? '' : alarm.unit}
            emphasis
          />
          <CompactValue
            label="Deviation"
            value={formatDeviationPct(alarm.deviationPct)}
            unit=""
            className={meta.badge.split(' ').at(-1)}
          />
        </div>

        <p className="text-ink-soft mt-3 text-[13px] leading-relaxed">{alarm.message}</p>

        {alarm.status === 'acknowledged' && alarm.acknowledgedBy && (
          <p className="text-ink-muted mt-2 text-[11px]">
            Acknowledged by {alarm.acknowledgedBy} ·{' '}
            {alarm.acknowledgedAt ? formatRelativeTime(alarm.acknowledgedAt) : ''}
          </p>
        )}
        {alarm.status === 'resolved' && alarm.resolvedBy && (
          <p className="text-ink-muted mt-2 text-[11px]">
            Resolved by {alarm.resolvedBy} ·{' '}
            {alarm.resolvedAt ? formatRelativeTime(alarm.resolvedAt) : ''}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => onView(alarm)} className="gap-1.5">
            <Eye className="size-3.5" aria-hidden />
            View details
          </Button>

          {alarm.status === 'active' && (
            <Button size="sm" onClick={() => onAcknowledge(alarm)} className="gap-1.5">
              <CheckCheck className="size-3.5" aria-hidden />
              Acknowledge
            </Button>
          )}

          {alarm.status !== 'resolved' && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => onResolve(alarm)}
              className="border-normal-border text-normal hover:bg-normal-surface gap-1.5"
            >
              <ShieldCheck className="size-3.5" aria-hidden />
              Resolve
            </Button>
          )}
        </div>
      </div>
    </article>
  )
}

function CompactValue({
  label,
  value,
  unit,
  emphasis = false,
  flagged = false,
  flagLabel,
  className,
}: {
  label: string
  value: string
  unit: string
  emphasis?: boolean
  flagged?: boolean
  flagLabel?: string
  className?: string
}) {
  return (
    <div className="min-w-0">
      <p className="micro-label">{label}</p>
      <p
        className={cn(
          'tnum mt-0.5 text-[14px] leading-none',
          emphasis ? 'text-ink font-semibold' : 'text-ink-soft font-medium',
          flagged && 'text-warning',
          className,
        )}
      >
        {value}
        {unit && <span className="text-ink-muted ml-0.5 text-[11px]">{unit}</span>}
      </p>
      {flagged && flagLabel && (
        <p className="text-warning mt-0.5 text-[10px] font-semibold uppercase">
          {flagLabel}
        </p>
      )}
    </div>
  )
}
