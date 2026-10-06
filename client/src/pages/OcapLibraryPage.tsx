import { BookOpen, FilePlus2, FileUp, Search, ShieldAlert } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { UploadDialog } from '@/components/ocap/OcapDialogs'
import { Excerpt } from '@/components/ocap/SectionText'
import { VersionSheet } from '@/components/ocap/VersionSheet'
import { LANGUAGE_LABEL, OCAP_STATUS_LABEL, OCAP_STATUS_TONE } from '@/components/ocap/ocapModel'
import { EmptyState } from '@/components/shared/EmptyState'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useRoles } from '@/hooks/useAuth'
import { ocapApi } from '@/services/ocapApi'
import type { OcapDocument, OcapHit, OcapListing, OcapVersion } from '@/types/ocapApi'
import { formatManilaFull } from '@/utils/manilaTime'

const SEARCH_AFTER_MS = 300

/**
 * The OCAP library (OCP-01…03, ADR-0031): every role reads and searches the Active versions; any Manager uploads a
 * PDF or Word file as a Draft, checks the sections it was read into, and activates it, or suspends one.
 */
export function OcapLibraryPage() {
  const { isManager } = useRoles()
  const [listing, setListing] = useState<OcapListing | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<OcapHit[] | null>(null)
  const [uploading, setUploading] = useState<{ document: OcapDocument | null } | null>(null)
  const [open, setOpen] = useState<{ versionId: string; section?: string } | null>(null)

  const load = useCallback(() => {
    ocapApi
      .list()
      .then(setListing)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [])
  useEffect(load, [load])

  useEffect(() => {
    const words = q.trim()
    if (words.length < 2) return
    const abort = new AbortController()
    const t = window.setTimeout(() => {
      ocapApi
        .search(words, 10, abort.signal)
        .then((r) => setHits(r.results))
        .catch(() => undefined)
    }, SEARCH_AFTER_MS)
    return () => {
      window.clearTimeout(t)
      abort.abort()
    }
  }, [q])

  const documents = listing?.documents ?? []
  const otherActive = (v: OcapVersion) =>
    documents.find((d) => d.id === v.documentId)?.active.filter((n) => n !== v.number) ?? []
  const searching = q.trim().length >= 2

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="OCAP library"
        description="The out-of-control action plans. After an operator's reason, the Active versions' sections that match it are offered, with their pages; a Manager guides when none apply."
        breadcrumbs={[{ label: 'Alarms' }, { label: 'OCAP library' }]}
        actions={
          isManager ? (
            <Button type="button" size="sm" onClick={() => setUploading({ document: null })}>
              <FileUp className="size-4" aria-hidden /> Upload an OCAP
            </Button>
          ) : undefined
        }
      />

      {listing?.scanner === 'none' && isManager && (
        <p className="border-warning-border bg-warning-surface text-warning flex items-center gap-2 rounded-lg border px-4 py-2.5 text-[13px]">
          <ShieldAlert className="size-4 shrink-0" aria-hidden />
          No malware scanner is set up on this PC: uploads are kept marked “Not scanned”. The plant's server scans each one.
        </p>
      )}

      <SectionCard title="Search" icon={Search} description="The Active versions only, as an operator's reason would find them">
        <div className="relative max-w-xl">
          <Search className="text-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" aria-hidden />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. heater thermocouple fault, or barado ang nozzle"
                 className="pl-9" aria-label="Search the OCAPs" />
        </div>
        {searching && hits !== null && (
          hits.length === 0 ? (
            <p className="text-ink-soft mt-3 text-[13px]">No Active section matches these words.</p>
          ) : (
            <ol className="mt-3 flex flex-col gap-2">
              {hits.map((h) => (
                <li key={h.sectionId}>
                  <button type="button" onClick={() => setOpen({ versionId: h.versionId, section: h.sectionId })}
                          className="border-line hover:bg-surface-muted w-full rounded-md border p-3 text-left text-[13px]">
                    <p className="text-ink font-medium">{h.citation}</p>
                    <p className="text-ink-muted text-[12px]">{h.title} · {LANGUAGE_LABEL[h.language]}</p>
                    <p className="text-ink-soft mt-1"><Excerpt text={h.excerpt} /></p>
                  </button>
                </li>
              ))}
            </ol>
          )
        )}
      </SectionCard>

      {error ? (
        <div className="bg-surface border-line shadow-card rounded-lg border">
          <EmptyState icon={BookOpen} title="Can't load the OCAP library" description={error} />
        </div>
      ) : !listing ? (
        <TableSkeleton rows={4} />
      ) : documents.length === 0 ? (
        <div className="bg-surface border-line shadow-card rounded-lg border">
          <EmptyState icon={BookOpen} title="No OCAPs yet"
                      description={isManager ? 'Upload the plant’s OCAPs as PDF or Word files; each is a Draft until you activate it.'
                                             : 'A Manager uploads the plant’s OCAPs here.'} />
        </div>
      ) : (
        <SectionCard title="Library" icon={BookOpen} flush
                     description={`${listing.counts.documents} OCAP${listing.counts.documents === 1 ? '' : 's'}, ${listing.counts.active} with an Active version`}>
          <table className="w-full text-[13px]">
            <tbody>
              {documents.map((d) => (
                <tr key={d.id} className="border-line-soft border-b align-top last:border-b-0">
                  <td className="px-5 py-3">
                    <p className="text-ink font-medium">{d.code}</p>
                    <p className="text-ink-soft">{d.title}</p>
                    {isManager && (
                      <Button type="button" variant="ghost" size="sm" className="mt-1 -ml-2 h-7 px-2 text-[12px]"
                              onClick={() => setUploading({ document: d })}>
                        <FilePlus2 className="size-3.5" aria-hidden /> New version
                      </Button>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <ul className="flex flex-col gap-1">
                      {d.versions.map((v) => (
                        <li key={v.id}>
                          <button type="button" onClick={() => setOpen({ versionId: v.id })}
                                  className="hover:bg-surface-muted -mx-2 flex w-full flex-wrap items-center gap-2 rounded-md px-2 py-1 text-left">
                            <span className="text-ink w-8 font-medium">v{v.number}</span>
                            <Badge variant={OCAP_STATUS_TONE[v.status]}>{OCAP_STATUS_LABEL[v.status]}</Badge>
                            <span className="text-ink-soft text-[12px]">
                              {v.source} · {v.sections} section{v.sections === 1 ? '' : 's'}
                              {v.pages ? ` · ${v.pages} p.` : ''} · {LANGUAGE_LABEL[v.language]}
                              {v.scan === 'not_scanned' && ' · not scanned'}
                            </span>
                            <span className="text-ink-muted ml-auto text-[11px]">
                              {v.by ?? '—'} · {formatManilaFull(Date.parse(v.createdAt))}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

      {uploading && (
        <UploadDialog
          document={uploading.document}
          onClose={() => setUploading(null)}
          onDone={(v) => {
            setUploading(null)
            toast.success(`${v.code} v${v.number} uploaded as a Draft`, {
              description: `Read into ${v.sections.length} section${v.sections.length === 1 ? '' : 's'}: check them, then activate it.`,
            })
            load()
            setOpen({ versionId: v.id })
          }}
        />
      )}
      {open && (
        <VersionSheet
          key={open.versionId}
          versionId={open.versionId}
          focusSection={open.section}
          otherActive={otherActive}
          canManage={isManager}
          onClose={() => setOpen(null)}
          onChanged={load}
        />
      )}
    </div>
  )
}
