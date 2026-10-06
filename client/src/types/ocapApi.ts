/** The OCAP library (OCP-01…03, ADR-0031): uploaded PDF or Word files read into sections with their pages. */

export type OcapStatus = 'draft' | 'active' | 'suspended' | 'superseded'
/** clean: clamd found nothing; not_scanned: no scanner on this PC; written: typed in Centerline, no file */
export type ScanVerdict = 'clean' | 'not_scanned' | 'written'
export type OcapLanguage = 'en' | 'fil'

export interface OcapVersionSummary {
  id: string
  number: number
  language: OcapLanguage
  /** The uploaded file's name, or "Written in Centerline" */
  source: string
  mediaType: string
  scan: ScanVerdict
  pages: number | null
  sections: number
  createdAt: string
  by: string | null
  reason: string
  status: OcapStatus
  statusAt: string
  statusBy: string | null
}

export interface OcapDocument {
  id: string
  code: string
  title: string
  /** Newest first */
  versions: OcapVersionSummary[]
  /** The numbers of the versions searched now */
  active: number[]
}

export interface OcapListing {
  documents: OcapDocument[]
  counts: { documents: number; active: number }
  scanner: 'none' | 'clamd'
}

export interface OcapVersionSection {
  id: string
  ordinal: number
  /** null: the text before the first heading */
  heading: string | null
  level: number
  pageFrom: number | null
  pageTo: number | null
  body: string
  citation: string
}

export interface OcapVersion {
  id: string
  documentId: string
  code: string
  title: string
  number: number
  language: OcapLanguage
  source: string
  mediaType: string
  sha256: string
  /** The stored file still matches its SHA-256 */
  intact: boolean
  scan: ScanVerdict
  scanDetail: string | null
  pages: number | null
  createdAt: string
  by: string | null
  reason: string
  status: OcapStatus
  sections: OcapVersionSection[]
  history: { status: OcapStatus; at: string; by: string | null; reason: string }[]
}

/** One section with its OCAP, version and citation: what an operator reads (OCP-02). */
export interface OcapSection {
  sectionId: string
  versionId: string
  code: string
  title: string
  version: number
  language: OcapLanguage
  heading: string | null
  pageFrom: number | null
  pageTo: number | null
  body: string
  status: OcapStatus
  /** False for an OCAP written in Centerline: there's no file to download */
  hasFile: boolean
  /** e.g. "OCAP-017 v2 · 3.2 Heater fault · pp. 3–4" */
  citation: string
}

export interface OcapHit extends OcapSection {
  score: number
  /** The matching words between « and » */
  excerpt: string
}

export interface OcapUpload {
  language: OcapLanguage
  source: string
  contentBase64: string
  reason: string
}
