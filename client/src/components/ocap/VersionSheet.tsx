import { Ban, CheckCircle2, Download, Loader2, ShieldAlert } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ocapApi } from '@/services/ocapApi'
import type { OcapVersion } from '@/types/ocapApi'
import { cn } from '@/utils/cn'
import { formatManilaFull } from '@/utils/manilaTime'

import { StatusDialog } from './OcapDialogs'
import { LANGUAGE_LABEL, OCAP_STATUS_LABEL, OCAP_STATUS_TONE, SCAN_LABEL, pagesLabel } from './ocapModel'

const at = (iso: string) => `${formatManilaFull(Date.parse(iso))} Manila`

/** One version as it was read: every section with its pages, the file's scan and fingerprint, and its history (OCP-01). */
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

              <div>
                <p className="micro-label mb-1.5">Sections, as read from the file</p>
                <ol className="flex flex-col gap-2">
                  {v.sections.map((s) => (
                    <li key={s.id} id={`section-${s.id}`}
                        className={cn('border-line-soft rounded-md border p-3', s.id === focusSection && 'ring-brand ring-2')}
                        style={{ marginLeft: `${Math.min(s.level - 1, 3) * 12}px` }}>
                      <p className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="text-ink font-medium">{s.heading ?? 'Opening text'}</span>
                        {pagesLabel(s.pageFrom, s.pageTo) && <span className="text-ink-muted text-[11px]">{pagesLabel(s.pageFrom, s.pageTo)}</span>}
                      </p>
                      {s.body && <p className="text-ink-soft mt-1 whitespace-pre-wrap">{s.body}</p>}
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
