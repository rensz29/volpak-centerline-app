/**
 * Centerline parameters.
 *
 * Every parameter carries three comparable values, and the whole application is
 * organised around the gap between them:
 *
 *   target  — what engineering says the setpoint should be (the centerline)
 *   hmi     — what an operator actually dialled into the machine panel
 *   actual  — what the sensor is reading right now
 *
 * `actual` drifting from `target` is a *process deviation*; `hmi` differing from
 * `target` is *setpoint drift*, a separate and often more actionable finding.
 */

export type ParameterStatus = 'normal' | 'warning' | 'critical' | 'no-data'

export const PARAMETER_STATUSES: readonly ParameterStatus[] = [
  'normal',
  'warning',
  'critical',
  'no-data',
]

export type ParameterCategory =
  | 'temperature'
  | 'pressure'
  | 'level'
  | 'output'
  | 'speed'
  | 'quality'
  | 'setpoint'
  | 'product'

export const PARAMETER_CATEGORIES: readonly ParameterCategory[] = [
  'temperature',
  'pressure',
  'level',
  'output',
  'speed',
  'quality',
  'setpoint',
  'product',
]

export const CATEGORY_LABELS: Record<ParameterCategory, string> = {
  temperature: 'Temperature',
  pressure: 'Pressure',
  level: 'Level',
  output: 'Output',
  speed: 'Speed',
  quality: 'Quality',
  setpoint: 'Setpoints',
  product: 'Product information',
}

/** Stable machine-readable keys for the eight monitored parameters. */
export type ParameterCode =
  | 'sealing_temperature'
  | 'hopper_pressure'
  | 'hopper_level'
  | 'discharge_weight'
  | 'machine_speed'
  | 'filling_pressure'
  | 'product_weight'
  | 'jaw_temperature'

export const PARAMETER_CODES: readonly ParameterCode[] = [
  'sealing_temperature',
  'hopper_pressure',
  'hopper_level',
  'discharge_weight',
  'machine_speed',
  'filling_pressure',
  'product_weight',
  'jaw_temperature',
]

export interface ParameterDefinition {
  id: string
  code: ParameterCode
  name: string
  category: ParameterCategory
  unit: string
  description: string
  minAllowed: number
  maxAllowed: number
  /** Deviation from target, as a percentage, at which the value turns Warning. */
  warningTolerancePct: number
  /** Deviation from target, as a percentage, at which the value turns Critical. */
  criticalTolerancePct: number
  /** Decimal places used everywhere this parameter is rendered. */
  decimals: number
  machineIds: string[]
}

/** One row of the Digital Centerline table: a parameter on a machine running a SKU. */
export interface ParameterReading {
  id: string
  parameterId: string
  factoryId: string
  lineId: string
  machineId: string
  skuId: string
  targetSetpoint: number
  hmiSetpoint: number
  /** `null` means the sensor reported nothing — surfaces as the No Data status. */
  actualValue: number | null
  updatedAt: string
  updatedBy: string
}

/** A reading joined to its definition and plant context, with status derived. */
export interface CenterlineRow {
  id: string
  parameter: ParameterDefinition
  reading: ParameterReading
  factoryName: string
  lineName: string
  machineName: string
  skuCode: string
  skuName: string
  status: ParameterStatus
  /** actual − target; `null` when there is no actual value. */
  deviation: number | null
  deviationPct: number | null
  /** True when the operator's panel value differs from the engineering target. */
  hasSetpointDrift: boolean
}

export type SetpointField =
  | 'targetSetpoint'
  | 'hmiSetpoint'
  | 'warningTolerancePct'
  | 'criticalTolerancePct'
  | 'minAllowed'
  | 'maxAllowed'

export const SETPOINT_FIELD_LABELS: Record<SetpointField, string> = {
  targetSetpoint: 'Target setpoint',
  hmiSetpoint: 'HMI setpoint',
  warningTolerancePct: 'Warning tolerance',
  criticalTolerancePct: 'Critical tolerance',
  minAllowed: 'Minimum allowable',
  maxAllowed: 'Maximum allowable',
}

export interface SetpointChange {
  id: string
  parameterId: string
  machineId: string
  skuId: string
  field: SetpointField
  previousValue: number
  newValue: number
  unit: string
  reason: string
  changedBy: string
  changedAt: string
}

/** One point on a parameter trend chart. */
export interface TrendPoint {
  timestamp: string
  actual: number | null
  hmi: number
  target: number
  upperTolerance: number
  lowerTolerance: number
  /** Set when an alarm was raised at this timestamp, so the chart can mark it. */
  alarmSeverity: 'warning' | 'critical' | null
}
