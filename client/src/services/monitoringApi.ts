import type {
  BriefChange,
  ControlView,
  EventCounts,
  EventDetail,
  EventFilters,
  LiveView,
  MaintenanceWindow,
  MonitorEvent,
} from '@/types/monitoringApi'

import { json, request } from './http'

const query = (filters: EventFilters) =>
  new URLSearchParams(
    Object.entries(filters)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString()

/** The Digital Centerline page's calls (ADR-0015), and a Manager's acknowledgment (ADR-0016). */
export const monitoringApi = {
  live(signal?: AbortSignal): Promise<LiveView> {
    return request<LiveView>('/api/v1/monitoring/live', { signal })
  },

  /** Newest first; `next` asks for the page after this one. */
  events(filters: EventFilters = {}): Promise<{ events: MonitorEvent[]; next: string | null }> {
    return request(`/api/v1/events?${query(filters)}`)
  },

  counts(): Promise<EventCounts> {
    return request<EventCounts>('/api/v1/events/counts')
  },

  /** A download link for Managers and Administrators (EXP-01): the browser sends the session cookie itself. */
  exportUrl(filters: EventFilters): string {
    const { before: _b, limit: _l, ...rest } = filters
    return `/api/v1/events/export.csv?${query(rest)}`
  },

  event(id: string): Promise<EventDetail> {
    return request<EventDetail>(`/api/v1/events/${encodeURIComponent(id)}`)
  },

  briefChanges(limit = 20): Promise<{ briefChanges: BriefChange[] }> {
    return request(`/api/v1/monitoring/brief-changes?limit=${limit}`)
  },

  control(): Promise<ControlView> {
    return request<ControlView>('/api/v1/monitoring/control')
  },

  /** A Manager switches zones off, with a reason, or on again (MON-01, ADR-0017). */
  switchZones(channels: string[], on: boolean, reason: string): Promise<ControlView & { changed: string[] }> {
    return request('/api/v1/monitoring/switch', json('POST', { channels, on, reason }))
  },

  maintenance(limit = 50): Promise<{ serverTime: string; windows: MaintenanceWindow[] }> {
    return request(`/api/v1/maintenance?limit=${limit}`)
  },

  /** An Administrator opens a window for the line or chosen zones; no start means now (MNT-01). */
  openWindow(body: { scope: 'line' | 'zones'; channels: string[]; reason: string; start: string | null; end: string }): Promise<MaintenanceWindow> {
    return request('/api/v1/maintenance', json('POST', body))
  },

  extendWindow(id: string, end: string, reason: string): Promise<MaintenanceWindow> {
    return request(`/api/v1/maintenance/${encodeURIComponent(id)}/extend`, json('POST', { end, reason }))
  },

  endWindow(id: string, reason: string): Promise<MaintenanceWindow> {
    return request(`/api/v1/maintenance/${encodeURIComponent(id)}/end`, json('POST', { reason }))
  },

  /** A Manager acknowledges an open Critical: its repeats stop once monitor-core applies it (ACT-04). */
  acknowledge(id: string, note: string): Promise<{ acknowledgedBy: string; at: string; criticalPeriod: number }> {
    return request(`/api/v1/events/${encodeURIComponent(id)}/acknowledge`, json('POST', { note }))
  },
}
