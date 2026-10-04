import { useContext } from 'react'

import { AuthContext, type AuthContextValue } from '@/context/AuthContext'
import type { Role, SessionInfo } from '@/types/authApi'

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return context
}

/** The signed-in session; only inside the signed-in application. */
export function useSession(): SessionInfo {
  const { state } = useAuth()
  if (state.status !== 'signed-in') {
    throw new Error('useSession needs a signed-in account')
  }
  return state.info
}

/**
 * The roles of whoever is signed in (ADR-0016). The api checks them on every call;
 * the page only hides what the role can't use.
 */
export function useRoles() {
  const { state } = useAuth()
  const roles: Role[] = state.status === 'signed-in' ? state.info.user.roles : []
  const has = (...wanted: Role[]) => wanted.some((r) => roles.includes(r))
  return {
    roles,
    has,
    isOperator: has('OPERATOR'),
    isManager: has('MANAGER'),
    isAdministrator: has('ADMINISTRATOR'),
    isPrivileged: has('MANAGER', 'ADMINISTRATOR'),
  }
}
