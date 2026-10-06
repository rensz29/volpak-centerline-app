import type { OcapSection } from './ocapApi'

/** The reason workflow (ADR-0025, ADR-0031): each HMI mismatch asks that shift's operator why, then offers the OCAP
 * sections that match, or a Manager's guidance. */

export type RequestStatus =
  | 'waiting_reason'
  | 'waiting_answers'
  | 'waiting_ocap'
  | 'waiting_guidance'
  | 'waiting_acknowledgment'
  | 'done'
  | 'not_answered'
  | 'resolved'
  | 'superseded'
  | 'cancelled'

export type Step = 'reason' | 'answers' | 'ocap' | 'guidance' | 'acknowledgment'

export interface ShiftView {
  code: 'A' | 'B' | 'C'
  label: string
  startsAt: string
  endsAt: string
}

export interface WorkflowAttachment {
  id: string
  name: string
  mediaType: string
  size: number
  scan: 'clean' | 'not_scanned'
}

export interface WorkflowEntry {
  kind: 'reason' | 'answer' | 'ocap_choice' | 'guidance' | 'acknowledgment'
  at: string
  by: string
  /** For an answer: the question as it was asked */
  question: string | null
  /** As typed, English or Filipino; for an OCAP choice, the section's citation or "None of these apply" */
  body: string
  /** For an OCAP choice: the section chosen, in full */
  section?: OcapSection | null
  /** For a guidance: its file */
  attachment?: WorkflowAttachment
}

/** An OCAP section offered after the reason (at most 3, best first), without its body. */
export interface OcapOffer extends Omit<OcapSection, 'body'> {
  rank: number
  score: number
  /** The section's opening words */
  excerpt: string
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
    openedAt: string
    hmi: string | null
    target: string | null
    open: boolean
    state: string
  }
  offered: OcapOffer[]
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
