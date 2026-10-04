export type AlarmSeverity = 'critical' | 'warning' | 'info'

export const ALARM_SEVERITIES: readonly AlarmSeverity[] = ['critical', 'warning', 'info']

export type AlarmStatus = 'active' | 'acknowledged' | 'resolved'

export const ALARM_STATUSES: readonly AlarmStatus[] = [
  'active',
  'acknowledged',
  'resolved',
]

export const ALARM_STATUS_LABELS: Record<AlarmStatus, string> = {
  active: 'Active',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
}

export const ALARM_SEVERITY_LABELS: Record<AlarmSeverity, string> = {
  critical: 'Critical',
  warning: 'Warning',
  info: 'Info',
}

export interface Alarm {
  id: string
  /** Human-facing reference shown in tables and dialogs, e.g. "ALM-1042". */
  reference: string
  parameterId: string
  factoryId: string
  lineId: string
  machineId: string
  skuId: string
  severity: AlarmSeverity
  status: AlarmStatus
  message: string
  targetValue: number
  hmiValue: number
  actualValue: number | null
  deviation: number | null
  deviationPct: number | null
  unit: string
  raisedAt: string
  acknowledgedAt: string | null
  acknowledgedBy: string | null
  resolvedAt: string | null
  resolvedBy: string | null
  resolutionNote: string | null
}

/** An alarm joined to its plant and parameter context for display. */
export interface AlarmRow extends Alarm {
  parameterName: string
  parameterUnit: string
  parameterDecimals: number
  factoryName: string
  lineName: string
  machineName: string
  skuCode: string
}
