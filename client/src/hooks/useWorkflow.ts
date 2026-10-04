import { useContext } from 'react'

import { WorkflowContext } from '@/context/WorkflowContext'

/** The reason workflow's requests, and how many wait for this person (ADR-0025). */
export function useWorkflow() {
  return useContext(WorkflowContext)
}
