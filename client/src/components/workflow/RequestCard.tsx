import { AlertTriangle, CheckCheck, Loader2, MessageSquareText, Send } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ApiProblem } from '@/services/http'
import { workflowApi } from '@/services/workflowApi'
import type { WorkflowRequest } from '@/types/workflowApi'
import { cn } from '@/utils/cn'
import { loadDraft, saveDraft } from '@/utils/drafts'
import { formatManilaFull } from '@/utils/manilaTime'

import { STATUS_LABEL, STATUS_TONE, withUnit } from './workflowModel'

const at = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`
const ENTRY_LABEL = { reason: 'Reason', answer: 'Answer', guidance: 'Guidance', acknowledgment: 'Acknowledged' } as const

/** A text box whose unsent text is also kept in this browser, until sent or until the session or request ends. */
function Draft({ id, texts, setText, label, placeholder, rows = 3 }: {
  id: string
  texts: Record<string, string>
  setText: (id: string, v: string) => void
  label: string
  placeholder: string
  rows?: number
}) {
  return (
    <Textarea rows={rows} value={texts[id] ?? ''} onChange={(e) => setText(id, e.target.value)} placeholder={placeholder}
              className="text-[13px]" aria-label={label} />
  )
}

/** One request: the mismatch, everything written on it, and the step it waits for (ADR-0025). */
export function RequestCard({
  r,
  questions,
  isOperator,
  isManager,
  highlight = false,
  onChanged,
}: {
  r: WorkflowRequest
  questions: string[]
  isOperator: boolean
  isManager: boolean
  highlight?: boolean
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const e = r.event
  const answerKeys = questions.map((_, i) => `${r.id}.answer.${i}`)
  const keys = [`${r.id}.reason`, `${r.id}.guidance`, ...answerKeys]
  const [texts, setTexts] = useState<Record<string, string>>(() => Object.fromEntries(keys.map((k) => [k, loadDraft(k)])))
  const setText = (id: string, v: string) => {
    setTexts((t) => ({ ...t, [id]: v }))
    saveDraft(id, v)
  }
  const text = (id: string) => (texts[id] ?? '').trim()

  const run = async (action: () => Promise<WorkflowRequest>, done: string, clear: string[]) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      clear.forEach((k) => setText(k, ''))
      toast.success(done)
      onChanged()
    } catch (caught) {
      setError(caught instanceof ApiProblem ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article
      id={`request-${r.id}`}
      className={cn('bg-surface border-line shadow-card flex flex-col gap-3 rounded-lg border p-4 text-[13px]',
                    highlight && 'ring-brand ring-2')}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-ink font-medium">
            HMI mismatch · {e.zoneName ?? e.zoneId} <span className="text-ink-muted font-normal">{e.parameterName}</span>
          </p>
          <p className="text-ink-soft mt-0.5">
            HMI setpoint <b className="text-warning">{withUnit(e.hmi, e.unit)}</b> against the target {withUnit(e.target, e.unit)} · since{' '}
            {at(e.openedAt)}
          </p>
          <p className="text-ink-muted mt-0.5 text-[12px]">{r.shift.label}</p>
        </div>
        <span className="flex flex-col items-end gap-1">
          <Badge variant={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</Badge>
          {r.escalatedAt && (
            <span className="text-critical flex items-center gap-1 text-[11px]">
              <AlertTriangle className="size-3" aria-hidden /> Management alerted {at(r.escalatedAt)}
            </span>
          )}
        </span>
      </header>

      {r.entries.length > 0 && (
        <ol className="border-line-soft flex flex-col gap-2 border-l-2 pl-3">
          {r.entries.map((x, i) => (
            <li key={i}>
              <p className="text-ink-muted text-[11px]">
                {ENTRY_LABEL[x.kind]} · {x.by} · {at(x.at)}
              </p>
              {x.question && <p className="text-ink-soft text-[12px]">{x.question}</p>}
              {x.body && <p className="text-ink whitespace-pre-wrap">{x.body}</p>}
            </li>
          ))}
        </ol>
      )}

      {isOperator && r.next === 'reason' && (
        <div className="flex flex-col gap-2">
          <Draft id={`${r.id}.reason`} texts={texts} setText={setText} label="Your reason"
                 placeholder="Why is the setpoint off target? English or Filipino." />
          <Button type="button" size="sm" className="self-end" disabled={busy}
                  onClick={() => void run(() => workflowApi.reason(r.id, text(`${r.id}.reason`)), 'Reason sent', [`${r.id}.reason`])}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Send the reason
          </Button>
        </div>
      )}
      {isOperator && r.next === 'answers' && (
        <div className="flex flex-col gap-2">
          {questions.map((q, i) => (
            <label key={q} className="flex flex-col gap-1">
              <span className="text-ink font-medium">{q}</span>
              <Draft id={answerKeys[i]!} texts={texts} setText={setText} label={q} placeholder="Your answer" rows={2} />
            </label>
          ))}
          <Button type="button" size="sm" className="self-end" disabled={busy}
                  onClick={() => void run(() => workflowApi.answers(r.id, answerKeys.map(text)), 'Answers sent', answerKeys)}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Send the answers
          </Button>
        </div>
      )}
      {isManager && r.next === 'guidance' && (
        <div className="flex flex-col gap-2">
          <Draft id={`${r.id}.guidance`} texts={texts} setText={setText} label="Your guidance"
                 placeholder="What the operator should do (GDE-01)" />
          <Button type="button" size="sm" className="self-end" disabled={busy}
                  onClick={() => void run(() => workflowApi.guidance(r.id, text(`${r.id}.guidance`)), 'Guidance sent', [`${r.id}.guidance`])}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <MessageSquareText className="size-4" aria-hidden />} Send the guidance
          </Button>
        </div>
      )}
      {isOperator && r.next === 'acknowledgment' && (
        <Button type="button" size="sm" className="self-end" disabled={busy}
                onClick={() => void run(() => workflowApi.acknowledge(r.id), 'Acknowledged', [])}>
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <CheckCheck className="size-4" aria-hidden />} I've read the guidance
        </Button>
      )}
      {error && <p className="text-critical text-[12px]">{error}</p>}
    </article>
  )
}
