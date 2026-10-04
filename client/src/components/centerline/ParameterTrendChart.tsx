import { useMemo, useState } from 'react'
import {
  Brush,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { EmptyState } from '@/components/shared/EmptyState'
import type { ParameterDefinition, TrendPoint } from '@/types'
import { cn } from '@/utils/cn'
import { formatNumber, formatTime, formatTimestamp } from '@/utils/format'
import { LineChartIcon } from '@/components/shared/icons'

/** Fixed, semantic series identities — never reassigned between charts. */
const SERIES = {
  actual: { label: 'Actual', color: 'var(--color-series-actual)' },
  hmi: { label: 'HMI setpoint', color: 'var(--color-series-hmi)' },
  target: { label: 'Target setpoint', color: 'var(--color-series-target)' },
  tolerance: { label: 'Tolerance band', color: 'var(--color-series-tolerance)' },
} as const

type SeriesKey = keyof typeof SERIES

interface ChartDatum extends TrendPoint {
  time: number
  /** Only populated on alarm points, so the marker layer plots just those. */
  alarmValue: number | null
}

interface ParameterTrendChartProps {
  points: readonly TrendPoint[]
  parameter: ParameterDefinition
  height?: number
  showBrush?: boolean
}

export function ParameterTrendChart({
  points,
  parameter,
  height = 300,
  showBrush = true,
}: ParameterTrendChartProps) {
  const [hidden, setHidden] = useState<ReadonlySet<SeriesKey>>(new Set())

  const data = useMemo<ChartDatum[]>(
    () =>
      points.map((point) => ({
        ...point,
        time: new Date(point.timestamp).getTime(),
        alarmValue: point.alarmSeverity !== null ? point.actual : null,
      })),
    [points],
  )

  const toggle = (key: SeriesKey) => {
    setHidden((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const visible = (key: SeriesKey) => !hidden.has(key)

  if (data.length === 0) {
    return (
      <EmptyState
        icon={LineChartIcon}
        title="No trend data"
        description="No readings were recorded for this parameter in the selected window."
        compact
      />
    )
  }

  // A little headroom beyond the tolerance band keeps excursions from being
  // clipped against the plot edge.
  const domain = computeDomain(data)

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {(Object.keys(SERIES) as SeriesKey[]).map((key) => (
          <SeriesToggle
            key={key}
            label={SERIES[key].label}
            color={SERIES[key].color}
            active={visible(key)}
            dashed={key === 'hmi'}
            band={key === 'tolerance'}
            onClick={() => toggle(key)}
          />
        ))}
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="var(--color-line)" strokeDasharray="3 3" vertical={false} />

          <XAxis
            dataKey="time"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={(value: number) => formatTime(new Date(value).toISOString())}
            tick={{ fill: 'var(--color-ink-muted)', fontSize: 11 }}
            stroke="var(--color-line)"
            minTickGap={40}
          />

          <YAxis
            domain={domain}
            tick={{ fill: 'var(--color-ink-muted)', fontSize: 11 }}
            stroke="var(--color-line)"
            width={56}
            tickFormatter={(value: number) => formatNumber(value, parameter.decimals)}
            label={{
              value: parameter.unit,
              angle: -90,
              position: 'insideLeft',
              style: {
                fill: 'var(--color-ink-muted)',
                fontSize: 11,
                textAnchor: 'middle',
              },
            }}
          />

          {/* Warning tolerance band, drawn behind every line. */}
          {visible('tolerance') && data[0] && (
            <ReferenceArea
              y1={data[0].lowerTolerance}
              y2={data[0].upperTolerance}
              fill="var(--color-series-tolerance)"
              fillOpacity={0.14}
              stroke="var(--color-series-tolerance)"
              strokeDasharray="4 4"
              strokeOpacity={0.6}
            />
          )}

          <Tooltip
            content={({ active, payload }) => (
              <TrendTooltip active={active} payload={payload} parameter={parameter} />
            )}
            cursor={{ stroke: 'var(--color-ink-muted)', strokeDasharray: '3 3' }}
          />
          <Legend content={() => null} />

          {visible('target') && (
            <Line
              type="monotone"
              dataKey="target"
              name={SERIES.target.label}
              stroke={SERIES.target.color}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          )}

          {visible('hmi') && (
            <Line
              type="monotone"
              dataKey="hmi"
              name={SERIES.hmi.label}
              stroke={SERIES.hmi.color}
              strokeWidth={1.75}
              strokeDasharray="6 3"
              dot={false}
              isAnimationActive={false}
            />
          )}

          {visible('actual') && (
            <Line
              type="monotone"
              dataKey="actual"
              name={SERIES.actual.label}
              stroke={SERIES.actual.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          )}

          {/* Alarm events: readings that breached a tolerance band. */}
          {visible('actual') && (
            <Scatter
              dataKey="alarmValue"
              name="Alarm event"
              fill="var(--color-series-alarm)"
              shape="circle"
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {showBrush && data.length > 12 && (
            <Brush
              dataKey="time"
              height={26}
              travellerWidth={8}
              stroke="var(--color-ink-muted)"
              fill="var(--color-surface-muted)"
              tickFormatter={(value: number) =>
                formatTime(new Date(value).toISOString())
              }
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function computeDomain(data: readonly ChartDatum[]): [number, number] {
  let min = Number.POSITIVE_INFINITY
  let max = Number.NEGATIVE_INFINITY

  for (const point of data) {
    for (const value of [point.actual, point.hmi, point.target, point.upperTolerance, point.lowerTolerance]) {
      if (value === null) continue
      min = Math.min(min, value)
      max = Math.max(max, value)
    }
  }

  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1]
  const padding = (max - min) * 0.12 || Math.abs(max) * 0.05 || 1
  return [min - padding, max + padding]
}

function SeriesToggle({
  label,
  color,
  active,
  dashed = false,
  band = false,
  onClick,
}: {
  label: string
  color: string
  active: boolean
  dashed?: boolean
  band?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'border-line focus-visible:ring-brand-ring inline-flex h-8 items-center gap-2 rounded-md border px-2.5 text-[12px] font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none',
        active
          ? 'bg-surface text-ink hover:bg-surface-muted'
          : 'bg-surface-muted text-ink-muted line-through hover:text-ink-soft',
      )}
    >
      {band ? (
        <span
          className="h-3 w-4 shrink-0 rounded-[2px] border"
          style={{
            backgroundColor: active ? color : 'transparent',
            opacity: active ? 0.35 : 1,
            borderColor: color,
          }}
          aria-hidden
        />
      ) : (
        <span
          className="h-0.5 w-4 shrink-0 rounded-full"
          style={{
            backgroundColor: active ? color : 'var(--color-ink-muted)',
            backgroundImage: dashed
              ? `repeating-linear-gradient(90deg, ${active ? color : 'var(--color-ink-muted)'} 0 5px, transparent 5px 8px)`
              : undefined,
          }}
          aria-hidden
        />
      )}
      {label}
    </button>
  )
}

/** Only the datum matters here, so the tooltip declares just what it reads. */
interface TrendTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: ChartDatum }>
  parameter: ParameterDefinition
}

function TrendTooltip({ active, payload, parameter }: TrendTooltipProps) {
  if (!active || !payload || payload.length === 0) return null

  const datum = payload[0]?.payload
  if (!datum) return null

  return (
    <div className="bg-surface border-line shadow-overlay min-w-[210px] rounded-lg border p-3">
      <p className="text-ink-soft border-line mb-2 border-b pb-2 text-[11px] font-medium">
        {formatTimestamp(datum.timestamp)}
      </p>

      <dl className="space-y-1.5">
        <TooltipRow
          label={SERIES.actual.label}
          color={SERIES.actual.color}
          value={datum.actual}
          parameter={parameter}
          emphasis
        />
        <TooltipRow
          label={SERIES.hmi.label}
          color={SERIES.hmi.color}
          value={datum.hmi}
          parameter={parameter}
        />
        <TooltipRow
          label={SERIES.target.label}
          color={SERIES.target.color}
          value={datum.target}
          parameter={parameter}
        />
      </dl>

      {datum.alarmSeverity && (
        <p
          className={cn(
            'mt-2 rounded border px-2 py-1 text-[11px] font-medium',
            datum.alarmSeverity === 'critical'
              ? 'border-critical-border bg-critical-surface text-critical'
              : 'border-warning-border bg-warning-surface text-warning',
          )}
        >
          {datum.alarmSeverity === 'critical' ? 'Critical' : 'Warning'} — outside tolerance
        </p>
      )}
    </div>
  )
}

function TooltipRow({
  label,
  color,
  value,
  parameter,
  emphasis = false,
}: {
  label: string
  color: string
  value: number | null
  parameter: ParameterDefinition
  emphasis?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-ink-soft flex items-center gap-1.5 text-[12px]">
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
          aria-hidden
        />
        {label}
      </dt>
      <dd className={cn('tnum text-[12px]', emphasis ? 'text-ink font-semibold' : 'text-ink-soft')}>
        {value === null ? '—' : `${formatNumber(value, parameter.decimals)} ${parameter.unit}`}
      </dd>
    </div>
  )
}
