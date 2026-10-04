import type { Connections } from '@/types/configApi'
import type {
  Channel,
  LogState,
  NotificationDetail,
  NotificationsForm,
  NotificationsList,
  RoutingCheck,
  RoutingDraft,
  RoutingOverview,
  RoutingProposal,
  RoutingVersion,
} from '@/types/notificationsApi'

import { json, request } from './http'

/** Notifications (ADR-0023): the log, TEST messages and re-drives, the routing versions and the channel settings. */
export const notificationsApi = {
  list(state: LogState, before?: string): Promise<NotificationsList> {
    const q = new URLSearchParams({ state, limit: '50' })
    if (before) q.set('before', before)
    return request<NotificationsList>(`/api/v1/notifications?${q}`)
  },

  get(id: string): Promise<NotificationDetail> {
    return request<NotificationDetail>(`/api/v1/notifications/${id}`)
  },

  sendTest(channel: Channel, target: string, note: string): Promise<NotificationDetail> {
    return request<NotificationDetail>('/api/v1/notifications/test', json('POST', { channel, target, note }))
  },

  redrive(deliveryId: string, reason: string): Promise<NotificationDetail> {
    return request<NotificationDetail>(`/api/v1/deliveries/${deliveryId}/redrive`, json('POST', { reason }))
  },

  routing(): Promise<RoutingOverview> {
    return request<RoutingOverview>('/api/v1/config/routing')
  },

  routingProposal(): Promise<RoutingProposal> {
    return request<RoutingProposal>('/api/v1/config/routing/proposal')
  },

  routingVersion(number: number): Promise<RoutingVersion> {
    return request<RoutingVersion>(`/api/v1/config/routing/versions/${number}`)
  },

  checkRouting(draft: RoutingDraft, signal?: AbortSignal): Promise<RoutingCheck> {
    return request<RoutingCheck>('/api/v1/config/routing/versions/check', json('POST', draft, signal))
  },

  saveRouting(draft: RoutingDraft): Promise<RoutingOverview> {
    return request<RoutingOverview>('/api/v1/config/routing/versions', json('POST', draft))
  },

  activateRouting(number: number, body: { expectedActive: number | null; at: string | null; reason: string }): Promise<RoutingOverview> {
    return request<RoutingOverview>(`/api/v1/config/routing/versions/${number}/activate`, json('POST', body))
  },

  cancelRoutingActivation(id: string, reason: string): Promise<RoutingOverview> {
    return request<RoutingOverview>(`/api/v1/config/routing/activations/${id}/cancel`, json('POST', { reason }))
  },

  saveConnection(form: NotificationsForm): Promise<Connections> {
    return request<Connections>('/api/v1/config/connections/notifications', json('PUT', form))
  },

  testEmail(form: NotificationsForm): Promise<{ ok: boolean; response: string }> {
    return request('/api/v1/config/connections/notifications/email-test', json('POST', form))
  },
}
