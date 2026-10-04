import type {
  Alarm,
  AlarmRow,
  AnalyticsRecord,
  CenterlineRow,
  Factory,
  Machine,
  ParameterCode,
  ParameterDefinition,
  ParameterReading,
  ProcessSample,
  ProductionLine,
  Shift,
  Sku,
  SummaryStatistics,
  TrendPoint,
} from '@/types'
import { calcDeviation, calcDeviationPct, deriveStatus } from './status'
import { mean, maximum, minimum, pearson, standardDeviation } from './stats'

/** Lookup tables passed to the join helpers below. */
export interface PlantLookups {
  factories: readonly Factory[]
  lines: readonly ProductionLine[]
  machines: readonly Machine[]
  skus: readonly Sku[]
  parameters: readonly ParameterDefinition[]
}

interface IndexedLookups {
  factory: Map<string, Factory>
  line: Map<string, ProductionLine>
  machine: Map<string, Machine>
  sku: Map<string, Sku>
  parameter: Map<string, ParameterDefinition>
  parameterByCode: Map<ParameterCode, ParameterDefinition>
}

export function indexLookups(lookups: PlantLookups): IndexedLookups {
  return {
    factory: new Map(lookups.factories.map((f) => [f.id, f])),
    line: new Map(lookups.lines.map((l) => [l.id, l])),
    machine: new Map(lookups.machines.map((m) => [m.id, m])),
    sku: new Map(lookups.skus.map((s) => [s.id, s])),
    parameter: new Map(lookups.parameters.map((p) => [p.id, p])),
    parameterByCode: new Map(lookups.parameters.map((p) => [p.code, p])),
  }
}

/**
 * Join readings to their definitions and plant context, deriving status,
 * deviation and setpoint drift. Nothing downstream re-derives these — the table,
 * summary cards, drawer and CSV export all read the same computed row.
 */
export function buildCenterlineRows(
  readings: readonly ParameterReading[],
  lookups: PlantLookups,
): CenterlineRow[] {
  const index = indexLookups(lookups)
  const rows: CenterlineRow[] = []

  for (const reading of readings) {
    const parameter = index.parameter.get(reading.parameterId)
    if (!parameter) continue

    const status = deriveStatus(
      reading.actualValue,
      reading.targetSetpoint,
      parameter.warningTolerancePct,
      parameter.criticalTolerancePct,
    )

    rows.push({
      id: reading.id,
      parameter,
      reading,
      factoryName: index.factory.get(reading.factoryId)?.name ?? 'Unknown factory',
      lineName: index.line.get(reading.lineId)?.name ?? 'Unknown line',
      machineName: index.machine.get(reading.machineId)?.name ?? 'Unknown machine',
      skuCode: index.sku.get(reading.skuId)?.code ?? '—',
      skuName: index.sku.get(reading.skuId)?.name ?? 'Unknown SKU',
      status,
      deviation: calcDeviation(reading.actualValue, reading.targetSetpoint),
      deviationPct: calcDeviationPct(reading.actualValue, reading.targetSetpoint),
      hasSetpointDrift: reading.hmiSetpoint !== reading.targetSetpoint,
    })
  }

  return rows
}

export function buildAlarmRows(
  alarms: readonly Alarm[],
  lookups: PlantLookups,
): AlarmRow[] {
  const index = indexLookups(lookups)

  return alarms.map((alarm) => {
    const parameter = index.parameter.get(alarm.parameterId)
    return {
      ...alarm,
      parameterName: parameter?.name ?? 'Unknown parameter',
      parameterUnit: parameter?.unit ?? alarm.unit,
      parameterDecimals: parameter?.decimals ?? 1,
      factoryName: index.factory.get(alarm.factoryId)?.name ?? 'Unknown factory',
      lineName: index.line.get(alarm.lineId)?.name ?? 'Unknown line',
      machineName: index.machine.get(alarm.machineId)?.name ?? 'Unknown machine',
      skuCode: index.sku.get(alarm.skuId)?.code ?? '—',
    }
  })
}

/**
 * Trend series for one parameter on one machine.
 *
 * `currentReading` is appended as the final point so the chart ends on exactly
 * the value the Digital Centerline table shows — the live reading is held
 * separately from the historical series, and this is where the two are rejoined
 * for display.
 */
export function buildTrend(
  samples: readonly ProcessSample[],
  code: ParameterCode,
  machineId: string,
  parameter: ParameterDefinition,
  currentReading?: ParameterReading,
): TrendPoint[] {
  const points: TrendPoint[] = []

  for (const sample of samples) {
    if (sample.machineId !== machineId) continue
    const value = sample.values[code]
    points.push(toTrendPoint(sample.timestamp, value.actual, value.hmi, value.target, parameter))
  }

  if (currentReading) {
    points.push(
      toTrendPoint(
        currentReading.updatedAt,
        currentReading.actualValue,
        currentReading.hmiSetpoint,
        currentReading.targetSetpoint,
        parameter,
      ),
    )
  }

  return points.sort((a, b) => a.timestamp.localeCompare(b.timestamp))
}

function toTrendPoint(
  timestamp: string,
  actual: number | null,
  hmi: number,
  target: number,
  parameter: ParameterDefinition,
): TrendPoint {
  const status = deriveStatus(
    actual,
    target,
    parameter.warningTolerancePct,
    parameter.criticalTolerancePct,
  )

  return {
    timestamp,
    actual,
    hmi,
    target,
    upperTolerance: round(target * (1 + parameter.warningTolerancePct / 100), 3),
    lowerTolerance: round(target * (1 - parameter.warningTolerancePct / 100), 3),
    alarmSeverity: status === 'critical' ? 'critical' : status === 'warning' ? 'warning' : null,
  }
}

function round(value: number, decimals: number): number {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

/**
 * Flatten wide process samples into one row per (sample, parameter) for the raw
 * records table. Only the requested parameter codes are expanded, which keeps
 * the table at a few hundred rows rather than a few thousand.
 */
export function buildAnalyticsRecords(
  samples: readonly ProcessSample[],
  codes: readonly ParameterCode[],
  lookups: PlantLookups,
): AnalyticsRecord[] {
  const index = indexLookups(lookups)
  const records: AnalyticsRecord[] = []

  for (const sample of samples) {
    for (const code of codes) {
      const parameter = index.parameterByCode.get(code)
      const value = sample.values[code]
      if (!parameter) continue

      records.push({
        id: `${sample.id}-${code}`,
        timestamp: sample.timestamp,
        factoryName: index.factory.get(sample.factoryId)?.name ?? '—',
        lineName: index.line.get(sample.lineId)?.name ?? '—',
        machineName: index.machine.get(sample.machineId)?.name ?? '—',
        skuCode: index.sku.get(sample.skuId)?.code ?? '—',
        parameterName: parameter.name,
        parameterCode: code,
        unit: parameter.unit,
        decimals: parameter.decimals,
        target: value.target,
        hmi: value.hmi,
        actual: value.actual,
        deviation: calcDeviation(value.actual, value.target),
        status: deriveStatus(
          value.actual,
          value.target,
          parameter.warningTolerancePct,
          parameter.criticalTolerancePct,
        ),
        shift: sample.shift,
      })
    }
  }

  return records
}

/** Paired X/Y observations for the scatter chart, dropping incomplete samples. */
export interface ScatterPoint {
  id: string
  x: number
  y: number
  skuId: string
  skuCode: string
  machineId: string
  machineName: string
  lineName: string
  shift: Shift
  timestamp: string
}

export function buildScatterPoints(
  samples: readonly ProcessSample[],
  xCode: ParameterCode,
  yCode: ParameterCode,
  lookups: PlantLookups,
): ScatterPoint[] {
  const index = indexLookups(lookups)
  const points: ScatterPoint[] = []

  for (const sample of samples) {
    const x = sample.values[xCode].actual
    const y = sample.values[yCode].actual
    if (x === null || y === null) continue

    points.push({
      id: sample.id,
      x,
      y,
      skuId: sample.skuId,
      skuCode: index.sku.get(sample.skuId)?.code ?? '—',
      machineId: sample.machineId,
      machineName: index.machine.get(sample.machineId)?.name ?? '—',
      lineName: index.line.get(sample.lineId)?.name ?? '—',
      shift: sample.shift,
      timestamp: sample.timestamp,
    })
  }

  return points
}

/**
 * How many distinct SKUs and machines actually contribute to a correlation.
 *
 * This must be measured on the paired points, not on the filtered samples: a
 * machine that lacks a sensor for one of the two parameters contributes no
 * points at all, and warning about it would be a false alarm.
 */
export function describeSpan(points: readonly ScatterPoint[]): {
  skuCount: number
  machineCount: number
} {
  return {
    skuCount: new Set(points.map((point) => point.skuId)).size,
    machineCount: new Set(points.map((point) => point.machineId)).size,
  }
}

/** Summary statistics for the analytics cards, computed over the filtered set. */
export function computeStatistics(
  samples: readonly ProcessSample[],
  focusCode: ParameterCode,
  comparisonCode: ParameterCode,
  parameter: ParameterDefinition,
): SummaryStatistics {
  const actuals: number[] = []
  const hmiDeviations: number[] = []
  const focusSeries: number[] = []
  const comparisonSeries: number[] = []
  let alarmCount = 0
  let withinTarget = 0
  let evaluated = 0

  for (const sample of samples) {
    const focus = sample.values[focusCode]
    const comparison = sample.values[comparisonCode]

    if (focus.actual !== null) {
      actuals.push(focus.actual)
      hmiDeviations.push(focus.actual - focus.hmi)

      const status = deriveStatus(
        focus.actual,
        focus.target,
        parameter.warningTolerancePct,
        parameter.criticalTolerancePct,
      )
      evaluated += 1
      if (status === 'normal') withinTarget += 1
      if (status === 'warning' || status === 'critical') alarmCount += 1
    }

    if (focus.actual !== null && comparison.actual !== null) {
      focusSeries.push(focus.actual)
      comparisonSeries.push(comparison.actual)
    }
  }

  return {
    totalRecords: samples.length,
    average: mean(actuals),
    minimum: minimum(actuals),
    maximum: maximum(actuals),
    standardDeviation: standardDeviation(actuals),
    correlationCoefficient:
      focusSeries.length >= 3 ? pearson(focusSeries, comparisonSeries) : null,
    averageActualVsHmiDeviation: mean(hmiDeviations),
    alarmCount,
    timeWithinTargetPct: evaluated === 0 ? 0 : (withinTarget / evaluated) * 100,
  }
}
