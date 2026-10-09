/** GET /api/v1/health (ADR-0038): each part of Centerline graded by the api. Administrators only. */

export type HealthState = 'ok' | 'unknown' | 'warning' | 'critical'

export interface HealthCheck {
  id: string
  /** The page's section: Monitoring, Notifications, Storage and backups, Database, Uploads and history */
  area: string
  title: string
  state: HealthState
  /** What's wrong and what to do, in the page's words */
  summary: string
  /** Where to act, a route in the app, or null */
  link: string | null
}

export interface HealthReport {
  overall: HealthState
  checks: HealthCheck[]
  checkedAt: string
  registerVersion: string
}
