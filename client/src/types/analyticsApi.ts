/**
 * Shapes of the api's Analytics & Correlation endpoints
 * (services/api/centerline_api/analytics/service.py). The server computes
 * everything from Timebase; the page only renders it (ANA-02, ANA-15).
 */

export type BucketCode = 'PT10S' | 'PT30S' | 'PT1M' | 'PT5M' | 'PT15M' | 'PT1H'
export type AggregationCode = 'AVG' | 'MIN' | 'MAX'
export type ShiftCode = 'ALL' | 'A' | 'B' | 'C'
export type GroupByCode = 'NONE' | 'SHIFT' | 'PRODUCTION_DATE'

export type VariableKind = 'actual' | 'setpoint'

export interface AnalyticsVariable {
  /** "<parameter>.<zone>.<kind>", e.g. "P02.V3.setpoint" (ADR-0009) */
  channel: string
  /** "<parameter>.<zone>", shared by a zone's actual and setpoint */
  zoneChannel: string
  kind: VariableKind
  /** What people see, e.g. "Vertical 3 · Setpoint": zone names, never parameter IDs */
  label: string
  parameterId: string
  parameterName: string
  zoneId: string
  zoneName: string
  unit: string | null
  area: string
  /** Set when the register flags the variable's tags for review (e.g. O-19). */
  caution: string | null
}

export interface Option<T extends string> {
  code: T
  label: string
}

export interface AnalyticsOptions {
  variables: AnalyticsVariable[]
  buckets: (Option<BucketCode> & { seconds: number })[]
  aggregations: Option<AggregationCode>[]
  shifts: Option<ShiftCode>[]
  groupings: Option<GroupByCode>[]
  defaults: {
    x: string | null
    y: string | null
    bucket: BucketCode
    aggregation: AggregationCode
    shift: ShiftCode
    groupBy: GroupByCode
    rangeHours: number
  }
  limits: { maxRangeDays: number; pairLimit: number; visibleGroups: number }
  sku: { available: boolean; reason: string | null }
  ranges: { loaded: boolean; source: string | null; sha256: string | null; problems: string[] }
  timezone: string
  note: string
  registerVersion: string
}

export interface AnalyticsQueryRequest {
  from: string
  to: string
  x: string
  y: string
  bucket: BucketCode
  aggregation: AggregationCode
  shift: ShiftCode
  groupBy: GroupByCode
  groupStats: boolean
}

export interface Correlation {
  n: number
  computable: boolean
  reason: string | null
  r: number | null
  rSquared: number | null
  slope: number | null
  intercept: number | null
  equation: string | null
  strength: string | null
  direction: 'positive' | 'negative' | 'none' | null
}

export interface Descriptive {
  n: number
  min: number | null
  max: number | null
  mean: number | null
  sd: number | null
}

export interface Exclusions {
  samples: number
  badQuality: number
  null: number
  nonNumeric: number
  nan: number
  infinite: number
  outOfRange: number
  unreadableSeconds: number
  gapSeconds: number
}

export interface AnalyticsWarning {
  code: string
  message: string
}

export interface GroupResult {
  key: string
  label: string
  n: number
  warning: 'INSUFFICIENT_DATA' | 'LOW_SAMPLE_SIZE' | null
  correlation?: Correlation
}

export interface AnalyticsResult {
  query: AnalyticsQueryRequest & { bucketSeconds: number; sku: string | null }
  x: AnalyticsVariable
  y: AnalyticsVariable
  exclusions: { x: Exclusions; y: Exclusions }
  buckets: {
    total: number
    xValid: number
    yValid: number
    bothValid: number
    outsideShift: number
    paired: number
  }
  sizeGuard: { limit: number; exceeded: boolean; recommendedBucket: BucketCode | null }
  /** Columnar pairs: bucket start (epoch ms), X, Y and the group key when grouping. */
  pairs: { t: number[]; x: number[]; y: number[]; g: string[] | null } | null
  statistics: { correlation: Correlation; x: Descriptive; y: Descriptive } | null
  groups: { by: GroupByCode; items: GroupResult[]; hidden: number } | null
  warnings: AnalyticsWarning[]
  note: string
  meta: {
    generatedAt: string
    durationMs: number
    fetchMs: number
    historianClockOffsetS: number | null
    timezone: string
  }
}

/** RFC 9457 problem document, as the api returns for every error. */
export interface ProblemDocument {
  type?: string
  title?: string
  status?: number
  detail?: string
  errors?: { field: string; message: string }[]
}
