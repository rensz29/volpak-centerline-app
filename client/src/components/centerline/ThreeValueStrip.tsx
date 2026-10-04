import { TriangleAlert } from 'lucide-react'

import type { CenterlineRow } from '@/types'
import { cn } from '@/utils/cn'
import { NO_VALUE, formatNumber } from '@/utils/format'
import { STATUS_META } from '@/utils/status'

/**
 * The three-value comparison, rendered as one block.
 *
 * This is the recurring visual motif of the application: Target (what
 * engineering specified), HMI (what the operator dialled in) and Actual (what
 * the sensor reads) shown side by side, so both kinds of drift are legible at a
 * glance rather than needing to be computed by the reader.
 */
export function ThreeValueStrip({ row }: { row: CenterlineRow }) {
  const { parameter, reading, status, hasSetpointDrift } = row
  const meta = STATUS_META[status]

  return (
    <div className="border-line grid grid-cols-3 divide-x divide-slate-200 overflow-hidden rounded-lg border">
      <ValueCell
        label="Target"
        value={formatNumber(reading.targetSetpoint, parameter.decimals)}
        unit={parameter.unit}
        accent="border-t-series-target"
      />
      <ValueCell
        label="HMI"
        value={formatNumber(reading.hmiSetpoint, parameter.decimals)}
        unit={parameter.unit}
        accent="border-t-series-hmi"
        flag={
          hasSetpointDrift ? (
            <span className="text-warning inline-flex items-center gap-1 text-[11px] font-medium">
              <TriangleAlert className="size-3" aria-hidden />
              Setpoint drift
            </span>
          ) : null
        }
      />
      <ValueCell
        label="Actual"
        value={
          reading.actualValue === null
            ? NO_VALUE
            : formatNumber(reading.actualValue, parameter.decimals)
        }
        unit={reading.actualValue === null ? '' : parameter.unit}
        accent="border-t-series-actual"
        valueClass={status === 'normal' ? 'text-ink' : meta.text}
      />
    </div>
  )
}

function ValueCell({
  label,
  value,
  unit,
  accent,
  valueClass,
  flag,
}: {
  label: string
  value: string
  unit: string
  accent: string
  valueClass?: string
  flag?: React.ReactNode
}) {
  return (
    <div className={cn('bg-surface border-t-[3px] px-3 py-2.5', accent)}>
      <p className="micro-label">{label}</p>
      <p className={cn('tnum mt-1 text-[19px] leading-none font-semibold', valueClass ?? 'text-ink')}>
        {value}
        {unit && (
          <span className="text-ink-muted ml-1 text-[12px] font-medium">{unit}</span>
        )}
      </p>
      {flag && <div className="mt-1.5">{flag}</div>}
    </div>
  )
}
