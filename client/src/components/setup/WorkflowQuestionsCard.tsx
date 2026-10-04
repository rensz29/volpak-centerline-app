import { ClipboardList, Loader2, Save, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { SectionCard } from '@/components/shared/SectionCard'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiProblem } from '@/services/http'
import { workflowApi } from '@/services/workflowApi'
import type { WorkflowSettings } from '@/types/workflowApi'
import { formatManilaFull } from '@/utils/manilaTime'

import { FormField } from './FormParts'

/**
 * The follow-up questions an operator answers after giving a reason (ADR-0025): up to two, until
 * the AI asks its own (Phase 3), and as its fallback when it's down. An Administrator changes them.
 */
export function WorkflowQuestionsCard({ canEdit }: { canEdit: boolean }) {
  const [settings, setSettings] = useState<WorkflowSettings | null>(null)
  const [questions, setQuestions] = useState(['', ''])
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  useEffect(() => {
    workflowApi
      .settings()
      .then((s) => {
        setSettings(s)
        setQuestions([s.questions[0] ?? '', s.questions[1] ?? ''])
      })
      .catch((caught: unknown) => setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) })))
  }, [])

  const save = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const s = await workflowApi.saveSettings(questions, reason)
      setSettings(s)
      setReason('')
      toast.success('Follow-up questions saved', { description: s.questions.length ? s.questions.join(' · ') : 'None: the reason alone' })
    } catch (caught) {
      setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
    } finally {
      setBusy(false)
    }
  }

  if (!settings) {
    return problem ? <p className="text-critical text-[13px]">{problem.message}</p> : <Skeleton className="h-[260px] w-full rounded-lg" />
  }
  return (
    <SectionCard title="Follow-up questions" icon={ClipboardList}
                 description="What the operator answers after giving a reason, until the AI asks its own (Phase 3). Up to two; leave both empty for the reason alone.">
      <fieldset disabled={!canEdit} className="flex flex-col gap-3">
        {questions.map((q, i) => (
          <FormField key={i} label={`Question ${i + 1}`} error={problem?.forField(`questions[${i}]`)}>
            <Input value={q} onChange={(e) => setQuestions((qs) => qs.map((x, j) => (j === i ? e.target.value : x)))}
                   placeholder={i === 0 ? 'e.g. What was changed, and why?' : 'e.g. Is the product affected?'}
                   className="h-8 text-[13px]" aria-label={`Question ${i + 1}`} />
          </FormField>
        ))}
        {canEdit && (
          <>
            <FormField label="Reason for the change" error={problem?.forField('reason')} hint="Required. Kept in the change history.">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Agreed with the shift leads"
                     className="h-8 text-[13px]" aria-label="Reason for the change" />
            </FormField>
            {problem && problem.fieldErrors.length === 0 && (
              <p className="text-critical flex items-center gap-1.5 text-[13px]">
                <XCircle className="size-4" aria-hidden /> {problem.message}
              </p>
            )}
            <Button type="button" size="sm" className="self-end" disabled={busy} onClick={() => void save()}>
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />} Save
            </Button>
          </>
        )}
      </fieldset>
      <div className="border-line mt-4 border-t pt-3">
        <p className="micro-label mb-1.5">Changes</p>
        <ul className="flex flex-col gap-1 text-[12px]">
          {settings.history.map((h, i) => (
            <li key={i} className="text-ink-soft">
              {formatManilaFull(Date.parse(h.at))} Manila{h.by ? ` · ${h.by}` : ''} · “{h.reason}”:{' '}
              <span className="text-ink">{h.questions.length ? h.questions.join(' · ') : 'no questions'}</span>
            </li>
          ))}
        </ul>
      </div>
    </SectionCard>
  )
}
