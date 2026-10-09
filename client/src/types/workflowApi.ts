import type { OcapSection, ReasonDirection, SectionPlace } from './ocapApi'

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
  /** As typed, English or Filipino; a picked reason's phenomenon, then any note; for an OCAP choice, the section's
   * citation or "None of these apply" */
  body: string
  /** For a reason picked from an OCAP, or an OCAP choice: the section, in full */
  section?: OcapSection | null
  /** For a guidance: its file */
  attachment?: WorkflowAttachment
}

/** An Excel OCAP row the operator can pick as the reason (ADR-0039) */
export interface ReasonChoice extends SectionPlace {
  sectionId: string
  /** The row's phenomenon, as written in the OCAP */
  label: string
  /** The same in Tagalog: the active checked version's, else the AI's (ADR-0044, ADR-0045) */
  labelFil: string | null
  code: string
  title: string
  version: number
  direction: ReasonDirection
  citation: string
}

/** An OCAP section offered after the reason (at most 3, best first), without its body. */
export interface OcapOffer extends Omit<OcapSection, 'body'> {
  rank: number
  score: number
  /** keyword: found by the search; reason: the row the operator picked as the reason (ADR-0039) */
  method: 'keyword' | 'reason'
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
  /** While it waits for the reason: the OCAP rows to pick it from, those for this direction first */
  choices: ReasonChoice[]
  /** The follow-up questions it asked, in order: the local AI's from the OCAP (ADR-0041) or the fixed ones; null before
   * the reason (and for requests from before ADR-0041, which asked the fixed ones in effect) */
  asked: { question: string; questionFil: string | null; by: 'ai' | 'fixed' }[] | null
  /** The first question, asked as soon as it opened: the local AI's from the OCAP rows for the mismatch, or the fixed
   * "Why did you change it?" when the AI couldn't (ADR-0042); null until written */
  opening: { question: string; questionFil: string | null; by: 'ai' | 'fixed' } | null
  /** In the list: the AI's opening question is still being written, so the chat waits a few seconds for it */
  openingPending?: boolean
  /** The local AI's summary of the OCAP sections offered, citing some of them (OCP-02, ADR-0046); null without one */
  summary: OcapSummary | null
  /** A summary was tried, whether or not it passed its checks */
  summaryTried: boolean
  /** In the list: the AI's summary is still being written */
  summaryPending?: boolean
  updatedAt: string
  entries: WorkflowEntry[]
  questions?: string[]
}

/** What the OCAP sections offered say for this mismatch, as the local AI summed it up: shown above them, never instead */
export interface OcapSummary {
  text: string
  /** Its Filipino, when that passed its checks */
  textFil: string | null
  at: string
  by: 'ai'
  /** The sections it cites, of those offered */
  sections: { sectionId: string; citation: string | null }[]
}

export interface WorkflowList {
  requests: WorkflowRequest[]
  /** The follow-up questions in effect */
  questions: string[]
  counts: Record<Step, number>
  /** The local AI writes each new request's opening question here (ADR-0042): worth waiting a few seconds for */
  aiOpening: boolean
  shift: { code: string; label: string; endsAt: string }
}

export interface WorkflowSettings {
  questions: string[]
  history: { questions: string[]; at: string; by: string | null; reason: string }[]
}
