import { useContext } from 'react'

import { CenterlineContext, type CenterlineContextValue } from '@/context/CenterlineContext'
import { ScopeContext, type ScopeContextValue } from '@/context/ScopeContext'

export function useCenterline(): CenterlineContextValue {
  const context = useContext(CenterlineContext)
  if (!context) {
    throw new Error('useCenterline must be used inside a CenterlineProvider')
  }
  return context
}

export function useScope(): ScopeContextValue {
  const context = useContext(ScopeContext)
  if (!context) {
    throw new Error('useScope must be used inside a ScopeProvider')
  }
  return context
}
