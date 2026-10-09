import type { OcapHit, OcapListing, OcapSection, OcapUpload, OcapVersion, ReasonDirection } from '@/types/ocapApi'

import { json, request } from './http'

/** The api refuses larger files (ADR-0031). */
export const MAX_FILE_BYTES = 20_000_000
export const ACCEPT = [
  '.pdf', '.docx', '.xlsx', 'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
].join(',')

/** A chosen file as base64, the way the api takes uploads. */
export function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ''))
    reader.onerror = () => reject(reader.error ?? new Error(`Can't read ${file.name}`))
    reader.readAsDataURL(file)
  })
}

/** The OCAP library (ADR-0031): every role reads and searches it; Managers upload, activate and suspend. */
export const ocapApi = {
  list(): Promise<OcapListing> {
    return request<OcapListing>('/api/v1/ocaps')
  },

  search(q: string, limit = 10, signal?: AbortSignal): Promise<{ query: string; results: OcapHit[] }> {
    return request(`/api/v1/ocaps/search?${new URLSearchParams({ q, limit: String(limit) })}`, { signal })
  },

  create(body: OcapUpload & { code: string; title: string }): Promise<OcapVersion> {
    return request<OcapVersion>('/api/v1/ocaps', json('POST', body))
  },

  addVersion(documentId: string, body: OcapUpload): Promise<OcapVersion> {
    return request<OcapVersion>(`/api/v1/ocaps/${documentId}/versions`, json('POST', body))
  },

  version(id: string): Promise<OcapVersion> {
    return request<OcapVersion>(`/api/v1/ocaps/versions/${id}`)
  },

  section(id: string): Promise<OcapSection> {
    return request<OcapSection>(`/api/v1/ocaps/sections/${id}`)
  },

  /** The file as uploaded; the browser downloads it with the session cookie. */
  originalUrl(versionId: string): string {
    return `/api/v1/ocaps/versions/${versionId}/original`
  },

  activate(id: string, reason: string, earlier: 'keep' | 'supersede'): Promise<OcapVersion> {
    return request<OcapVersion>(`/api/v1/ocaps/versions/${id}/activate`, json('POST', { reason, earlier }))
  },

  suspend(id: string, reason: string): Promise<OcapVersion> {
    return request<OcapVersion>(`/api/v1/ocaps/versions/${id}/suspend`, json('POST', { reason }))
  },

  /** The plant's checked Tagalog version of an OCAP version, a Draft (ADR-0044); returns the version */
  addTranslation(versionId: string, body: { source: string; contentBase64: string; reason: string }): Promise<OcapVersion> {
    return request<OcapVersion>(`/api/v1/ocaps/versions/${versionId}/translations`, json('POST', { language: 'fil', ...body }))
  },

  /** Show a Tagalog version to operators, or stop showing it; returns its OCAP version */
  setTranslation(id: string, action: 'activate' | 'withdraw', reason: string): Promise<OcapVersion> {
    return request<OcapVersion>(`/api/v1/ocaps/translations/${id}/${action}`, json('POST', { reason }))
  },

  translationUrl(id: string): string {
    return `/api/v1/ocaps/translations/${id}/original`
  },

  /** Which HMI mismatches offer an Excel row as a reason (ADR-0039); returns its version */
  tagReason(sectionId: string, body: { parameterIds: string[]; direction: ReasonDirection; reason: string }): Promise<OcapVersion> {
    return request<OcapVersion>(`/api/v1/ocaps/sections/${sectionId}/reason`, json('POST', body))
  },
}
