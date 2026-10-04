import { useMemo } from 'react'

import type { AnalyticsResult } from '@/types/analyticsApi'

import { EChart } from './EChart'
import { readPalette, scatterOption, trendOption, variableLabel } from './chartOptions'

export function ScatterView({ result }: { result: AnalyticsResult }) {
  const option = useMemo(() => scatterOption(result, readPalette()), [result])
  return (
    <EChart
      option={option}
      label={`Scatter of ${variableLabel(result.y)} against ${variableLabel(result.x)}, ${result.buckets.paired} paired buckets`}
    />
  )
}

export function TrendView({ result }: { result: AnalyticsResult }) {
  const option = useMemo(() => trendOption(result, readPalette()), [result])
  return (
    <EChart
      option={option}
      label={`Trend of ${variableLabel(result.x)} and ${variableLabel(result.y)} over time`}
    />
  )
}
