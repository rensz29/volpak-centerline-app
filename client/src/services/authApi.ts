import type { Account, AccountFields, SessionInfo, TemporaryPassword } from '@/types/authApi'

import { json, request } from './http'

/** Sign-in and the session (ADR-0016). */
export const authApi = {
  session: () => request<SessionInfo>('/api/v1/auth/session'),
  login: (name: string, password: string) => request<SessionInfo>('/api/v1/auth/login', json('POST', { name, password })),
  /** At an operator workstation: take over a session that has had no heartbeat for 5 min (SES-04). */
  takeover: (name: string, password: string) =>
    request<SessionInfo>('/api/v1/auth/takeover', json('POST', { name, password })),
  logout: () => request<{ signedOut: boolean }>('/api/v1/auth/logout', { method: 'POST' }),
  /** The person is still here: restarts the inactivity limit (SES-02). */
  activity: () => request<SessionInfo>('/api/v1/auth/activity', { method: 'POST' }),
  changePassword: (current: string, next: string) =>
    request<SessionInfo>('/api/v1/auth/password', json('POST', { current, new: next })),
}

/** Accounts, for Administrators. A temporary password is in the answer once and never again. */
export const accountsApi = {
  list: () => request<{ accounts: Account[] }>('/api/v1/users'),
  create: (body: AccountFields & { username: string }) => request<TemporaryPassword>('/api/v1/users', json('POST', body)),
  update: (id: string, body: AccountFields & { active: boolean }) =>
    request<{ account: Account; signedOut: number; you: boolean }>(`/api/v1/users/${id}`, json('PUT', body)),
  temporaryPassword: (id: string, reason: string) =>
    request<TemporaryPassword>(`/api/v1/users/${id}/temporary-password`, json('POST', { reason })),
}
