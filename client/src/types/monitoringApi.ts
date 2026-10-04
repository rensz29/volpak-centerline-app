import type { WorkflowRequest } from './workflowApi'

/**
 * Shapes of the api's monitoring endpoints (services/api/centerline_api/monitoring):
 * monitor-core's live state and its events. Every state is monitor-core's; the page judges nothing.
 * Measured values are decimal strings, as recorded (HMI-01).
 */

/** NO_TARGET: under a placeholder SKU there's no target, so the HMI setpoint isn't judged (ADR-0022) */
export type HmiState = 'AT_TARGET' | 'PENDING' | 'OPEN' | 'NO_TARGET'
export type Severity = 'NORMAL' | 'WARNING' | 'CRITICAL'

export interface Bands {
  warnLow: string
  warnHigh: string
  critLow: string
  critHigh: string
}

export interface LiveZone {
  id: string
  name: string
  channel: string
  /** False when monitor-core isn't running or its heartbeat is stale. */
  known: boolean
  setpoint?: string | null
  actual?: string | null
  target?: string | null
  bands?: Bands | null
  hmi?: HmiState
  hmiSince?: string | null
  hmiDue?: string | null
  hmiEvent?: string | null
  actualSeverity?: Severity
  actualPending?: Severity | null
  actualDue?: string | null
  actualEvent?: string | null
  hmiRulesVersion?: number | null
  actualRulesVersion?: number | null
  /** Why monitor-core isn't judging this zone right now, if it isn't (ADR-0017). */
  control?: ZoneControl | null
  events: string[]
}

export interface LiveParameter {
  id: string
  name: string
  unit: string | null
  zones: LiveZone[]
}

export interface MonitorStatus {
  instance: string
  startedAt: string
  beatAt: string
  ageS: number
  alive: boolean
  judging?: boolean
  reasons?: string[]
  sku?: string | null
  skuSeen?: string | null
  /** The mapping's placeholder SKU, if one stands in for the SKU field (ADR-0022) */
  skuPlaceholder?: string | null
  connected?: boolean
  actualPaused?: boolean
  stop?: 'unknown' | 'running' | 'stopped' | 'warmup'
  warmupUntil?: string | null
  rulesVersion?: number | null
  mappingVersion?: number | null
  registerVersion?: string | null
}

export interface MonitorEvent {
  id: string
  kind: 'HMI_MISMATCH' | 'ACTUAL'
  parameterId: string
  zoneId: string
  channel: string
  parameterName: string
  zoneName: string
  unit: string | null
  sku: string
  openedAt: string
  state: string
  severity: Severity | null
  open: boolean
  closedAt: string | null
  acknowledgedAt: string | null
  target: string | null
  hmi: string | null
  actual: string | null
  supersedes: string | null
  rulesVersion: number | null
}

export interface LiveView {
  serverTime: string
  monitor: MonitorStatus | null
  parameters: LiveParameter[]
  events: MonitorEvent[]
  counts: { zones: number; hmiOpen: number; warning: number; critical: number }
  control: ControlView
}

/** As monitor-core applied it: switched off (MON-01), under maintenance (MNT-01), or back on and waiting for fresh values. */
export type ZoneControl =
  | { state: 'off'; since: string; by: string; reason: string | null }
  | { state: 'maintenance'; window: string; scope: 'line' | 'zones'; reason: string; plannedStart: string; plannedEnd: string }
  | { state: 'waiting'; since: string }

export interface ZoneRef {
  channel: string
  parameterId: string
  parameterName: string
  zoneName: string
}

export interface SwitchedOffZone extends ZoneRef {
  since: string
  by: string
  reason: string | null
}

export type WindowStatus = 'scheduled' | 'active' | 'overdue' | 'ended' | 'cancelled'

export interface MaintenanceWindow {
  id: string
  scope: 'line' | 'zones'
  status: WindowStatus
  reason: string
  zones: ZoneRef[]
  plannedStart: string
  plannedEnd: string
  createdAt: string
  createdBy: string
  endedAt: string | null
  endedBy: string | null
}

/** Zones switched off and maintenance windows not ended, from the database (ADR-0017). */
export interface ControlView {
  serverTime: string
  switchedOff: SwitchedOffZone[]
  maintenance: MaintenanceWindow[]
}

/** Open events by kind and severity: the sidebar badge and the bell. */
export interface EventCounts {
  open: number
  hmi: number
  warning: number
  critical: number
  unacknowledgedCritical: number
}

export interface EventFilters {
  open?: boolean
  kind?: 'HMI_MISMATCH' | 'ACTUAL'
  severity?: Severity
  /** Ever reached that severity (a Critical that went back to Warning still counts) */
  reached?: Severity
  /** A zone, e.g. P02.V1 */
  channel?: string
  /** ISO times: opened at or after `since`, before `until` */
  since?: string
  until?: string
  /** The `next` of the previous page */
  before?: string
  limit?: number
}

export interface EventDetail extends MonitorEvent {
  rule: Record<string, unknown>
  versions: { rules: number; mapping: number; register: string }
  transitions: { seq: number; at: string; state: string; inputs: Record<string, string | null> }[]
  /** status: pending (not routed yet), unrouted, expired, waiting, sent or failed (ADR-0023) */
  notifications: { id: string; kind: string; at: string; status: string; deliveries: { channel: string; target: string; status: string }[] }[]
  /** A Manager's, one per Critical period (ACT-04); monitor-core applies each within 2 s. */
  acknowledgments: { at: string; by: string | null; note: string | null; criticalPeriod: number | null }[]
  /** The reason workflow: one request per shift, with what was written (ADR-0025) */
  requests: WorkflowRequest[]
  /** Whether a Manager can acknowledge it now: an open Critical not acknowledged in this period. */
  acknowledgeable: boolean
}

export interface BriefChange {
  id: string
  channel: string
  parameterName: string
  zoneName: string
  unit: string | null
  sku: string
  mode: 'lightweight' | 'cleared_before_trigger'
  startedAt: string
  endedAt: string
  seconds: number
  target: string | null
  hmi: string | null
}
