import { useMemo } from 'react'

import { ParameterTrendChart } from '@/components/centerline/ParameterTrendChart'
import { EmptyState } from '@/components/shared/EmptyState'
import { LineChartIcon } from '@/components/shared/icons'
import type { ParameterDefinition, ProcessSample, TrendPoint } from '@/types'
import { deriveStatus } from '@/utils/status'

interface SetpointComparisonChartProps {
  samples: readonly ProcessSample[]
  parameter: ParameterDefinition
  height?: number
}

/**
 * Actual against both setpoints over time for the filtered selection.
 *
 * Where several machines are in scope the readings are averaged per timestamp:
 * drawing one line per machine on top of the setpoint lines would make the
 * comparison the chart exists for unreadable.
 */
export function SetpointComparisonChart({
  samples,
  parameter,
  height = 420,
}: SetpointComparisonChartProps) {
  const points = useMemo<TrendPoint[]>(() => {
    const byTimestamp = new Map<
      string,
      { actuals: number[]; hmi: number[]; target: number[] }
    >()

    for (const sample of samples) {
      const value = sample.values[parameter.code]
      const bucket = byTimestamp.get(sample.timestamp) ?? {
        actuals: [],
        hmi: [],
        target: [],
      }
      if (value.actual !== null) bucket.actuals.push(value.actual)
      bucket.hmi.push(value.hmi)
      bucket.target.push(value.target)
      byTimestamp.set(sample.timestamp, bucket)
    }

    return [...byTimestamp.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([timestamp, bucket]) => {
        const actual = bucket.actuals.length === 0 ? null : average(bucket.actuals)
        const target = average(bucket.target)
        const status = deriveStatus(
          actual,
          target,
          parameter.warningTolerancePct,
          parameter.criticalTolerancePct,
        )

        return {
          timestamp,
          actual,
          hmi: average(bucket.hmi),
          target,
          upperTolerance: target * (1 + parameter.warningTolerancePct / 100),
          lowerTolerance: target * (1 - parameter.warningTolerancePct / 100),
          alarmSeverity:
            status === 'critical' ? 'critical' : status === 'warning' ? 'warning' : null,
        } satisfies TrendPoint
      })
  }, [samples, parameter])

  if (points.length === 0) {
    return (
      <EmptyState
        icon={LineChartIcon}
        title="No readings in range"
        description={`No sample of ${parameter.name} falls inside the current filters. Widen the date range or clear a filter to see the comparison.`}
      />
    )
  }

  return <ParameterTrendChart points={points} parameter={parameter} height={height} />
}

function average(values: readonly number[]): number {
  if (values.length === 0) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}
