/** The reason workflow (ADR-0025): each HMI mismatch asks that shift's operator why. */

export type RequestStatus =
  | 'waiting_reason'
  | 'waiting_answers'
  | 'waiting_guidance'
  | 'waiting_acknowledgment'
  | 'done'
  | 'not_answered'
  | 'resolved'
  | 'superseded'
  | 'cancelled'

export type Step = 'reason' | 'answers' | 'guidance' | 'acknowledgment'

export interface ShiftView {
  code: 'A' | 'B' | 'C'
  label: string
  startsAt: string
  endsAt: string
}

export interface WorkflowEntry {
  kind: 'reason' | 'answer' | 'guidance' | 'acknowledgment'
  at: string
  by: string
  /** For an answer: the question as it was asked */
  question: string | null
  /** As typed, English or Filipino */
  body: string
}

export interface WorkflowRequest {
  id: string
  status: RequestStatus
  /** The step it waits for; null once closed */
  next: Step | null
  createdAt: string
  escalatedAt: string | null
  closedAt: string | null
  shift: ShiftView
  event: {
    id: string
    channel: string
    parameterId: string
    zoneId: string
    parameterName: string | null
    zoneName: string | null
    unit: string | null
    sku: string
    openedAt: string
    hmi: string | null
    target: string | null
    open: boolean
    state: string
  }
  entries: WorkflowEntry[]
  questions?: string[]
}

export interface WorkflowList {
  requests: WorkflowRequest[]
  /** The follow-up questions in effect */
  questions: string[]
  counts: Record<Step, number>
  shift: { code: string; label: string; endsAt: string }
}

export interface WorkflowSettings {
  questions: string[]
  history: { questions: string[]; at: string; by: string | null; reason: string }[]
}
