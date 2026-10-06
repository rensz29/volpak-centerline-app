import { createContext, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { useRoles } from '@/hooks/useAuth'
import { workflowApi } from '@/services/workflowApi'
import type { WorkflowList } from '@/types/workflowApi'
import { clearDrafts } from '@/utils/drafts'

// An operator's pop-up comes within 3 s of the event (PER-01), so their browser asks every 2 s, like the live page
const OPERATOR_EVERY_MS = 2_000
const EVERY_MS = 5_000

interface WorkflowState {
  list: WorkflowList | null
  /** What this person has to do: for an operator, reasons, answers and acknowledgments; for a Manager, guidance */
  waiting: number
  refresh: () => void
}

/** The reason workflow's requests (ADR-0025), shared by the sidebar badge and the Reasons page; refreshed every 2 s for operators, 5 s for others. */
const WorkflowContext = createContext<WorkflowState>({ list: null, waiting: 0, refresh: () => undefined })

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const { isOperator, isManager } = useRoles()
  const [list, setList] = useState<WorkflowList | null>(null)
  const seen = useRef<Set<string> | null>(null)

  const load = useCallback(() => {
    workflowApi
      .list()
      .then((next) => {
        const open = next.requests.filter((r) => r.next !== null)
        // A new request is a pop-up for the operator who has to answer it (PER-01: within 3 s of the event)
        if (isOperator && seen.current) {
          for (const r of open) {
            if (r.next === 'reason' && !seen.current.has(r.id)) {
              toast.warning(`HMI mismatch on ${r.event.zoneName ?? r.event.channel}: give your reason`, {
                description: `HMI setpoint ${r.event.hmi ?? '—'} against the target ${r.event.target ?? '—'}. Open Reasons.`,
                duration: 15_000,
              })
            }
          }
        }
        seen.current = new Set(open.map((r) => r.id))
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
  return <WorkflowContext.Provider value={{ list, waiting, refresh: load }}>{children}</WorkflowContext.Provider>
}

export { WorkflowContext }
