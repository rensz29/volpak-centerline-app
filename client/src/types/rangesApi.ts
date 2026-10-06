import type { RulesVersionStatus } from './configApi'

/**
 * Analytics-valid ranges (ANA-10/11, ADR-0029): the CSV an Administrator uploads, one row per register
 * parameter, versioned in the database like the rules (services/api/centerline_api/config/ranges_store.py).
 */

export interface RangeRow {
  parameterId: string
  parameterName?: string | null
  unit: string | null
  validMin: number
  validMax: number
}

export interface RangesVersionSummary {
  number: number
  createdAt: string
  by: string | null
  reason: string
  /** The file's name as uploaded */
  source: string
  sha256: string
  registerVersion: string
  status: RulesVersionStatus
}

export interface RangesOverview {
  active: { number: number; since: string; reason: string; by: string | null } | null
  scheduled: { id: string; number: number; at: string; reason: string; by: string | null }[]
  latest: number | null
  versions: RangesVersionSummary[]
  /** The version in effect's rows; null when none is */
  rows: RangeRow[] | null
  /** Why the version in effect isn't applied: it no longer fits the register */
  problems: string[]
  parameters: { parameterId: string; unit: string | null }[]
  registerVersion: string
  created?: number
}

export interface RangesVersion {
  number: number
  createdAt: string
  by: string | null
  reason: string
  source: string
  sha256: string
  registerVersion: string
  /** The stored file still matches its SHA-256 */
  intact: boolean
  rows: RangeRow[]
  problems: string[]
}

export interface RangesCheck {
  problems: string[]
  sha256: string | null
  rows: RangeRow[] | null
}

export interface RangesUpload {
  source: string
  contentBase64: string
}

export interface RangesDraft extends RangesUpload {
  expectedLatest: number | null
  reason: string
  activate: 'no' | 'now' | 'at'
  activateAt: string | null
}
