import { BookOpen, Check, Loader2, X } from 'lucide-react'
import { useState } from 'react'

import { SectionText } from '@/components/ocap/SectionText'
import { Button } from '@/components/ui/button'
import type { OcapOffer } from '@/types/workflowApi'

/**
 * After the reason, the operator chooses the OCAP section that fits, read in full first, or says none of them
 * apply and a Manager guides (WF-01, OCP-02, ADR-0031). The sections were matched on the reason's words.
 */
export function OcapOffers({ offers, busy, onChoose }: {
  offers: OcapOffer[]
  busy: boolean
  onChoose: (sectionId: string | null) => void
}) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="flex flex-col gap-2">
      <p className="text-ink-soft">
        {offers.length === 1 ? 'This OCAP section matches' : `These ${offers.length} OCAP sections match`} your reason, best first.
        Read the one that fits in full, then choose it. If none fits, a Manager will guide you.
      </p>
      {offers.map((o) => {
        const reading = open === o.sectionId
        return (
          <div key={o.sectionId} className="border-line rounded-md border p-3">
            <p className="text-ink font-medium">{o.citation}</p>
            <p className="text-ink-muted text-[12px]">{o.title}</p>
            {reading ? (
              <SectionText sectionId={o.sectionId} />
            ) : (
              <p className="text-ink-soft mt-1 line-clamp-3 whitespace-pre-wrap">{o.excerpt}</p>
            )}
            <div className="mt-2 flex flex-wrap justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(reading ? null : o.sectionId)}>
                {reading ? <X className="size-4" aria-hidden /> : <BookOpen className="size-4" aria-hidden />}
                {reading ? 'Close' : 'Read in full'}
              </Button>
              <Button type="button" size="sm" disabled={busy || !reading} title={reading ? undefined : 'Read it in full first'}
                      onClick={() => onChoose(o.sectionId)}>
                {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Check className="size-4" aria-hidden />} This one applies
              </Button>
            </div>
          </div>
        )
      })}
      <Button type="button" variant="outline" size="sm" className="self-end" disabled={busy} onClick={() => onChoose(null)}>
        None of these apply
      </Button>
    </div>
  )
}
