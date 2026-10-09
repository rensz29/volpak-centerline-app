import { Download, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { ocapApi } from '@/services/ocapApi'
import type { OcapSection } from '@/types/ocapApi'

import { OCAP_STATUS_LABEL, excerptPieces } from './ocapModel'

/** Text with the search's «…» matches marked. */
export function Excerpt({ text }: { text: string }) {
  return (
    <>
      {excerptPieces(text).map((piece, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="bg-warning-surface text-ink rounded-sm px-0.5">
            {piece}
          </mark>
        ) : (
          piece
        ),
      )}
    </>
  )
}

/**
 * One OCAP section's text in full, exactly as read from its file, under its citation (OCP-02: the exact source). In
 * Tagalog (`tagalog`), its Tagalog text comes first when there's one, saying whose: the plant's checked version
 * (ADR-0044) or the local AI's (ADR-0045). The English stays below it, as the official text.
 */
export function SectionText({ sectionId, section: given = null, tagalog = false }: {
  sectionId: string
  section?: OcapSection | null
  tagalog?: boolean
}) {
  const [section, setSection] = useState<OcapSection | null>(given)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (given) return
    ocapApi
      .section(sectionId)
      .then(setSection)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [sectionId, given])

  if (error) return <p className="text-critical text-[12px]">{error}</p>
  if (!section) return <Loader2 className="text-ink-muted size-4 animate-spin" aria-label="Loading the section" />
  return (
    <div className="bg-surface-muted border-line-soft mt-2 flex flex-col gap-2 rounded-md border p-3">
      {section.status !== 'active' && (
        <p className="text-warning text-[11px]">{section.code} v{section.version} is now {OCAP_STATUS_LABEL[section.status]}: no longer offered</p>
      )}
      {tagalog && section.fil && (
        <>
          <p className="text-ink-muted text-[11px] font-medium">
            {section.fil.by === 'ai' ? 'Salin ng AI · maaaring may mali, kaya basahin din ang English' : 'Sa Tagalog · sinuri ng plant'}
          </p>
          <p className="text-ink max-h-[320px] overflow-y-auto whitespace-pre-wrap">{section.fil.body}</p>
          <p className="text-ink-muted border-line-soft border-t pt-2 text-[11px] font-medium">Opisyal na OCAP (English)</p>
        </>
      )}
      <p className="text-ink max-h-[320px] overflow-y-auto whitespace-pre-wrap">{section.body || '(no text under this heading)'}</p>
      {section.hasFile && (
        <a href={ocapApi.originalUrl(section.versionId)} className="text-brand inline-flex items-center gap-1 self-start text-[12px] hover:underline">
          <Download className="size-3.5" aria-hidden /> The file as uploaded
        </a>
      )}
    </div>
  )
}
