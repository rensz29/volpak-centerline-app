import {
  createContext,
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export const ALL = 'all' as const

export interface ScopeSelection {
  factoryId: string
  lineId: string
  machineId: string
}

export interface ScopeContextValue extends ScopeSelection {
  setFactory: (factoryId: string) => void
  setLine: (lineId: string) => void
  setMachine: (machineId: string) => void
  reset: () => void
}

const INITIAL: ScopeSelection = {
  factoryId: ALL,
  lineId: ALL,
  machineId: ALL,
}

const ScopeContext = createContext<ScopeContextValue | null>(null)

/**
 * Factory / line / machine selection shared by the header selectors and every
 * page. Selecting upward in the hierarchy clears the narrower selections below
 * it, so the scope can never describe an impossible combination such as a
 * machine that does not belong to the chosen line.
 */
export function ScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<ScopeSelection>(INITIAL)

  const setFactory = useCallback((factoryId: string) => {
    setScope({ factoryId, lineId: ALL, machineId: ALL })
  }, [])

  const setLine = useCallback((lineId: string) => {
    setScope((current) => ({ ...current, lineId, machineId: ALL }))
  }, [])

  const setMachine = useCallback((machineId: string) => {
    setScope((current) => ({ ...current, machineId }))
  }, [])

  const reset = useCallback(() => setScope(INITIAL), [])

  const value = useMemo<ScopeContextValue>(
    () => ({ ...scope, setFactory, setLine, setMachine, reset }),
    [scope, setFactory, setLine, setMachine, reset],
  )

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>
}

export { ScopeContext }
