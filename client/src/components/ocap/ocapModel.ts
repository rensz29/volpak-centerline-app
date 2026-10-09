import type { OcapLanguage, OcapStatus, ReasonDirection, ScanVerdict, SectionPlace } from '@/types/ocapApi'

/** How the library names each status of a version (OCP-01, OCP-03, ADR-0031). */
export const OCAP_STATUS_LABEL: Record<OcapStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  suspended: 'Suspended',
  superseded: 'Superseded',
}

export const OCAP_STATUS_TONE: Record<OcapStatus, 'outline' | 'normal' | 'warning' | 'neutral'> = {
  draft: 'outline',
  active: 'normal',
  suspended: 'warning',
  superseded: 'neutral',
}

export const SCAN_LABEL: Record<ScanVerdict, string> = {
  clean: 'Scanned: clean',
  not_scanned: 'Not scanned',
  written: 'Written in Centerline',
}

export const LANGUAGE_LABEL: Record<OcapLanguage, string> = { en: 'English', fil: 'Filipino' }

/** An excerpt's text split at the «…» marks the search puts around matching words: odd pieces are matches. */
export function excerptPieces(excerpt: string): string[] {
  return excerpt.split(/«([^»]*)»/)
}

export function pagesLabel(from: number | null, to: number | null): string | null {
  if (from === null) return null
  return to !== null && to !== from ? `pp. ${from}–${to}` : `p. ${from}`
}

/** Where a section is: "pp. 3–4", or an Excel row's "Troubleshooting, rows 4–5" (ADR-0039) */
export function placeLabel(s: SectionPlace): string | null {
  if (s.sheet && s.rowFrom) {
    return `${s.sheet}, ${s.rowTo !== null && s.rowTo !== s.rowFrom ? `rows ${s.rowFrom}–${s.rowTo}` : `row ${s.rowFrom}`}`
  }
  return pagesLabel(s.pageFrom, s.pageTo)
}

export const DIRECTION_LABEL: Record<ReasonDirection, string> = {
  raised: 'when raised',
  lowered: 'when lowered',
  either: 'raised or lowered',
}

export function sizeLabel(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** "P02, P03 · when raised", or that it isn't offered */
export function reasonTagLabel(tag: { parameterIds: string[]; direction: ReasonDirection }): string {
  return tag.parameterIds.length ? `${tag.parameterIds.join(', ')} · ${DIRECTION_LABEL[tag.direction]}` : 'Not offered: no parameter ticked'
}
