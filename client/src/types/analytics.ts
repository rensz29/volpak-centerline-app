import type { Shift } from './entities'
import type { ParameterCode, ParameterStatus } from './parameters'

/**
 * A single instant of process data for one machine, carrying *every* parameter
 * at once.
 *
 * The wide shape is deliberate: scatter analysis correlates two parameters
 * observed at the same moment (hopper pressure against hopper level), which a
 * long/tall table of one-parameter-per-row cannot express without a join. One
 * dataset therefore drives the scatter chart, the trend comparison, the summary
 * statistics and the raw records table, with no parallel fixtures to keep in
 * sync.
 */
export interface ProcessSample {
  id: string
  timestamp: string
  factoryId: string
  lineId: string
  machineId: string
  skuId: string
  shift: Shift
  values: Record<ParameterCode, ParameterSample>
}

export interface ParameterSample {
  /** `null` models a sensor dropout, which renders as No Data. */
  actual: number | null
  hmi: number
  target: number
}

/** A ProcessSample flattened to one parameter, for the raw records table. */
export interface AnalyticsRecord {
  id: string
  timestamp: string
  factoryName: string
  lineName: string
  machineName: string
  skuCode: string
  parameterName: string
  parameterCode: ParameterCode
  unit: string
  decimals: number
  target: number
  hmi: number
  actual: number | null
  deviation: number | null
  status: ParameterStatus
  shift: Shift
}

export type ChartType = 'scatter' | 'line'

export interface AnalyticsFilters {
  factoryId: string
  lineId: string
  machineId: string
  skuId: string
  shift: Shift | 'all'
  startDate: string
  endDate: string
}

/** Pearson correlation plus the fitted line used to draw the trend overlay. */
export interface CorrelationResult {
  coefficient: number
  slope: number
  intercept: number
  sampleCount: number
  strength: CorrelationStrength
  direction: 'positive' | 'negative' | 'none'
}

export type CorrelationStrength =
  | 'negligible'
  | 'weak'
  | 'moderate'
  | 'strong'
  | 'very strong'

export interface SummaryStatistics {
  totalRecords: number
  average: number
  minimum: number
  maximum: number
  standardDeviation: number
  correlationCoefficient: number | null
  averageActualVsHmiDeviation: number
  alarmCount: number
  timeWithinTargetPct: number
}
