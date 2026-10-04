import type { WorkflowList, WorkflowRequest, WorkflowSettings } from '@/types/workflowApi'

import { json, request } from './http'

/** The reason workflow (ADR-0025): the requests, each step, and the follow-up questions. */
export const workflowApi = {
  list(): Promise<WorkflowList> {
    return request<WorkflowList>('/api/v1/workflow/requests')
  },

  get(id: string): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}`)
  },

  reason(id: string, text: string): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/reason`, json('POST', { text }))
  },

  answers(id: string, answers: string[]): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/answers`, json('POST', { answers }))
  },

  guidance(id: string, text: string): Promise<WorkflowRequest> {
    return request<WorkflowRequest>(`/api/v1/workflow/requests/${id}/guidance`, json('POST', { text }))
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
