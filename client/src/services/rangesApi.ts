import type { RangesCheck, RangesDraft, RangesOverview, RangesUpload, RangesVersion } from '@/types/rangesApi'

import { json, request } from './http'

const BASE = '/api/v1/config/analytics-ranges'

/** The file's bytes as base64, so the api keeps exactly what was uploaded (ANA-11). */
export async function readUpload(file: File): Promise<RangesUpload> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return { source: file.name, contentBase64: btoa(binary) }
}

/** Analytics-valid ranges (ADR-0029): read by Managers and Administrators, changed by an Administrator. */
export const rangesApi = {
  overview(): Promise<RangesOverview> {
    return request<RangesOverview>(BASE)
  },

  version(number: number): Promise<RangesVersion> {
    return request<RangesVersion>(`${BASE}/versions/${number}`)
  },

  templateUrl: `${BASE}/template.csv`,

  originalUrl(number: number): string {
    return `${BASE}/versions/${number}/original.csv`
  },

  check(upload: RangesUpload): Promise<RangesCheck> {
    return request<RangesCheck>(`${BASE}/versions/check`, json('POST', upload))
  },

  save(draft: RangesDraft): Promise<RangesOverview> {
    return request<RangesOverview>(`${BASE}/versions`, json('POST', draft))
  },

  activate(number: number, body: { expectedActive: number | null; at: string | null; reason: string }): Promise<RangesOverview> {
    return request<RangesOverview>(`${BASE}/versions/${number}/activate`, json('POST', body))
  },

  cancelActivation(id: string, reason: string): Promise<RangesOverview> {
    return request<RangesOverview>(`${BASE}/activations/${encodeURIComponent(id)}/cancel`, json('POST', { reason }))
  },
}
