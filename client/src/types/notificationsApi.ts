import type { RulesVersionStatus } from './configApi'

/** Notifications (ADR-0023): the channels, the routing, and the log of every message with its deliveries. */

export type Channel = 'teams' | 'email'
export type DeliveryStatus = 'PENDING' | 'ATTEMPTING' | 'DELIVERED' | 'SUBMITTED' | 'RETRYING' | 'PERMANENT_FAILURE' | 'REDRIVEN'
/** pending: not routed yet. routed, unrouted (no rule sends it), expired (over 24 h old), test */
export type RouteOutcome = 'pending' | 'routed' | 'unrouted' | 'expired' | 'test'
export type LogState = 'all' | 'waiting' | 'failed' | 'unrouted' | 'test'

/** The channel settings as the page may see them: never the flow URL or the relay password. */
export interface NotificationsConnection {
  appUrl: string
  line: string
  teams: { configured: boolean; where: string | null }
  email: {
    configured: boolean
    host: string
    port: number
    security: 'none' | 'starttls' | 'tls'
    username: string
    passwordSet: boolean
    sender: string
  }
}

export interface NotificationsForm {
  appUrl: string
  teamsUrl: string
  clearTeams: boolean
  smtpHost: string
  smtpPort: number
  smtpSecurity: 'none' | 'starttls' | 'tls'
  smtpUsername: string
  smtpPassword: string
  clearSmtpPassword: boolean
  emailSender: string
  reason: string
}

export interface RoutingRule {
  name: string
  types: string[]
  channel: Channel
  targets: string[]
}

export interface RoutingType {
  id: string
  label: string
  /** Critical kinds must reach someone before a version can be activated (ACT-03). */
  critical: boolean
}

export interface RoutingOverview {
  active: { number: number; since: string; reason: string; by: string | null } | null
  scheduled: { id: string; number: number; at: string; reason: string; by: string | null }[]
  latest: number | null
  versions: { number: number; createdAt: string; by: string | null; reason: string; basedOn: number | null; status: RulesVersionStatus }[]
  rules: RoutingRule[] | null
  warnings: string[]
  types: RoutingType[]
  channels: { id: Channel; label: string }[]
  created?: number
}

export interface RoutingVersion {
  number: number
  createdAt: string
  by: string | null
  reason: string
  basedOn: number | null
  rules: RoutingRule[]
  intact: boolean
  warnings: string[]
}

export interface RoutingProposal {
  source: string
  rules: RoutingRule[]
  warnings: string[]
}

export interface RoutingDraft {
  expectedLatest: number | null
  basedOn: number | null
  rules: RoutingRule[]
  reason: string
  activate: 'no' | 'now' | 'at'
  activateAt: string | null
}

export interface RoutingCheck {
  errors: { field: string; message: string }[]
  warnings: string[]
}

export interface DeliveryView {
  id: string
  channel: Channel
  target: string
  rule: string | null
  status: DeliveryStatus
  attempts: number
  createdAt: string
  nextAttemptAt: string | null
  finishedAt: string | null
  lastError: string | null
  redriveOf: string | null
  redrivenBy: string | null
  redriveReason: string | null
}

/** The message as sent: the same on every retry. */
export interface DeliveryContent {
  subject: string
  severity: string
  text: string
  facts: { name: string; value: string }[]
  link: string | null
  footer: string
  body?: string
  teams?: Record<string, unknown>
}

export interface DeliveryAttempt {
  attempt: number
  startedAt: string
  endedAt: string
  outcome: 'delivered' | 'submitted' | 'failed' | 'interrupted'
  response: string | null
}

export interface DeliveryDetail extends DeliveryView {
  messageId: string
  dedupKey: string
  content: DeliveryContent
  attemptLog: DeliveryAttempt[]
}

export interface NotificationSummary {
  id: string
  createdAt: string
  kind: string
  type: string
  typeLabel: string
  subject: string
  eventId: string | null
  outcome: RouteOutcome
  routingVersion: number | null
  deliveries: DeliveryView[]
}

export interface NotificationDetail extends Omit<NotificationSummary, 'deliveries'> {
  payload: Record<string, unknown>
  dedupKey: string
  route: { routedAt: string; routingVersion: number | null; matched: RoutingRule[]; outcome: RouteOutcome } | null
  deliveries: DeliveryDetail[]
}

export interface NotificationsList {
  notifications: NotificationSummary[]
  next: string | null
  counts: { waiting: number; failed: number }
}
