import type { NotificationsConnection } from './notificationsApi'

/**
 * Shapes of the api's Configuration endpoints (services/api/centerline_api/config).
 * Secrets never come back from the api: only whether one is set.
 */

export type HistorianAuth = 'none' | 'bearer' | 'basic'
export type ParameterStatus = 'active' | 'analytics_only' | 'awaiting_tag'

export interface HistorianConnection {
  baseUrl: string
  dataset: string
  timeoutS: number
  verifyTls: boolean
  authType: HistorianAuth
  username: string
  tokenSet: boolean
  passwordSet: boolean
  source: string
}

export interface MqttConnection {
  configured: boolean
  host: string
  port: number
  protocol: '5' | '3.1.1'
  tlsEnabled: boolean
  verifyHostname: boolean
  caSet: boolean
  username: string
  passwordSet: boolean
  clientId: string
  keepaliveS: number
  subscriptions: string[]
  freshnessS: Record<string, number>
}

export interface Connections {
  historian: HistorianConnection
  mqtt: MqttConnection
  /** The Teams flow and the SMTP relay (ADR-0023) */
  notifications: NotificationsConnection
  updatedAt: string | null
}

export interface HistorianForm {
  baseUrl: string
  dataset: string
  timeoutS: number
  verifyTls: boolean
  authType: HistorianAuth
  username: string
  /** Empty keeps the saved secret. */
  token: string
  password: string
  reason: string
}

export interface MqttForm {
  host: string
  port: number
  protocol: '5' | '3.1.1'
  tlsEnabled: boolean
  verifyHostname: boolean
  caPem: string
  clearCa: boolean
  username: string
  password: string
  clearPassword: boolean
  clientId: string
  keepaliveS: number
  subscriptions: string[]
  freshnessS: Record<string, number>
  reason: string
}

export interface HistorianCheck {
  ok: boolean
  error?: string | null
  latencyMs?: number
  datasets?: string[]
  datasetFound?: boolean
  tagsUnderNamespace?: number
  namespace?: string
  clockOffsetS?: number | null
}

export interface MqttCheck {
  connected: boolean
  error?: string
  connect?: string
  subscriptions?: string[] | null
  listenedS?: number
  topicCount?: number
  topics?: {
    topic: string
    messages: number
    perMinute: number
    retained: boolean
    format: string | null
    fields: number
    fieldNames?: string[]
    sample: string | null
  }[]
  mapped?: { label: string; tag: string; topic: string; field: string | null }[]
  missing?: { label: string; tag: string }[]
  skuCandidates?: { topic: string; field: string; value: string }[]
  warnings?: string[]
}

export interface HistorianTag {
  tag: string
  area: string
  type: string
  usedBy: string | null
}

export interface LatestValue {
  value: number | string | boolean | null
  quality: number
  at: string
}

export interface RegisterZone {
  id: string
  name: string
  setpoint: string | null
  actual: string | null
}

export interface RegisterParameter {
  id: string
  name: string
  unit: string | null
  status: ParameterStatus
  note: string | null
  review: string | null
  candidateTags: string[]
  zones: RegisterZone[]
}

export interface AuditEntry {
  at: string
  user: string | null
  action: string
  summary: string | null
  reason: string | null
  from?: string | null
  to?: string | null
}

export interface RegisterView {
  version: string
  namespace: string
  line: { id: string; name: string } | null
  sku: { status: string; tag: string | null; note?: string } | null
  parameters: RegisterParameter[]
  audit: AuditEntry[]
  /** Set when config/parameter-register.json holds hand edits the database doesn't have. */
  fileWarning: string | null
}

export interface ParameterUpdate {
  baseVersion: string
  status: ParameterStatus
  zones: RegisterZone[]
  reason: string
}

// -- Monitoring rules (ADR-0012) ------------------------------------------------------

export type BriefChangeMode = 'do_not_record' | 'lightweight' | 'cleared_before_trigger'

/** One scope of a rules version. sku / zoneId null = every SKU / every zone; a null field is inherited. */
export interface RuleRow {
  sku: string | null
  parameterId: string
  zoneId: string | null
  target: number | null
  warnLow: number | null
  warnHigh: number | null
  critLow: number | null
  critHigh: number | null
  mismatchDelayS: number | null
  warningDelayS: number | null
  criticalDelayS: number | null
  recoveryDelayS: number | null
  briefChangeMode: BriefChangeMode | null
  warningNotifications: boolean | null
}

export type RuleField = Exclude<keyof RuleRow, 'sku' | 'parameterId' | 'zoneId'>

export interface RuleDefaults {
  mismatchDelayS: number
  warningDelayS: number
  criticalDelayS: number
  recoveryDelayS: number
  briefChangeMode: BriefChangeMode
  warningNotifications: boolean
}

export interface RulesSettings {
  pauseWhenStopped: { enabled: boolean; longStopMin: number; warmupMin: number }
  defaults: RuleDefaults
}

export interface ReadinessGap {
  parameterId: string
  zoneId: string
  label: string
  missing: RuleField[]
}

export type RulesVersionStatus = 'active' | 'scheduled' | 'previous' | 'saved'

export interface RulesVersionSummary {
  number: number
  createdAt: string
  reason: string
  basedOn: number | null
  registerVersion: string
  status: RulesVersionStatus
}

export interface Sku {
  code: string
  name: string
}

export interface RulesOverview {
  /** `by`: who activated it; null for activations made before sign-in existed */
  active: { number: number; since: string; reason: string; by: string | null } | null
  scheduled: { id: string; number: number; at: string; reason: string; by: string | null }[]
  latest: number | null
  versions: RulesVersionSummary[]
  activations: {
    id: string
    number: number
    at: string
    createdAt: string
    reason: string
    by: string | null
    cancelledAt: string | null
    cancelledBy: string | null
    cancelReason: string | null
  }[]
  skus: Sku[]
  /** Per SKU, against the version in effect: an empty list means the SKU can be monitored. */
  readiness: Record<string, ReadinessGap[]>
  registerVersion: string
  created?: number
}

export interface RulesVersion {
  number: number
  createdAt: string
  reason: string
  basedOn: number | null
  registerVersion: string
  /** False when the stored content no longer matches its hash. */
  intact: boolean
  settings: RulesSettings
  rules: RuleRow[]
  readiness: Record<string, ReadinessGap[]>
}

export interface RulesProposal {
  source: string
  settings: RulesSettings
  rules: (Partial<RuleRow> & { parameterId: string })[]
}

export interface RulesDraft {
  expectedLatest: number | null
  basedOn: number | null
  settings: RulesSettings
  rules: RuleRow[]
  reason: string
  activate: 'no' | 'now' | 'at'
  activateAt: string | null
}

export interface RulesCheck {
  errors: { field: string; message: string }[]
  readiness: Record<string, ReadinessGap[]>
}

// -- Tag mappings (ADR-0013) ---------------------------------------------------------

/** Where a register tag arrives: a topic, and a JSON field of its message (null: the whole payload). */
export interface MappingRow {
  tag: string
  topic: string
  field: string | null
}

export interface SkuPlace {
  topic: string
  field: string
}

export interface RequiredTag {
  tag: string
  kind: 'setpoint' | 'actual' | 'context'
  parameterId: string | null
  parameterName: string | null
  zoneId: string | null
  zoneName: string | null
  label: string
}

export interface MappingCoverage {
  required: number
  mapped: number
  missing: RequiredTag[]
}

export interface MappingVersionSummary extends RulesVersionSummary {
  source: string
}

export interface MappingsOverview {
  active: RulesOverview['active']
  scheduled: RulesOverview['scheduled']
  latest: number | null
  versions: MappingVersionSummary[]
  activations: RulesOverview['activations']
  /** The tags monitor-core needs, in register order. */
  required: RequiredTag[]
  /** Of the version in effect, against the current register. */
  coverage: MappingCoverage | null
  sku: SkuPlace | null
  /** A code standing in for the SKU field while the machine publishes none: actual values only (ADR-0022) */
  skuPlaceholder: string | null
  subscriptions: string[]
  registerVersion: string
  created?: number
}

export interface MappingVersion {
  number: number
  createdAt: string
  reason: string
  source: string
  basedOn: number | null
  registerVersion: string
  intact: boolean
  rows: MappingRow[]
  sku: SkuPlace | null
  skuPlaceholder: string | null
  coverage: MappingCoverage
  warnings: string[]
}

export interface MappingDraft {
  expectedLatest: number | null
  basedOn: number | null
  rows: MappingRow[]
  sku: SkuPlace | null
  skuPlaceholder?: string | null
  source: string
  reason: string
  activate: 'no' | 'now' | 'at'
  activateAt: string | null
}

export interface MappingCheck {
  errors: { field: string; message: string }[]
  warnings: string[]
  coverage: MappingCoverage
}

export interface MappingImport {
  rows: MappingRow[]
  sku: SkuPlace | null
  ignored: string[]
  notSeen: string[]
  problems: { line: number; message: string }[]
  source: string
}

export interface MappingDiscovery {
  connected: boolean
  error?: string
  listenedS?: number
  rows?: MappingRow[]
  notSeen?: string[]
  skuCandidates?: { topic: string; field: string; value: string }[]
  topics?: string[]
  /** The JSON fields heard on each topic. */
  fields?: Record<string, string[]>
  warnings?: string[]
}
