import { AlertTriangle, BookOpen, CheckCheck, Loader2, Paperclip, Send } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { SectionText } from '@/components/ocap/SectionText'
import { placeLabel, sizeLabel } from '@/components/ocap/ocapModel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ApiProblem } from '@/services/http'
import { workflowApi, type GuidanceBody } from '@/services/workflowApi'
import type { WorkflowRequest } from '@/types/workflowApi'
import { cn } from '@/utils/cn'
import { loadDraft, saveDraft } from '@/utils/drafts'
import { formatManilaFull } from '@/utils/manilaTime'

import { GuidanceForm } from './GuidanceForm'
import { OcapOffers } from './OcapOffers'
import { ENTRY_LABEL, STATUS_LABEL, STATUS_TONE, withUnit } from './workflowModel'

const at = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`

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

/** One request: the mismatch, everything written on it, and the step it waits for (ADR-0025, ADR-0031). */
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
  const [reading, setReading] = useState<number | null>(null)
  /** The reason picked from the OCAP rows offered, or "other" to type one (ADR-0039) */
  const [picked, setPicked] = useState<string | null>(null)
  const e = r.event
  const raised = e.hmi !== null && e.target !== null ? Number(e.hmi) > Number(e.target) : null
  /** What the operator acknowledges: the OCAP section chosen, or the Manager's guidance */
  const last = r.entries.findLast((x) => x.kind === 'ocap_choice' || x.kind === 'guidance')
  const ackOcap = last?.kind === 'ocap_choice' && !!last.section
  // The questions this request asked: the AI's or the fixed ones (ADR-0041); the fixed ones in effect before the reason
  const asked = r.asked?.map((q) => q.question) ?? questions
  const answerKeys = asked.map((_, i) => `${r.id}.answer.${i}`)
  const keys = [`${r.id}.reason`, `${r.id}.note`, `${r.id}.guidance`, ...answerKeys]
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
              {x.kind === 'reason' && x.section && <p className="text-ink-muted text-[12px]">Picked from {x.section.citation}</p>}
              {x.body && <p className="text-ink whitespace-pre-wrap">{x.body}</p>}
              {x.section && (
                <>
                  <button type="button" className="text-brand inline-flex items-center gap-1 text-[12px] hover:underline"
                          onClick={() => setReading(reading === i ? null : i)}>
                    <BookOpen className="size-3.5" aria-hidden /> {reading === i ? 'Hide the section' : 'Read the section'}
                  </button>
                  {reading === i && <SectionText sectionId={x.section.sectionId} section={x.section} />}
                </>
              )}
              {x.attachment && (
                <a href={workflowApi.attachmentUrl(x.attachment.id)}
                   className="text-brand inline-flex items-center gap-1 text-[12px] hover:underline">
                  <Paperclip className="size-3.5" aria-hidden /> {x.attachment.name} · {sizeLabel(x.attachment.size)}
                  {x.attachment.scan === 'not_scanned' && <span className="text-ink-muted"> · not scanned</span>}
                </a>
              )}
            </li>
          ))}
        </ol>
      )}

      {isOperator && r.next === 'reason' && r.opening?.by === 'ai' && (
        <p className="text-ink -mb-1">
          {r.opening.question} <span className="text-ink-muted text-[11px]">· asked by the AI, from the OCAP</span>
        </p>
      )}
      {isOperator && r.next === 'reason' && r.choices.length > 0 && (
        <fieldset className="flex min-w-0 flex-col gap-2">
          <legend className="text-ink mb-1 font-medium">{r.opening?.by === 'ai' ? 'Pick the reason' : 'Why did you change it? Pick the reason'}</legend>
          <p className="text-ink-muted -mt-1 text-[12px]">
            From the OCAPs for {e.parameterName ?? e.parameterId}
            {raised === null ? '' : raised ? ', setpoint raised' : ', setpoint lowered'}. If none fits, choose Other and type it.
          </p>
          {[...r.choices.map((c) => ({ id: c.sectionId, label: c.label, sub: [c.code, placeLabel(c)].filter(Boolean).join(' · '), title: c.citation })),
            { id: 'other', label: 'Other: I’ll type the reason', sub: 'English or Filipino', title: undefined }].map((o) => (
            <label key={o.id} title={o.title}
                   className={cn('border-line hover:bg-surface-muted flex min-h-11 cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2',
                                 picked === o.id && 'border-brand bg-brand-surface hover:bg-brand-surface')}>
              <input type="radio" name={`reason-${r.id}`} className="mt-1" checked={picked === o.id} onChange={() => setPicked(o.id)} />
              <span className="min-w-0">
                <span className="text-ink block">{o.label}</span>
                <span className="text-ink-muted block text-[11px]">{o.sub}</span>
              </span>
            </label>
          ))}
          {picked === 'other' && (
            <Draft id={`${r.id}.reason`} texts={texts} setText={setText} label="Your reason"
                   placeholder="Why is the setpoint off target? English or Filipino." />
          )}
          {picked !== null && picked !== 'other' && (
            <Draft id={`${r.id}.note`} texts={texts} setText={setText} label="A note" rows={2}
                   placeholder="Anything to add? (optional)" />
          )}
          <Button type="button" size="sm" className="self-end" disabled={busy || picked === null || (picked === 'other' && !text(`${r.id}.reason`))}
                  onClick={() => void run(() => workflowApi.reason(r.id, picked === 'other'
                    ? { text: text(`${r.id}.reason`) }
                    : { sectionId: picked!, note: text(`${r.id}.note`) }), 'Reason sent', [`${r.id}.reason`, `${r.id}.note`])}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Send the reason
          </Button>
        </fieldset>
      )}
      {isOperator && r.next === 'reason' && r.choices.length === 0 && (
        <div className="flex flex-col gap-2">
          <Draft id={`${r.id}.reason`} texts={texts} setText={setText} label="Your reason"
                 placeholder="Why is the setpoint off target? English or Filipino." />
          <Button type="button" size="sm" className="self-end" disabled={busy}
                  onClick={() => void run(() => workflowApi.reason(r.id, { text: text(`${r.id}.reason`) }), 'Reason sent', [`${r.id}.reason`])}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Send the reason
          </Button>
        </div>
      )}
      {isOperator && r.next === 'answers' && (
        <div className="flex flex-col gap-2">
          {asked.map((q, i) => (
            <label key={q} className="flex flex-col gap-1">
              <span className="text-ink font-medium">
                {q}
                {r.asked?.[i]?.by === 'ai' && <span className="text-ink-muted ml-1.5 text-[11px] font-normal">· asked by the AI, from the OCAP</span>}
              </span>
              <Draft id={answerKeys[i]!} texts={texts} setText={setText} label={q} placeholder="Your answer" rows={2} />
            </label>
          ))}
          <Button type="button" size="sm" className="self-end" disabled={busy}
                  onClick={() => void run(() => workflowApi.answers(r.id, answerKeys.map(text)), 'Answers sent', answerKeys)}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Send the answers
          </Button>
        </div>
      )}
      {isOperator && r.next === 'ocap' && (
        <OcapOffers offers={r.offered} busy={busy}
                    onChoose={(id) => void run(() => workflowApi.ocap(r.id, id), id ? 'OCAP section chosen' : 'Sent to a Manager', [])} />
      )}
      {r.next !== 'ocap' && r.offered.length > 0 && (isManager || r.next === null) && (
        <p className="text-ink-muted text-[12px]">OCAP offered: {r.offered.map((o) => o.citation).join('; ')}</p>
      )}
      {r.summary && (isManager || r.next === null) && (
        <p className="text-ink-muted text-[12px]">
          AI summary ({r.summary.sections.map((s) => s.citation).join('; ')}): <span className="text-ink-soft">{r.summary.text}</span>
        </p>
      )}
      {isManager && r.next === 'guidance' && (
        <GuidanceForm
          busy={busy}
          text={<Draft id={`${r.id}.guidance`} texts={texts} setText={setText} label="Your guidance"
                       placeholder="What the operator should do (GDE-01)" />}
          onSend={(body: (t: string) => Promise<GuidanceBody>) =>
            void run(async () => workflowApi.guidance(r.id, await body(text(`${r.id}.guidance`))), 'Guidance sent', [`${r.id}.guidance`])}
        />
      )}
      {isOperator && r.next === 'acknowledgment' && (
        <Button type="button" size="sm" className="self-end" disabled={busy}
                onClick={() => void run(() => workflowApi.acknowledge(r.id), 'Acknowledged', [])}>
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <CheckCheck className="size-4" aria-hidden />}{' '}
          {ackOcap ? "I've read the OCAP section" : "I've read the guidance"}
        </Button>
      )}
      {isOperator && r.next === 'acknowledgment' && (
        <p className="text-ink-muted -mt-2 self-end text-[11px]">This records that you reviewed it, not that each step was done.</p>
      )}
      {error && <p className="text-critical text-[12px]">{error}</p>}
    </article>
  )
}
