import type { AnalyticsOptions, AnalyticsQueryRequest, AnalyticsResult } from '@/types/analyticsApi'

import { ApiProblem, json, request } from './http'

export { ApiProblem }

export const analyticsApi = {
  options(signal?: AbortSignal): Promise<AnalyticsOptions> {
    return request<AnalyticsOptions>('/api/v1/analytics/options', { signal })
  },

  query(body: AnalyticsQueryRequest, signal?: AbortSignal): Promise<AnalyticsResult> {
    return request<AnalyticsResult>('/api/v1/analytics/query', json('POST', body, signal))
  },
}
