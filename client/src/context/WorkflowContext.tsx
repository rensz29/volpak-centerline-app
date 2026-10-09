import { createContext, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { OPERATOR_STEPS } from '@/components/workflow/workflowModel'
import { useRoles } from '@/hooks/useAuth'
import { workflowApi } from '@/services/workflowApi'
import type { Step, WorkflowList } from '@/types/workflowApi'
import { chime } from '@/utils/chime'
import { clearDrafts } from '@/utils/drafts'

// An operator's pop-up comes within 3 s of the event (PER-01), so their browser asks every 2 s, like the live page
const OPERATOR_EVERY_MS = 2_000
const EVERY_MS = 5_000
/** The reason assistant is called (ADR-0040): `id` is the request to show, `seq` grows with each call */
export interface AssistantCall {
  id: string
  seq: number
}

interface WorkflowState {
  list: WorkflowList | null
  /** What this person has to do: for an operator, reasons, answers and acknowledgments; for a Manager, guidance */
  waiting: number
  refresh: () => void
  /** For an operator: the latest call to open the reason assistant */
  call: AssistantCall | null
}

/** The reason workflow's requests (ADR-0025), shared by the sidebar badge and the Reasons page; refreshed every 2 s for operators, 5 s for others. */
const WorkflowContext = createContext<WorkflowState>({ list: null, waiting: 0, refresh: () => undefined, call: null })

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const { isOperator, isManager } = useRoles()
  const [list, setList] = useState<WorkflowList | null>(null)
  const [call, setCall] = useState<AssistantCall | null>(null)
  const seen = useRef<Map<string, Step | null> | null>(null)

  const load = useCallback(() => {
    workflowApi
      .list()
      .then((next) => {
        const open = next.requests.filter((r) => r.next !== null)
        // The reason assistant opens itself for the operator (PER-01: within 3 s of the event, ADR-0040): for a new
        // mismatch, when a Manager's guidance arrives, and for whatever is waiting when the page opens
        if (isOperator) {
          const before = seen.current
          const mine = (step: Step | null) => step !== null && OPERATOR_STEPS.includes(step)
          const callers = open.filter((r) => mine(r.next) && (before === null || !before.has(r.id) ||
                                                               (before.get(r.id) === 'guidance' && r.next === 'acknowledgment')))
          if (callers.length) {
            setCall((c) => {
              // Stay on the request in hand while it still waits for the operator
              const keep = c !== null && open.some((r) => r.id === c.id && mine(r.next))
              return { id: keep && c ? c.id : callers[0]!.id, seq: (c?.seq ?? 0) + 1 }
            })
            chime()
          }
        }
        seen.current = new Map(open.map((r) => [r.id, r.next]))
        clearDrafts((key) => open.some((r) => key.startsWith(r.id))) // a closed request's unsent text goes with it
        setList(next)
      })
      .catch(() => undefined)
  }, [isOperator])

  useEffect(() => {
    load()
    const t = window.setInterval(load, isOperator ? OPERATOR_EVERY_MS : EVERY_MS)
    return () => window.clearInterval(t)
  }, [load, isOperator])

  const counts = list?.counts
  const waiting = !counts ? 0 : isOperator ? counts.reason + counts.answers + counts.ocap + counts.acknowledgment : isManager ? counts.guidance : 0
  return <WorkflowContext.Provider value={{ list, waiting, refresh: load, call }}>{children}</WorkflowContext.Provider>
}

export { WorkflowContext }
