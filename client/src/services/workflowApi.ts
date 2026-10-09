import type { OcapLanguage } from '@/types/ocapApi'
import type { WorkflowList, WorkflowRequest, WorkflowSettings } from '@/types/workflowApi'

import { json, request } from './http'

/** A Manager's guidance (GDE-01): the text, one PDF or Word file, and whether to keep it as a reusable OCAP. */
export interface GuidanceBody {
  text: string
  attachment?: { name: string; contentBase64: string }
  reusable?: { code: string; title: string; language: OcapLanguage }
}

/** The reason workflow (ADR-0025): the requests, each step, and the follow-up questions. */
export const workflowApi = {
  list(): Promise<WorkflowList> {
    return request<WorkflowList>('/api/v1/workflow/requests')
  },

  get(id: string): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}`)
  },

  /** Typed, or picked from the request's choices with an optional note (ADR-0039) */
  reason(id: string, body: { text: string } | { sectionId: string; note: string }): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/reason`, json('POST', body))
  },

  answers(id: string, answers: string[]): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/answers`, json('POST', { answers }))
  },

  /** One of the sections offered, or null: none of these apply, so a Manager guides. */
  ocap(id: string, sectionId: string | null): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/ocap`, json('POST', { sectionId }))
  },

  guidance(id: string, body: GuidanceBody): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/guidance`, json('POST', body))
  },

  attachmentUrl(attachmentId: string): string {
    return `/api/v1/workflow/attachments/${attachmentId}`
  },

  acknowledge(id: string): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/acknowledge`, json('POST', {}))
  },

  settings(): Promise<WorkflowSettings> {
    return request<WorkflowSettings>('/api/v1/config/workflow')
  },

  saveSettings(questions: string[], reason: string): Promise<WorkflowSettings> {
    return request<WorkflowSettings>('/api/v1/config/workflow', json('PUT', { questions, reason }))
  },
}
