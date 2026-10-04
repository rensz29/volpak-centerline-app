import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'

import { EmptyState } from '@/components/shared/EmptyState'
import { ScatterChartIcon } from '@/components/shared/icons'
import type { GroupBy } from '@/hooks/useAnalyticsSelection'
import type { CorrelationResult, ParameterDefinition } from '@/types'
import type { ScatterPoint } from '@/utils/selectors'
import { formatNumber, formatTimestamp } from '@/utils/format'

/** Qualitative ramp chosen to stay separable in greyscale. */
const GROUP_COLORS = [
  'var(--color-cat-1)',
  'var(--color-cat-2)',
  'var(--color-cat-3)',
  'var(--color-cat-4)',
  'var(--color-cat-5)',
]

interface CorrelationScatterChartProps {
  points: readonly ScatterPoint[]
  xParameter: ParameterDefinition
  yParameter: ParameterDefinition
  groupBy: GroupBy
  correlation: CorrelationResult
  height?: number
}

export function CorrelationScatterChart({
  points,
  xParameter,
  yParameter,
  groupBy,
  correlation,
  height = 420,
}: CorrelationScatterChartProps) {
  /** One Scatter series per group so the legend and colours follow the data. */
  const groups = useMemo(() => {
    const buckets = new Map<string, ScatterPoint[]>()

    for (const point of points) {
      const key =
        groupBy === 'sku'
          ? point.skuCode
          : groupBy === 'machine'
            ? point.machineName
            : `Shift ${point.shift}`

      const bucket = buckets.get(key)
      if (bucket) bucket.push(point)
      else buckets.set(key, [point])
    }

    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, data], i) => ({
        name,
        data,
        color: GROUP_COLORS[i % GROUP_COLORS.length] ?? GROUP_COLORS[0],
      }))
  }, [points, groupBy])

  /** Two endpoints of the least-squares fit, drawn as a straight overlay. */
  const regressionLine = useMemo(() => {
    if (points.length < 3) return []
    const xs = points.map((p) => p.x)
    const min = Math.min(...xs)
    const max = Math.max(...xs)
    return [
      { x: min, y: correlation.intercept + correlation.slope * min },
      { x: max, y: correlation.intercept + correlation.slope * max },
    ]
  }, [points, correlation])

  if (points.length === 0) {
    return (
      <EmptyState
        icon={ScatterChartIcon}
        title="No paired observations"
        description={`No sample in the current selection has a reading for both ${xParameter.name} and ${yParameter.name}. Widen the filters or choose parameters measured on the same machine.`}
      />
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 12, right: 20, bottom: 28, left: 12 }}>
        <CartesianGrid stroke="var(--color-line)" strokeDasharray="3 3" />

        <XAxis
          type="number"
          dataKey="x"
          name={xParameter.name}
          domain={['dataMin', 'dataMax']}
          tick={{ fill: 'var(--color-ink-muted)', fontSize: 11 }}
          stroke="var(--color-line)"
          tickFormatter={(value: number) => formatNumber(value, xParameter.decimals)}
          label={{
            value: `${xParameter.name} (${xParameter.unit})`,
            position: 'insideBottom',
            offset: -16,
            style: { fill: 'var(--color-ink-soft)', fontSize: 12, fontWeight: 500 },
          }}
        />

        <YAxis
          type="number"
          dataKey="y"
          name={yParameter.name}
          domain={['dataMin', 'dataMax']}
          tick={{ fill: 'var(--color-ink-muted)', fontSize: 11 }}
          stroke="var(--color-line)"
          width={64}
          tickFormatter={(value: number) => formatNumber(value, yParameter.decimals)}
          label={{
            value: `${yParameter.name} (${yParameter.unit})`,
            angle: -90,
            position: 'insideLeft',
            style: {
              fill: 'var(--color-ink-soft)',
              fontSize: 12,
              fontWeight: 500,
              textAnchor: 'middle',
            },
          }}
        />

        <ZAxis range={[36, 36]} />

        <Tooltip
          cursor={{ strokeDasharray: '3 3', stroke: 'var(--color-ink-muted)' }}
          content={({ active, payload }) => (
            <ScatterTooltip
              active={active}
              payload={payload}
              xParameter={xParameter}
              yParameter={yParameter}
            />
          )}
        />

        <Legend
          verticalAlign="top"
          align="right"
          height={30}
          iconType="circle"
          wrapperStyle={{ fontSize: 12, color: 'var(--color-ink-soft)' }}
        />

        {groups.map((group) => (
          <Scatter
            key={group.name}
            name={group.name}
            data={group.data}
            fill={group.color}
            fillOpacity={0.7}
            isAnimationActive={false}
          />
        ))}

        {/* Least-squares fit, drawn on top of the points. */}
        {regressionLine.length === 2 && (
          <Line
            type="linear"
            dataKey="y"
            data={regressionLine}
            name={`Trend line (r = ${correlation.coefficient.toFixed(2)})`}
            stroke="var(--color-ink)"
            strokeWidth={1.75}
            strokeDasharray="5 4"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
            legendType="plainline"
          />
        )}
      </ScatterChart>
    </ResponsiveContainer>
  )
}

interface ScatterTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: ScatterPoint }>
  xParameter: ParameterDefinition
  yParameter: ParameterDefinition
}

function ScatterTooltip({ active, payload, xParameter, yParameter }: ScatterTooltipProps) {
  if (!active || !payload || payload.length === 0) return null

  const datum = payload[0]?.payload
  // The regression overlay has no plant context; skip its tooltip.
  if (!datum || datum.timestamp === undefined) return null

  return (
    <div className="bg-surface border-line shadow-overlay min-w-[230px] rounded-lg border p-3">
      <p className="text-ink-soft border-line mb-2 border-b pb-2 text-[11px] font-medium">
        {formatTimestamp(datum.timestamp)}
      </p>
      <dl className="space-y-1.5">
        <Row label={xParameter.name}>
          <span className="tnum text-ink font-semibold">
            {formatNumber(datum.x, xParameter.decimals)} {xParameter.unit}
          </span>
        </Row>
        <Row label={yParameter.name}>
          <span className="tnum text-ink font-semibold">
            {formatNumber(datum.y, yParameter.decimals)} {yParameter.unit}
          </span>
        </Row>
        <div className="border-line mt-2 space-y-1.5 border-t pt-2">
          <Row label="SKU">{datum.skuCode}</Row>
          <Row label="Machine">{datum.machineName}</Row>
          <Row label="Production line">{datum.lineName}</Row>
        </div>
      </dl>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-ink-soft text-[12px]">{label}</dt>
      <dd className="text-ink-soft text-[12px]">{children}</dd>
    </div>
  )
}
