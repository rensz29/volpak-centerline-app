/** Accounts, sign-in and sessions (ADR-0016), as the Centerline api returns them. */

export type Role = 'OPERATOR' | 'MANAGER' | 'ADMINISTRATOR'

export const ROLE_LABEL: Record<Role, string> = { OPERATOR: 'Operator', MANAGER: 'Manager', ADMINISTRATOR: 'Administrator' }

export interface SessionInfo {
  user: { id: string; username: string; displayName: string; roles: Role[]; mustChange: boolean }
  session: {
    kind: 'operator' | 'privileged'
    workstation: string | null
    signedInAt: string
    lastActiveAt: string
    /** Managers and Administrators: signed out after this long without activity (SES-02); operators: null */
    idleLimitS: number | null
    idleWarningS: number | null
    /** Operators: the session ends with its shift (SES-03), with a warning this many seconds before */
    endsWithShift: boolean
    shiftWarningS: number
  }
  /** An operator's: the shift the session belongs to. Managers and Administrators: the shift now. */
  shift: { code: 'A' | 'B' | 'C'; label: string; startsAt: string; endsAt: string }
  serverTime: string
}

export interface Account {
  id: string
  username: string
  displayName: string
  email: string | null
  employeeId: string | null
  roles: Role[]
  active: boolean
  mustChange: boolean
  temporaryExpiresAt: string | null
  lockedUntil: string | null
  lastSignInAt: string | null
  createdAt: string
  sessions: number
}

export interface AccountFields {
  displayName: string
  email: string | null
  employeeId: string | null
  roles: Role[]
  reason: string
}

export interface TemporaryPassword {
  account: Account
  temporaryPassword: string
  temporaryExpiresAt: string
}
