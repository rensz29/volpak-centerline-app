import type { HealthReport } from '@/types/healthApi'

import { request } from './http'

/** The System health page (ADR-0038). */
export const healthApi = {
  report(signal?: AbortSignal): Promise<HealthReport> {
    return request<HealthReport>('/api/v1/health', { signal })
  },
}
