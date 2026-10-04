import { createContext, useCallback, useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { ROUTES } from '@/routes/navigation'
import { authApi } from '@/services/authApi'
import { ACTIVITY_EVENT, ApiProblem, SIGNED_OUT_EVENT } from '@/services/http'
import { clearDrafts } from '@/utils/drafts'
import type { SessionInfo } from '@/types/authApi'

/**
 * Who is signed in (ADR-0016). The session itself is an HttpOnly cookie the page never
 * sees; this holds what the api says about it. A 401 from any call signs the page out,
 * with the api's reason (session ended elsewhere, inactivity, account disabled).
 */

export type AuthState =
  | { status: 'loading' }
  /** The api, or its database, doesn't answer: nobody can sign in until it does. */
  | { status: 'unreachable'; problem: ApiProblem }
  | { status: 'signed-out'; reason: string | null }
  /** skewMs: the server's clock minus this browser's, for the inactivity countdown. */
  | { status: 'signed-in'; info: SessionInfo; skewMs: number }

export interface AuthContextValue {
  state: AuthState
  signIn: (name: string, password: string, takeover?: boolean) => Promise<void>
  signOut: (reason?: string) => Promise<void>
  changePassword: (current: string, next: string) => Promise<void>
  /** The person is still here: restarts the 15 min limit of a Manager or Administrator session. */
  stillHere: () => Promise<void>
  retry: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })
  const navigate = useNavigate()

  const accept = useCallback((info: SessionInfo) => {
    setState({ status: 'signed-in', info, skewMs: Date.parse(info.serverTime) - Date.now() })
  }, [])

  const probe = useCallback(() => {
    authApi
      .session()
      .then(accept)
      .catch((caught: unknown) => {
        const problem = caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) })
        if (problem.status !== 401) setState({ status: 'unreachable', problem }) // a 401 is handled below
      })
  }, [accept])

  useEffect(() => {
    const onSignedOut = (e: Event) => {
      const problem = (e as CustomEvent<ApiProblem>).detail
      const quiet = problem.body?.type === '/problems/not-signed-in'
      clearDrafts() // the session ended (its shift, a takeover, inactivity): nothing unsent survives it
      setState({ status: 'signed-out', reason: quiet ? null : `${problem.title}. ${problem.message}` })
    }
    // A change that went through was the person's own doing: the api restarted its inactivity limit
    const onActivity = () =>
      setState((s) =>
        s.status === 'signed-in'
          ? { ...s, info: { ...s.info, session: { ...s.info.session, lastActiveAt: new Date(Date.now() + s.skewMs).toISOString() } } }
          : s,
      )
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut)
    window.addEventListener(ACTIVITY_EVENT, onActivity)
    probe()
    return () => {
      window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut)
      window.removeEventListener(ACTIVITY_EVENT, onActivity)
    }
  }, [probe])

  const signIn = useCallback(
    async (name: string, password: string, takeover = false) => {
      accept(await (takeover ? authApi.takeover(name, password) : authApi.login(name, password)))
    },
    [accept],
  )

  const signOut = useCallback(
    async (reason?: string) => {
      await authApi.logout().catch(() => undefined)
      clearDrafts()
      setState({ status: 'signed-out', reason: reason ?? null })
      // Signing out on purpose hands the screen to the next person: they start at the Digital Centerline.
      // Signed out for inactivity, the page stays, so the same person comes back to it.
      if (!reason) navigate(ROUTES.centerline, { replace: true })
    },
    [navigate],
  )

  const changePassword = useCallback(
    async (current: string, next: string) => accept(await authApi.changePassword(current, next)),
    [accept],
  )

  const stillHere = useCallback(async () => accept(await authApi.activity()), [accept])

  const retry = useCallback(() => {
    setState({ status: 'loading' })
    probe()
  }, [probe])

  return (
    <AuthContext.Provider value={{ state, signIn, signOut, changePassword, stillHere, retry }}>{children}</AuthContext.Provider>
  )
}

export { AuthContext }
