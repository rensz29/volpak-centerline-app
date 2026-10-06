import type { OcapLanguage, OcapStatus, ScanVerdict } from '@/types/ocapApi'

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

export function sizeLabel(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
