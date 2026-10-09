import { BookOpen, Bot, Check, ChevronLeft, ChevronRight, Loader2, Minus, Paperclip, Send, Sparkles, X } from 'lucide-react'
import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'

import { Excerpt, SectionText } from '@/components/ocap/SectionText'
import { placeLabel, sizeLabel } from '@/components/ocap/ocapModel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useWorkflow } from '@/hooks/useWorkflow'
import { ApiProblem } from '@/services/http'
import { workflowApi } from '@/services/workflowApi'
import type { WorkflowRequest } from '@/types/workflowApi'
import { cn } from '@/utils/cn'
import { formatManilaFull } from '@/utils/manilaTime'

import { LANG_LABEL, TEXT, spoken, type AssistantText, type Lang } from './assistantText'
import { OPERATOR_STEPS, withUnit } from './workflowModel'

type Run = (action: () => Promise<unknown>) => Promise<void>

/** The chat's language (ADR-0043): Tagalog unless this browser chose English */
const LANG_KEY = 'centerline.assistant.lang'
const Words = createContext<{ t: AssistantText; lang: Lang }>({
  t: TEXT.fil,
  lang: 'fil',
})

function savedLang(): Lang {
  try {
    return window.localStorage.getItem(LANG_KEY) === 'en' ? 'en' : 'fil'
  } catch {
    return 'fil'
  }
}

function Say({ from, children }: { from: 'bot' | 'me'; children: ReactNode }) {
  return from === 'bot' ? (
    <div className="flex items-start gap-2">
      <span className="bg-brand-surface text-brand mt-0.5 grid size-6 shrink-0 place-items-center rounded-full">
        <Bot className="size-3.5" aria-hidden />
      </span>
      <div className="bg-surface-muted text-ink min-w-0 rounded-lg rounded-tl-sm px-3 py-2">{children}</div>
    </div>
  ) : (
    <div className="flex justify-end">
      <div className="bg-brand max-w-[85%] min-w-0 rounded-lg rounded-tr-sm px-3 py-2 text-white">{children}</div>
    </div>
  )
}

/** A question the local AI wrote from the OCAP (ADR-0041), in the chat's language, marked as such */
function Asked({ question, ai }: { question: string; ai: boolean }) {
  const { t } = useContext(Words)
  return (
    <Say from="bot">
      <p>{question}</p>
      {ai && (
        <p className="text-ink-muted mt-0.5 flex items-center gap-1 text-[11px]">
          <Sparkles className="size-3" aria-hidden /> {t.askedByAi}
        </p>
      )}
    </Say>
  )
}

/** Below the assistant's message: what the operator can answer with */
function Replies({ children }: { children: ReactNode }) {
  return <div className="flex min-w-0 flex-col gap-1.5 pl-8">{children}</div>
}

/** The first question: the AI's from the OCAP rows for the mismatch (ADR-0042), a note that it's looking, or the fixed one */
function Opening({ r }: { r: WorkflowRequest }) {
  const { t, lang } = useContext(Words)
  if (r.opening) return <Asked question={spoken(r.opening, lang)} ai={r.opening.by === 'ai'} />
  if (r.openingPending) {
    return (
      <Say from="bot">
        <span className="text-ink-muted flex items-center gap-2">
          <Loader2 className="size-3.5 animate-spin" aria-hidden /> {t.lookingAtOcap(r.event.zoneName ?? r.event.zoneId)}
        </span>
      </Say>
    )
  }
  return <Say from="bot">{t.whyChanged}</Say>
}

/** What was said so far, from the request's own record */
function Transcript({ r }: { r: WorkflowRequest }) {
  const { t, lang } = useContext(Words)
  const e = r.event
  const raised = e.hmi !== null && e.target !== null ? Number(e.hmi) > Number(e.target) : null
  // An answer keeps the English question (the record's language); the chat shows it as it was asked
  const asked = (question: string | null) => r.asked?.find((q) => q.question === question)
  return (
    <>
      <Say from="bot">
        <p className="font-medium">{t.mismatchOn(e.zoneName ?? e.zoneId)}</p>
        <p>
          {t.setpointIs(e.parameterName ?? e.parameterId)}
          <b className="text-warning">{withUnit(e.hmi, e.unit)}</b>
          {t.againstTarget(
            withUnit(e.target, e.unit),
            raised === null ? null : raised ? 'raised' : 'lowered',
            formatManilaFull(Date.parse(e.openedAt)),
          )}
        </p>
      </Say>
      <Opening r={r} />
      {r.entries.map((x, i) =>
        x.kind === 'reason' ? (
          <Say key={i} from="me">
            {/* A picked reason is the OCAP row's words, then any note: in Tagalog, its Tagalog words (ADR-0044, ADR-0045) */}
            <p className="whitespace-pre-wrap">
              {lang === 'fil' && x.section?.fil?.phenomenon
                ? [x.section.fil.phenomenon, ...x.body.split('\n').slice(1)].join('\n')
                : x.body}
            </p>
            {x.section && (
              <p className="text-[11px] opacity-80">{t.fromOcap([x.section.code, placeLabel(x.section)].filter(Boolean).join(' · '))}</p>
            )}
          </Say>
        ) : x.kind === 'answer' ? (
          <div key={i} className="flex flex-col gap-2.5">
            <Asked
              question={(() => {
                const q = asked(x.question)
                return spoken(q ?? { question: x.question ?? '', questionFil: null, by: 'fixed' }, lang)
              })()}
              ai={asked(x.question)?.by === 'ai'}
            />
            <Say from="me">
              <p className="whitespace-pre-wrap">{x.body}</p>
            </Say>
          </div>
        ) : x.kind === 'ocap_choice' ? (
          <Say key={i} from="me">
            {x.section ? t.thisApplies(x.section.citation) : t.noneApply}
          </Say>
        ) : x.kind === 'guidance' ? (
          <Say key={i} from="bot">
            <p className="text-ink-muted text-[11px]">{t.guidanceFrom(x.by)}</p>
            <p className="whitespace-pre-wrap">{x.body}</p>
            {x.attachment && (
              <a
                href={workflowApi.attachmentUrl(x.attachment.id)}
                className="text-brand inline-flex items-center gap-1 text-[12px] hover:underline"
              >
                <Paperclip className="size-3.5" aria-hidden /> {x.attachment.name} · {sizeLabel(x.attachment.size)}
              </a>
            )}
          </Say>
        ) : (
          <Say key={i} from="me">
            {t.readIt}
          </Say>
        ),
      )}
    </>
  )
}

function Composer({
  placeholder,
  disabled,
  required,
  busy,
  onSend,
}: {
  placeholder: string
  disabled?: boolean
  required: boolean
  busy: boolean
  onSend: (text: string) => void
}) {
  const [text, setText] = useState('')
  const sendLabel = useContext(Words).t.send
  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    if (busy || disabled || (required && !text.trim())) return
    onSend(text.trim())
    setText('')
  }
  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <Input
        value={text}
        onChange={(ev) => setText(ev.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={placeholder}
        className="h-9 text-[13px]"
      />
      <Button type="submit" size="sm" className="h-9" disabled={busy || disabled || (required && !text.trim())} aria-label={sendLabel}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
      </Button>
    </form>
  )
}

function ReasonStep({ r, busy, run }: { r: WorkflowRequest; busy: boolean; run: Run }) {
  const { t, lang } = useContext(Words)
  const [picked, setPicked] = useState<string | null>(r.choices.length ? null : 'other')
  const other = picked === 'other'
  return (
    <Replies>
      {r.choices.length > 0 && (
        <div className="flex max-h-[220px] flex-col gap-1.5 overflow-y-auto pr-1">
          {[
            // In Tagalog, the row's Tagalog words, with its English words below (ADR-0044, ADR-0045)
            ...r.choices.map((c) => ({
              id: c.sectionId,
              label: lang === 'fil' && c.labelFil ? c.labelFil : c.label,
              sub: [lang === 'fil' && c.labelFil ? c.label : null, c.code, placeLabel(c)].filter(Boolean).join(' · '),
            })),
            { id: 'other', label: t.otherTypeIt, sub: t.englishOrFilipino },
          ].map((o) => (
            <button
              key={o.id}
              type="button"
              onClick={() => setPicked(o.id)}
              className={cn(
                'border-line hover:bg-surface-muted rounded-lg border px-3 py-1.5 text-left',
                picked === o.id && 'border-brand bg-brand-surface hover:bg-brand-surface',
              )}
            >
              <span className="text-ink block">{o.label}</span>
              <span className="text-ink-muted block text-[11px]">{o.sub}</span>
            </button>
          ))}
        </div>
      )}
      <Composer
        busy={busy}
        disabled={picked === null}
        required={other}
        placeholder={picked === null ? t.pickAbove : other ? t.typeReason : t.addNote}
        onSend={(text) => void run(() => workflowApi.reason(r.id, other ? { text } : { sectionId: picked!, note: text }))}
      />
    </Replies>
  )
}

function AnswersStep({ r, fixed, busy, run }: { r: WorkflowRequest; fixed: string[]; busy: boolean; run: Run }) {
  const { t, lang } = useContext(Words)
  const [answers, setAnswers] = useState<string[]>([])
  const asked =
    r.asked ??
    fixed.map((question) => ({
      question,
      questionFil: null,
      by: 'fixed' as const,
    }))
  const questions = asked.map((q) => q.question)
  const shown = asked.map((q) => spoken(q, lang))
  const k = answers.length
  return (
    <>
      {answers.map((a, i) => (
        <div key={i} className="flex flex-col gap-2.5">
          <Asked question={shown[i] ?? ''} ai={asked[i]?.by === 'ai'} />
          <Say from="me">{a}</Say>
        </div>
      ))}
      <Asked question={shown[k] ?? ''} ai={asked[k]?.by === 'ai'} />
      <Replies>
        <Composer
          busy={busy}
          required
          placeholder={t.yourAnswer}
          onSend={(text) => {
            const next = [...answers, text]
            if (next.length < questions.length) setAnswers(next)
            else void run(() => workflowApi.answers(r.id, next))
          }}
        />
      </Replies>
    </>
  )
}

/**
 * The local AI's summary of the sections offered (OCP-02, ADR-0046): above them, in the chat's language, with the
 * sections it cites by their number; a note while it's being written. The sections are read either way.
 */
function Summary({ r }: { r: WorkflowRequest }) {
  const { t, lang } = useContext(Words)
  if (r.summaryPending && !r.summary) {
    return (
      <Say from="bot">
        <span className="text-ink-muted flex items-center gap-2">
          <Loader2 className="size-3.5 animate-spin" aria-hidden /> {t.summarising}
        </span>
      </Say>
    )
  }
  if (!r.summary) return null
  const number = (id: string) => r.offered.findIndex((o) => o.sectionId === id) + 1
  return (
    <Say from="bot">
      <p className="text-ink-muted mb-1 flex items-center gap-1 text-[11px] font-medium">
        <Sparkles className="size-3" aria-hidden /> {t.aiSummary}
      </p>
      <p className="whitespace-pre-wrap">{lang === 'fil' && r.summary.textFil ? r.summary.textFil : r.summary.text}</p>
      <p className="text-ink-muted mt-1 text-[11px]">
        {r.summary.sections.map((s) => `[${number(s.sectionId)}] ${s.citation ?? ''}`).join(' · ')}
      </p>
      <p className="text-ink-muted mt-0.5 text-[11px]">{t.summaryNote}</p>
    </Say>
  )
}

function OcapStep({ r, busy, run }: { r: WorkflowRequest; busy: boolean; run: Run }) {
  const { t, lang } = useContext(Words)
  const picked = r.offered[0]?.method === 'reason'
  const [reading, setReading] = useState<string | null>(r.offered.length === 1 ? r.offered[0]!.sectionId : null)
  return (
    <>
      <Say from="bot">{picked ? t.ocapPicked : t.ocapMatches(r.offered.length)}</Say>
      <Summary r={r} />
      <Replies>
        {r.offered.map((o, i) => (
          <div key={o.sectionId} className="border-line rounded-lg border p-2.5">
            <p className="text-ink font-medium">
              {r.summary && r.offered.length > 1 ? `[${i + 1}] ` : ''}
              {o.citation}
            </p>
            {reading === o.sectionId ? (
              <SectionText sectionId={o.sectionId} tagalog={lang === 'fil'} />
            ) : (
              <p className="text-ink-soft mt-1 line-clamp-3 whitespace-pre-wrap">
                <Excerpt text={o.excerpt} />
              </p>
            )}
            <div className="mt-2 flex flex-wrap justify-end gap-2">
              {reading !== o.sectionId && (
                <Button type="button" variant="ghost" size="sm" onClick={() => setReading(o.sectionId)}>
                  <BookOpen className="size-4" aria-hidden /> {t.readInFull}
                </Button>
              )}
              <Button
                type="button"
                size="sm"
                disabled={busy || reading !== o.sectionId}
                title={reading === o.sectionId ? undefined : t.readFirst}
                onClick={() => void run(() => workflowApi.ocap(r.id, o.sectionId))}
              >
                <Check className="size-4" aria-hidden /> {t.thisOneApplies}
              </Button>
            </div>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          disabled={busy}
          onClick={() => void run(() => workflowApi.ocap(r.id, null))}
        >
          {t.askManager(r.offered.length === 1)}
        </Button>
      </Replies>
    </>
  )
}

function AcknowledgeStep({ r, busy, run }: { r: WorkflowRequest; busy: boolean; run: Run }) {
  const { t, lang } = useContext(Words)
  const last = r.entries.findLast((x) => x.kind === 'ocap_choice' || x.kind === 'guidance')
  const section = last?.kind === 'ocap_choice' ? last.section : null
  return (
    <>
      <Say from="bot">{section ? t.ackSection : t.ackGuidance}</Say>
      <Replies>
        {section && <SectionText sectionId={section.sectionId} section={section} tagalog={lang === 'fil'} />}
        <Button
          type="button"
          size="sm"
          className="self-start"
          disabled={busy}
          onClick={() => void run(() => workflowApi.acknowledge(r.id))}
        >
          <Check className="size-4" aria-hidden /> {t.readIt}
        </Button>
        <p className="text-ink-muted text-[11px]">{t.reviewOnly}</p>
      </Replies>
    </>
  )
}

/**
 * The reason assistant (ADR-0040): a chat that opens by itself on every page when an HMI mismatch needs the operator,
 * with a short sound, and asks one thing at a time: the reason (picked from the OCAP rows offered, or typed), the
 * follow-up questions, the OCAP row or sections, and the acknowledgment; or tells them a Manager will guide them and
 * comes back when the guidance arrives. Same steps and records as the Reasons page. The local AI asks its questions from
 * the OCAP (ADR-0041, ADR-0042). In Tagalog by default, or English, switched in its header (ADR-0043).
 */
export function ReasonAssistant() {
  const { list, refresh, call } = useWorkflow()
  const [closedSeq, setClosedSeq] = useState(0)
  const [opened, setOpened] = useState(false)
  /** A request the operator switched to, and the call it was in: a newer call moves on once it's finished */
  const [chosen, setChosen] = useState<{ id: string; seq: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const [lang, setLangState] = useState<Lang>(savedLang)
  const t = TEXT[lang]
  const setLang = (next: Lang) => {
    setLangState(next)
    try {
      window.localStorage.setItem(LANG_KEY, next)
    } catch {
      /* kept for this page only */
    }
  }

  const requests = list?.requests ?? []
  const waiting = requests.filter((r) => r.next !== null).sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  const actionable = waiting.filter((r) => r.next !== null && OPERATOR_STEPS.includes(r.next))
  const open = opened || (call !== null && call.seq > closedSeq)
  const exists = (id: string | undefined) => id !== undefined && requests.some((x) => x.id === id)
  const stillOpen = (id: string) => requests.some((x) => x.id === id && x.next !== null)
  const keepChosen = chosen !== null && exists(chosen.id) && (stillOpen(chosen.id) || (call?.seq ?? 0) <= chosen.seq)
  const activeId =
    (keepChosen ? chosen.id : undefined) ?? (exists(call?.id) ? call?.id : undefined) ?? actionable[0]?.id ?? waiting[0]?.id ?? null
  const r = requests.find((x) => x.id === activeId) ?? null
  const position = r ? waiting.findIndex((x) => x.id === r.id) : -1
  const others = waiting.filter((x) => x.id !== r?.id)

  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [open, r?.id, r?.status, r?.entries.length])

  const run: Run = async (action) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      refresh()
    } catch (caught) {
      setError(caught instanceof ApiProblem ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const close = () => {
    setClosedSeq(call?.seq ?? 0)
    setOpened(false)
    setChosen(null)
    setError(null)
  }
  const show = (id: string) => {
    setChosen({ id, seq: call?.seq ?? 0 })
    setError(null)
  }

  if (!open) {
    if (!waiting.length) return null
    return (
      <button
        type="button"
        onClick={() => setOpened(true)}
        aria-label={`Centerline assistant: ${waiting.length} waiting`}
        className="bg-nav fixed right-4 bottom-4 z-40 flex items-center gap-2 rounded-full px-4 py-3 text-white shadow-lg hover:opacity-95"
      >
        <Bot className="size-5" aria-hidden />
        <span className="text-[13px] font-medium">{actionable.length ? t.bubbleReasons(actionable.length) : t.bubbleManager}</span>
        {actionable.length > 0 && <span className="bg-critical-solid size-2.5 animate-pulse rounded-full" aria-hidden />}
      </button>
    )
  }

  return (
    <Words.Provider value={{ t, lang }}>
      <section
        role="dialog"
        aria-label="Centerline assistant"
        className="bg-surface border-line fixed right-3 bottom-3 z-40 flex max-h-[min(660px,calc(100vh-80px))] w-[min(420px,calc(100vw-24px))] flex-col overflow-hidden rounded-xl border shadow-2xl"
      >
        <header className="bg-nav flex items-center gap-2 px-3 py-2.5 text-white">
          <Bot className="size-5 shrink-0" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-[14px] leading-tight font-semibold">Centerline assistant</p>
            <p className="text-nav-fg truncate text-[11px]">
              {r ? `HMI mismatch · ${r.event.zoneName ?? r.event.channel}` : t.nothingWaiting}
            </p>
          </div>
          <span
            role="group"
            aria-label={t.language}
            className="border-nav-border flex shrink-0 overflow-hidden rounded-md border text-[11px]"
          >
            {(['fil', 'en'] as Lang[]).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLang(l)}
                aria-pressed={lang === l}
                className={cn('px-2 py-1 font-medium', lang === l ? 'bg-nav-accent text-white' : 'text-nav-fg hover:bg-nav-hover')}
              >
                {LANG_LABEL[l]}
              </button>
            ))}
          </span>
          {waiting.length > 1 && position >= 0 && (
            <span className="flex items-center gap-0.5 text-[12px]">
              <button
                type="button"
                className="hover:bg-nav-hover rounded p-1 disabled:opacity-40"
                disabled={position === 0}
                onClick={() => show(waiting[position - 1]!.id)}
                aria-label={t.previousMismatch}
              >
                <ChevronLeft className="size-4" aria-hidden />
              </button>
              {t.of(position + 1, waiting.length)}
              <button
                type="button"
                className="hover:bg-nav-hover rounded p-1 disabled:opacity-40"
                disabled={position === waiting.length - 1}
                onClick={() => show(waiting[position + 1]!.id)}
                aria-label={t.nextMismatch}
              >
                <ChevronRight className="size-4" aria-hidden />
              </button>
            </span>
          )}
          <button
            type="button"
            onClick={close}
            className="hover:bg-nav-hover rounded p-1"
            aria-label={waiting.length ? t.minimise : t.close}
          >
            {waiting.length ? <Minus className="size-4" aria-hidden /> : <X className="size-4" aria-hidden />}
          </button>
        </header>

        <div ref={scroller} className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-3 text-[13px]" aria-live="polite">
          {!r ? (
            <Say from="bot">{t.idle}</Say>
          ) : (
            <>
              <Transcript r={r} />
              {r.next === 'reason' && <ReasonStep key={r.id} r={r} busy={busy} run={run} />}
              {r.next === 'answers' && <AnswersStep key={r.id} r={r} fixed={list?.questions ?? []} busy={busy} run={run} />}
              {r.next === 'ocap' && <OcapStep key={r.id} r={r} busy={busy} run={run} />}
              {r.next === 'guidance' && <Say from="bot">{t.waitingManager}</Say>}
              {r.next === 'acknowledgment' && <AcknowledgeStep key={r.id} r={r} busy={busy} run={run} />}
              {r.next === null && (
                <>
                  <Say from="bot">{t.closed[r.status] ?? t.closedOther}</Say>
                  <Replies>
                    {others.length > 0 ? (
                      <Button type="button" size="sm" className="self-start" onClick={() => show(others[0]!.id)}>
                        {t.next(others[0]!.event.zoneName ?? others[0]!.event.channel)}
                      </Button>
                    ) : (
                      <Button type="button" variant="outline" size="sm" className="self-start" onClick={close}>
                        {t.close}
                      </Button>
                    )}
                  </Replies>
                </>
              )}
            </>
          )}
          {busy && r?.next === 'reason' && (
            <Say from="bot">
              <span className="text-ink-muted flex items-center gap-2">
                <Loader2 className="size-3.5 animate-spin" aria-hidden /> {t.readingOcap}
              </span>
            </Say>
          )}
          {error && <p className="text-critical pl-8 text-[12px]">{error}</p>}
        </div>
      </section>
    </Words.Provider>
  )
}
