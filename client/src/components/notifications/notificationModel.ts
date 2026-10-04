import type { DeliveryAttempt, DeliveryStatus, RouteOutcome } from '@/types/notificationsApi'

/** How the Notifications page names each state (ADR-0023). */

export const DELIVERY_LABEL: Record<DeliveryStatus, string> = {
  PENDING: 'Waiting',
  ATTEMPTING: 'Sending',
  DELIVERED: 'Delivered',
  SUBMITTED: 'Submitted',
  RETRYING: 'Retrying',
  PERMANENT_FAILURE: 'Failed',
  REDRIVEN: 'Re-driven',
}

export const DELIVERY_HINT: Record<DeliveryStatus, string> = {
  PENDING: 'Due now: the notifier sends it within seconds',
  ATTEMPTING: 'Being sent now',
  DELIVERED: 'The Teams flow accepted it (HTTP 202)',
  SUBMITTED: 'The relay accepted it (250); delivering it to the inbox is the relay’s job',
  RETRYING: 'An attempt failed: it is tried again on the schedule, for up to 24 h',
  PERMANENT_FAILURE: 'Every attempt for 24 h failed. An Administrator can re-drive it',
  REDRIVEN: 'An Administrator sent it again: see the new delivery',
}

export const DELIVERY_TONE: Record<DeliveryStatus, 'normal' | 'warning' | 'critical' | 'neutral' | 'outline'> = {
  PENDING: 'neutral',
  ATTEMPTING: 'neutral',
  DELIVERED: 'normal',
  SUBMITTED: 'normal',
  RETRYING: 'warning',
  PERMANENT_FAILURE: 'critical',
  REDRIVEN: 'outline',
}

export const OUTCOME_LABEL: Record<RouteOutcome, string> = {
  pending: 'Not routed yet',
  routed: 'Routed',
  unrouted: 'Not sent: no rule sends it',
  expired: 'Not sent: over 24 h old when routed',
  test: 'TEST, to one recipient',
}

export const ATTEMPT_LABEL: Record<DeliveryAttempt['outcome'], string> = {
  delivered: 'Delivered',
  submitted: 'Submitted',
  failed: 'Failed',
  interrupted: 'Cut short',
}
