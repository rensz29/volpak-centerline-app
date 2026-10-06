import type { RequestStatus, WorkflowRequest } from '@/types/workflowApi'

/** How the Reasons page names each state of a request (ADR-0025). */
export const STATUS_LABEL: Record<RequestStatus, string> = {
  waiting_reason: 'Waiting for the reason',
  waiting_answers: 'Waiting for the answers',
  waiting_guidance: "Waiting for a Manager's guidance",
  waiting_acknowledgment: 'Waiting for the operator to acknowledge',
  done: 'Done',
  not_answered: 'Not answered: its shift ended',
  resolved: 'Closed: back on target',
  superseded: 'Closed: a newer mismatch replaced it',
  cancelled: 'Closed: the zone was switched off',
}

export const STATUS_TONE: Record<RequestStatus, 'warning' | 'normal' | 'neutral' | 'critical' | 'outline'> = {
  waiting_reason: 'warning',
  waiting_answers: 'warning',
  waiting_guidance: 'warning',
  waiting_acknowledgment: 'warning',
  done: 'normal',
  not_answered: 'critical',
  resolved: 'neutral',
  superseded: 'neutral',
  cancelled: 'neutral',
}

/** Whether this person is the one the request waits for. */
export function waitsFor(r: WorkflowRequest, roles: { isOperator: boolean; isManager: boolean }): boolean {
  if (r.next === null) return false
  return r.next === 'guidance' ? roles.isManager : roles.isOperator
}

export function withUnit(v: string | null, unit: string | null): string {
  return v === null ? '—' : unit ? `${v} ${unit}` : v
}
