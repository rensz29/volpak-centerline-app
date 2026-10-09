/** The OCAP library (OCP-01…03, ADR-0031): uploaded PDF or Word files read into sections with their pages, and Excel
 * workbooks read row by row, whose rows can be reasons an operator picks (ADR-0039). */

export type OcapStatus = 'draft' | 'active' | 'suspended' | 'superseded'
/** clean: clamd found nothing; not_scanned: no scanner on this PC; written: typed in Centerline, no file */
export type ScanVerdict = 'clean' | 'not_scanned' | 'written'
export type OcapLanguage = 'en' | 'fil'
/** When a row is offered as a reason: after the HMI setpoint was raised, lowered, or either */
export type ReasonDirection = 'raised' | 'lowered' | 'either'

/** Where a section is: its pages (PDF, Word) or its sheet and rows (Excel) */
export interface SectionPlace {
  pageFrom: number | null
  pageTo: number | null
  sheet: string | null
  rowFrom: number | null
  rowTo: number | null
}

/** A section in Tagalog: the plant's checked translation (ADR-0044) or the local AI's that passed its checks (ADR-0045) */
export interface TagalogText {
  heading: string | null
  body: string
  phenomenon: string | null
  by: 'plant' | 'ai'
  /** The AI's model, for its translation */
  model?: string
}

/** A checked Tagalog version of an OCAP version: Draft until a Manager activates it (ADR-0044) */
export interface OcapTranslation {
  id: string
  language: 'fil'
  source: string
  scan: 'clean' | 'not_scanned'
  status: 'draft' | 'active' | 'withdrawn' | 'superseded'
  createdAt: string
  by: string | null
  reason: string
  statusAt: string
}

/** Which HMI mismatches offer an Excel row as a reason, the latest change in effect (ADR-0039) */
export interface ReasonTag {
  parameterIds: string[]
  direction: ReasonDirection
  at: string
  by: string | null
  /** Why it was set; "Proposed from the file" for the first */
  why: string
}

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

export interface OcapVersionSection extends SectionPlace {
  id: string
  ordinal: number
  /** null: the text before the first heading */
  heading: string | null
  level: number
  body: string
  citation: string
  /** An Excel row's phenomenon: the reason it offers; null for any other section */
  phenomenon: string | null
  reason: ReasonTag | null
  /** Its Tagalog text for the Manager to check: the newest checked version that's a Draft or Active, else the AI's */
  fil: (TagalogText & { status: 'draft' | 'active' }) | null
  /** Why the AI's translation of it isn't shown: the check it failed (it stays English) */
  filNote: string | null
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
  /** What a reason can be offered for: the parameters whose HMI setpoints are judged */
  reasonParameters: { id: string; name: string }[]
  /** Its checked Tagalog versions, newest first */
  translations: OcapTranslation[]
  /** The local AI's Tagalog, a section at a time once the version is Active, where it's switched on (ADR-0045):
   * sections translated, kept in English because a translation failed a check, and still to do */
  aiTagalog: { on: boolean; translated: number; english: number; waiting: number }
}

/** One section with its OCAP, version and citation: what an operator reads (OCP-02). */
export interface OcapSection extends SectionPlace {
  sectionId: string
  versionId: string
  code: string
  title: string
  version: number
  language: OcapLanguage
  heading: string | null
  body: string
  status: OcapStatus
  /** False for an OCAP written in Centerline: there's no file to download */
  hasFile: boolean
  /** e.g. "OCAP-017 v2 · 3.2 Heater fault · pp. 3–4" */
  citation: string
  /** Its Tagalog text: the active checked version's, else the AI's (ADR-0044, ADR-0045) */
  fil?: TagalogText | null
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
