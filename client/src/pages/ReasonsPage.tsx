import { ClipboardList } from 'lucide-react'
import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

import { EmptyState } from '@/components/shared/EmptyState'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { RequestCard } from '@/components/workflow/RequestCard'
import { waitsFor } from '@/components/workflow/workflowModel'
import { useRoles } from '@/hooks/useAuth'
import { useWorkflow } from '@/hooks/useWorkflow'
import type { WorkflowRequest } from '@/types/workflowApi'
import { formatManilaTime } from '@/utils/manilaTime'

/**
 * Reasons (WF-01…03, ADR-0025, ADR-0031): every HMI mismatch asks that shift's operator why, then offers the OCAP
 * sections that match. Operators see their shift's requests, answer them and choose an OCAP; Managers see every open
 * one and guide when no OCAP applies; everyone else reads. Requests still open 15 min after they were made have
 * alerted Management.
 */
export function ReasonsPage() {
  const { isOperator, isManager } = useRoles()
  const { list, refresh } = useWorkflow()
  const [params] = useSearchParams()
  const focus = params.get('request')

  useEffect(() => {
    if (focus && list) document.getElementById(`request-${focus}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focus, list])

  const roles = { isOperator, isManager }
  const requests = list?.requests ?? []
  const mine = requests.filter((r) => waitsFor(r, roles))
  const others = requests.filter((r) => r.next !== null && !waitsFor(r, roles))
  const closed = requests.filter((r) => r.next === null)
  const card = (r: WorkflowRequest) => (
    <RequestCard key={`${r.id}-${r.status}`} r={r} questions={list?.questions ?? []} isOperator={isOperator} isManager={isManager}
                 highlight={r.id === focus} onChanged={refresh} />
  )

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Reasons"
        description={
          isOperator
            ? `Every HMI mismatch this shift asks you why. Give your reason, answer the follow-up questions, choose the OCAP section that fits, and acknowledge it or the Manager's guidance. ${list ? `${list.shift.label.split(' (')[0]} ends at ${formatManilaTime(Date.parse(list.shift.endsAt)).slice(0, 5)}.` : ''}`
            : "Every HMI mismatch asks that shift's operator why, then offers the matching OCAP sections. Managers guide when none apply; a request still open after 15 min alerts Management."
        }
        breadcrumbs={[{ label: 'Alarms' }, { label: 'Reasons' }]}
      />
      {!list ? (
        <TableSkeleton rows={4} />
      ) : requests.length === 0 ? (
        <div className="bg-surface border-line shadow-card rounded-lg border">
          <EmptyState icon={ClipboardList} title={isOperator ? 'Nothing to explain this shift' : 'No reasons open or from the last day'}
                      description="A request appears here when an HMI setpoint stays off its target past the mismatch delay." />
        </div>
      ) : (
        <>
          {(isOperator || isManager) && (
            <SectionCard title="Waiting for you" icon={ClipboardList} description={mine.length ? `${mine.length} to do` : undefined}
                         bodyClassName="flex flex-col gap-3 p-4">
              {mine.length ? mine.map(card) : <p className="text-ink-muted text-[13px]">Nothing waits for you right now.</p>}
            </SectionCard>
          )}
          {others.length > 0 && (
            <SectionCard title={isOperator || isManager ? 'Waiting for someone else' : 'Open'} icon={ClipboardList}
                         description={`${others.length} open`} bodyClassName="flex flex-col gap-3 p-4">
              {others.map(card)}
            </SectionCard>
          )}
          {closed.length > 0 && (
            <SectionCard title={isOperator ? 'Closed this shift' : 'Closed in the last day'} icon={ClipboardList}
                         description={`${closed.length} closed`} bodyClassName="flex flex-col gap-3 p-4">
              {closed.map(card)}
            </SectionCard>
          )}
        </>
      )}
    </div>
  )
}
