import { TriangleAlert } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { CenterlineRow } from '@/types'
import { cn } from '@/utils/cn'
import { NO_VALUE, formatDeviationPct, formatNumber } from '@/utils/format'
import { STATUS_META } from '@/utils/status'

/**
 * HMI setpoint cell.
 *
 * When the operator's panel value differs from the engineering target this is
 * *setpoint drift* — a distinct finding from the process simply running off
 * target, and the one a centerline system exists to catch. It is marked with an
 * icon and a warning tint rather than by re-colouring the whole row, so the
 * table stays readable when several rows drift at once.
 */
export function HmiSetpointCell({ row }: { row: CenterlineRow }) {
  const { reading, parameter, hasSetpointDrift } = row
  const value = formatNumber(reading.hmiSetpoint, parameter.decimals)

  if (!hasSetpointDrift) {
    return <span className="tnum text-ink-soft">{value}</span>
  }

  const delta = reading.hmiSetpoint - reading.targetSetpoint
  const deltaPct = (delta / reading.targetSetpoint) * 100

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="border-warning-border bg-warning-surface text-warning tnum inline-flex cursor-help items-center gap-1.5 rounded border px-1.5 py-0.5 font-medium">
          <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
          {value}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-semibold">Setpoint drift</p>
        <p className="mt-0.5 font-normal">
          The HMI panel value is {formatDeviationPct(deltaPct)} from the centerline
          target of {formatNumber(reading.targetSetpoint, parameter.decimals)}{' '}
          {parameter.unit}.
        </p>
      </TooltipContent>
    </Tooltip>
  )
}

/** Actual value, tinted by status so the eye lands on the outliers first. */
export function ActualValueCell({ row }: { row: CenterlineRow }) {
  if (row.reading.actualValue === null) {
    return <span className="text-ink-muted tnum">{NO_VALUE}</span>
  }

  const meta = STATUS_META[row.status]

  return (
    <span
      className={cn(
        'tnum font-semibold',
        row.status === 'normal' ? 'text-ink' : meta.text,
      )}
    >
      {formatNumber(row.reading.actualValue, row.parameter.decimals)}
    </span>
  )
}

/** Absolute deviation with its percentage underneath. */
export function DeviationCell({ row }: { row: CenterlineRow }) {
  if (row.deviation === null || row.deviationPct === null) {
    return <span className="text-ink-muted tnum">{NO_VALUE}</span>
  }

  const meta = STATUS_META[row.status]
  const sign = row.deviation > 0 ? '+' : row.deviation < 0 ? '−' : ''

  return (
    <span className="flex flex-col items-end leading-tight">
      <span
        className={cn(
          'tnum font-semibold',
          row.status === 'normal' ? 'text-ink-soft' : meta.text,
        )}
      >
        {sign}
        {formatNumber(Math.abs(row.deviation), row.parameter.decimals)}
      </span>
      <span className={cn('tnum text-[11px]', row.status === 'normal' ? 'text-ink-muted' : meta.text)}>
        {formatDeviationPct(row.deviationPct)}
      </span>
    </span>
  )
}

/** Warning and critical tolerance bands, shown as ± percentages. */
export function ToleranceCell({ row }: { row: CenterlineRow }) {
  const { warningTolerancePct, criticalTolerancePct } = row.parameter

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="tnum inline-flex cursor-help items-center gap-1 text-[12px]">
          <span className="text-warning">±{formatNumber(warningTolerancePct, 1)}%</span>
          <span className="text-ink-muted" aria-hidden>
            /
          </span>
          <span className="text-critical">±{formatNumber(criticalTolerancePct, 1)}%</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-semibold">Tolerance bands</p>
        <p className="mt-0.5 font-normal">
          Warning beyond ±{formatNumber(warningTolerancePct, 1)}%, critical beyond ±
          {formatNumber(criticalTolerancePct, 1)}% of the target setpoint.
        </p>
      </TooltipContent>
    </Tooltip>
  )
}
