import type { ProblemDocument } from '@/types/analyticsApi'

/**
 * The browser talks to the Centerline api only (ANA-02). In development Vite
 * proxies /api to the api service on 127.0.0.1:8000. Errors arrive as RFC 9457
 * problem documents and surface as ApiProblem, with per-field messages.
 *
 * Sign-in (ADR-0016): the session is an HttpOnly cookie the browser sends by itself.
 * Every state-changing call carries the CSRF header; a 401 anywhere means the session
 * ended, and a change that went through counts as the person's own activity.
 */

export const CSRF_HEADER = 'X-Centerline-CSRF'
export const SIGNED_OUT_EVENT = 'centerline:signed-out'
export const ACTIVITY_EVENT = 'centerline:activity'
const SAFE = new Set(['GET', 'HEAD', 'OPTIONS'])
const SIGN_IN_PATHS = ['/api/v1/auth/login', '/api/v1/auth/takeover']

export class ApiProblem extends Error {
  readonly status: number
  readonly title: string
  readonly fieldErrors: { field: string; message: string }[]
  readonly body: (ProblemDocument & Record<string, unknown>) | null

  constructor(status: number, body: (ProblemDocument & Record<string, unknown>) | null) {
    super(body?.detail ?? body?.title ?? `Request failed (HTTP ${status})`)
    this.name = 'ApiProblem'
    this.status = status
    this.title = body?.title ?? 'Request failed'
    this.fieldErrors = body?.errors ?? []
    this.body = body
  }

  /** The message for one field, matching "zones[1].actual" or its prefix "zones[1]". */
  forField(field: string): string | undefined {
    return this.fieldErrors.find((e) => e.field === field || e.field.startsWith(`${field}.`))?.message
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers = new Headers(init?.headers)
  if (!SAFE.has(method)) headers.set(CSRF_HEADER, '1')
  let response: Response
  try {
    response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiProblem(0, {
      title: 'The Centerline api is not reachable',
      detail: 'Check that the api service is running (see services/api/README.md).',
    })
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as (ProblemDocument & Record<string, unknown>) | null
    const problem = new ApiProblem(response.status, body)
    // A failed sign-in is a 401 too, but it doesn't end anything
    if (response.status === 401 && !SIGN_IN_PATHS.includes(path)) {
      window.dispatchEvent(new CustomEvent(SIGNED_OUT_EVENT, { detail: problem }))
    }
    throw problem
  }
  if (!SAFE.has(method)) window.dispatchEvent(new Event(ACTIVITY_EVENT))
  return (await response.json()) as T
}

export function json(method: 'POST' | 'PUT', body: unknown, signal?: AbortSignal): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal }
}
