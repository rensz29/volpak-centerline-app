import { Ban, CheckCircle2, Download, Languages, ListChecks, Loader2, ShieldAlert } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ocapApi } from '@/services/ocapApi'
import type { OcapVersion, OcapVersionSection } from '@/types/ocapApi'
import { cn } from '@/utils/cn'
import { formatManilaFull } from '@/utils/manilaTime'

import { ReasonTagDialog, StatusDialog, TranslationDialog } from './OcapDialogs'
import { LANGUAGE_LABEL, OCAP_STATUS_LABEL, OCAP_STATUS_TONE, SCAN_LABEL, placeLabel, reasonTagLabel } from './ocapModel'

const at = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`

/** One version as it was read: every section with its pages or rows, the reasons an Excel version offers and when
 * (ADR-0039), the file's scan and fingerprint, and its history (OCP-01). */
export function VersionSheet({ versionId, focusSection, otherActive, canManage, onClose, onChanged }: {
  versionId: string
  /** Scrolled to and marked, e.g. from a search result */
  focusSection?: string
  /** The numbers of the OCAP's other Active versions */
  otherActive: (v: OcapVersion) => number[]
  canManage: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const [v, setV] = useState<OcapVersion | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [acting, setActing] = useState<'activate' | 'suspend' | null>(null)
  const [tagging, setTagging] = useState<OcapVersionSection | null>(null)
  /** A Tagalog version to add ("new"), or one to activate or withdraw (ADR-0044) */
  const [translating, setTranslating] = useState<'new' | { id: string; source: string; action: 'activate' | 'withdraw' } | null>(null)
  const reasons = v?.sections.filter((s) => s.reason) ?? []
  const unoffered = reasons.filter((s) => !s.reason?.parameterIds.length).length

  const load = useCallback(() => {
    ocapApi
      .version(versionId)
      .then(setV)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [versionId])
  useEffect(load, [load])

  useEffect(() => {
    if (v && focusSection) document.getElementById(`section-${focusSection}`)?.scrollIntoView({ block: 'center' })
  }, [v, focusSection])

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-[640px]">
        <SheetHeader>
          <SheetTitle>{v ? `${v.code} v${v.number}` : 'OCAP'}</SheetTitle>
          <SheetDescription>{v ? v.title : ' '}</SheetDescription>
        </SheetHeader>
        <SheetBody className="flex flex-col gap-4 px-5 py-4 text-[13px]">
          {error && <p className="text-critical">{error}</p>}
          {!v && !error && <Loader2 className="text-ink-muted size-5 animate-spin" aria-label="Loading" />}
          {v && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={OCAP_STATUS_TONE[v.status]}>{OCAP_STATUS_LABEL[v.status]}</Badge>
                <Badge variant={v.scan === 'not_scanned' ? 'warning' : 'outline'}>{SCAN_LABEL[v.scan]}</Badge>
                <span className="text-ink-soft">
                  {LANGUAGE_LABEL[v.language]} · {v.sections.length} section{v.sections.length === 1 ? '' : 's'}
                  {v.pages ? ` · ${v.pages} page${v.pages === 1 ? '' : 's'}` : ''}
                </span>
              </div>
              <dl className="text-ink-soft grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-[12px]">
                <dt>From</dt>
                <dd className="text-ink">
                  {v.scan === 'written' ? (
                    v.source
                  ) : (
                    <a href={ocapApi.originalUrl(v.id)} className="text-brand inline-flex items-center gap-1 hover:underline">
                      <Download className="size-3.5" aria-hidden /> {v.source}
                    </a>
                  )}
                </dd>
                <dt>By</dt>
                <dd className="text-ink">{v.by ?? '—'} · {at(v.createdAt)}</dd>
                <dt>Reason</dt>
                <dd className="text-ink">{v.reason || '—'}</dd>
                {v.scanDetail && (
                  <>
                    <dt>Scanner</dt>
                    <dd className="text-ink">{v.scanDetail}</dd>
                  </>
                )}
                <dt>SHA-256</dt>
                <dd className={cn('font-mono text-[11px] break-all', v.intact ? 'text-ink' : 'text-critical')}>
                  {v.sha256}
                  {!v.intact && (
                    <span className="flex items-center gap-1 font-sans text-[12px]">
                      <ShieldAlert className="size-3.5" aria-hidden /> The stored file no longer matches it
                    </span>
                  )}
                </dd>
              </dl>

              {reasons.length > 0 && (
                <p className={cn('flex items-start gap-2 rounded-md border px-3 py-2 text-[12px]',
                                 unoffered ? 'border-warning-border bg-warning-surface' : 'border-line bg-surface-muted')}>
                  <ListChecks className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span>
                    {reasons.length} row{reasons.length === 1 ? '' : 's'} offer a reason operators can pick for an HMI mismatch, on the
                    parameters shown under each.{' '}
                    {unoffered > 0 && <b>{unoffered} {unoffered === 1 ? "isn't" : "aren't"} offered for any parameter yet. </b>}
                    The parameters were proposed from the file: check them{canManage ? ' and change any that are wrong' : ''}.
                  </span>
                </p>
              )}
              <div className="border-line rounded-md border p-3 text-[12px]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="micro-label">Tagalog</p>
                  {canManage && (
                    <Button type="button" variant="outline" size="sm" className="h-7" onClick={() => setTranslating('new')}>
                      <Languages className="size-3.5" aria-hidden /> {v.translations.length ? 'Upload a new Tagalog version' : 'Add the Tagalog version'}
                    </Button>
                  )}
                </div>
                {(v.aiTagalog.on || v.aiTagalog.translated > 0) && (
                  <p className="text-ink-soft mt-1">
                    {v.status !== 'active'
                      ? 'The local AI translates it once it’s Active, a section at a time, while no operator is answering.'
                      : v.aiTagalog.on && v.aiTagalog.waiting > 0
                        ? `The local AI has translated ${v.aiTagalog.translated} of ${v.sections.length} sections; ${v.aiTagalog.waiting} to go, while no operator is answering.`
                        : `The local AI translated ${v.aiTagalog.translated} of ${v.sections.length} sections.`}
                    {v.aiTagalog.english > 0 &&
                      ` ${v.aiTagalog.english} stay${v.aiTagalog.english === 1 ? 's' : ''} in English: the translation failed a check (a number or an instruction word changed, or it wasn’t translated).`}{' '}
                    Operators read it in the chat with the English below it.
                  </p>
                )}
                {v.translations.length === 0 ? (
                  <p className="text-ink-muted mt-1">
                    {v.aiTagalog.on
                      ? 'Optional: the plant’s own checked translation, with the same sheets and rows, shown instead of the AI’s once it’s activated.'
                      : 'None yet. The plant’s checked translation, with the same sheets and rows: operators read it in the chat once it’s activated, with the English below it.'}
                  </p>
                ) : (
                  <ul className="mt-1.5 flex flex-col gap-1">
                    {v.translations.map((tr) => (
                      <li key={tr.id} className="flex flex-wrap items-center gap-2">
                        <Badge variant={tr.status === 'active' ? 'normal' : tr.status === 'draft' ? 'outline' : tr.status === 'withdrawn' ? 'warning' : 'neutral'}>
                          {{ draft: 'Draft', active: 'Active', withdrawn: 'Withdrawn', superseded: 'Superseded' }[tr.status]}
                        </Badge>
                        <a href={ocapApi.translationUrl(tr.id)} className="text-brand hover:underline">{tr.source}</a>
                        <span className="text-ink-muted">{tr.by ?? '—'} · {at(tr.createdAt)}</span>
                        {canManage && (tr.status === 'draft' || tr.status === 'active') && (
                          <Button type="button" variant={tr.status === 'draft' ? 'default' : 'ghost'} size="sm" className="ml-auto h-7"
                                  onClick={() => setTranslating({ id: tr.id, source: tr.source, action: tr.status === 'draft' ? 'activate' : 'withdraw' })}>
                            {tr.status === 'draft' ? 'Activate' : 'Withdraw'}
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <p className="micro-label mb-1.5">Sections, as read from the file</p>
                <ol className="flex flex-col gap-2">
                  {v.sections.map((s) => (
                    <li key={s.id} id={`section-${s.id}`}
                        className={cn('border-line-soft rounded-md border p-3', s.id === focusSection && 'ring-brand ring-2')}
                        style={{ marginLeft: `${Math.min(s.level - 1, 3) * 12}px` }}>
                      <p className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="text-ink font-medium">{s.heading ?? 'Opening text'}</span>
                        {placeLabel(s) && <span className="text-ink-muted text-[11px]">{placeLabel(s)}</span>}
                      </p>
                      {s.body && <p className="text-ink-soft mt-1 whitespace-pre-wrap">{s.body}</p>}
                      {s.fil && (
                        <div className="bg-surface-muted mt-2 rounded px-2 py-1.5 text-[12px]">
                          <p className="text-ink-muted">
                            Tagalog · {s.fil.by === 'ai' ? 'the AI’s translation' : 'checked by the plant'}
                            {s.fil.status === 'draft' ? ' · draft, not shown to operators yet' : ''}
                          </p>
                          <p className="text-ink-soft whitespace-pre-wrap">{s.fil.body}</p>
                        </div>
                      )}
                      {!s.fil && s.filNote && (
                        <p className="text-ink-muted mt-2 text-[12px]">Stays in English: the AI’s translation failed a check ({s.filNote}).</p>
                      )}
                      {s.reason && (
                        <div className={cn('mt-2 flex flex-wrap items-center justify-between gap-2 rounded px-2 py-1.5 text-[12px]',
                                           s.reason.parameterIds.length ? 'bg-surface-muted' : 'bg-warning-surface')}>
                          <span>
                            <span className="text-ink-muted">Reason to pick: </span>
                            <span className="text-ink font-medium">{reasonTagLabel(s.reason)}</span>
                            <span className="text-ink-muted"> · {s.reason.why === 'Proposed from the file' ? 'proposed from the file' : `set by ${s.reason.by ?? '—'}`}</span>
                          </span>
                          {canManage && (
                            <Button type="button" variant="ghost" size="sm" className="h-7" onClick={() => setTagging(s)}>
                              Change
                            </Button>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              </div>

              <div>
                <p className="micro-label mb-1.5">History</p>
                <ol className="flex flex-col gap-1 text-[12px]">
                  {v.history.map((h, i) => (
                    <li key={i} className="text-ink-soft">
                      <span className="text-ink font-medium">{OCAP_STATUS_LABEL[h.status]}</span> · {h.by ?? '—'} · {at(h.at)}
                      {h.reason && <> · “{h.reason}”</>}
                    </li>
                  ))}
                </ol>
              </div>
            </>
          )}
        </SheetBody>
        {v && canManage && (
          <SheetFooter>
            {v.status === 'active' ? (
              <Button type="button" variant="outline" size="sm" onClick={() => setActing('suspend')}>
                <Ban className="size-4" aria-hidden /> Suspend
              </Button>
            ) : (
              <Button type="button" size="sm" onClick={() => setActing('activate')}>
                <CheckCircle2 className="size-4" aria-hidden /> {v.status === 'draft' ? 'Activate' : 'Activate again'}
              </Button>
            )}
          </SheetFooter>
        )}
      </SheetContent>
      {v && translating && (
        <TranslationDialog
          version={v}
          translation={translating === 'new' ? null : translating}
          onClose={() => setTranslating(null)}
          onDone={(next) => {
            setTranslating(null)
            setV(next)
            toast.success('Saved', { description: 'The Tagalog version is updated.' })
            onChanged()
          }}
        />
      )}
      {v && tagging && (
        <ReasonTagDialog
          version={v}
          section={tagging}
          onClose={() => setTagging(null)}
          onDone={(next) => {
            setTagging(null)
            setV(next)
            toast.success('Saved', { description: 'Operators see it on the next requests.' })
            onChanged()
          }}
        />
      )}
      {v && acting && (
        <StatusDialog
          version={v}
          action={acting}
          otherActive={otherActive(v)}
          onClose={() => setActing(null)}
          onDone={(next) => {
            setActing(null)
            setV(next)
            toast.success(next.status === 'active' ? `${next.code} v${next.number} is Active` : `${next.code} v${next.number} is suspended`,
                          { description: next.status === 'active' ? 'Searched from now on.' : 'No longer searched.' })
            onChanged()
          }}
        />
      )}
    </Sheet>
  )
}
