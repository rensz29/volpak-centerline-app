import { useEffect, useRef, useState } from 'react'

import { ApiProblem } from '@/services/http'
import { monitoringApi } from '@/services/monitoringApi'
import type { LiveView } from '@/types/monitoringApi'

const EVERY_MS = 2000 // monitor-core's heartbeat carries the live values every 2 s

/**
 * The live view, refreshed every 2 s while the page is visible. A failed refresh keeps
 * the last view on screen and reports the problem, so a blip doesn't blank the page.
 */
export function useLiveCenterline() {
  const [view, setView] = useState<LiveView | null>(null)
  const [error, setError] = useState<ApiProblem | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    let controller = new AbortController()
    const load = async () => {
      window.clearTimeout(timer.current)
      if (document.visibilityState === 'visible') {
        controller = new AbortController()
        try {
          const next = await monitoringApi.live(controller.signal)
          setView(next)
          setError(null)
          setUpdatedAt(Date.now())
        } catch (caught) {
          if (caught instanceof DOMException && caught.name === 'AbortError') return
          setError(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
        }
      }
      timer.current = window.setTimeout(() => void load(), EVERY_MS)
    }
    void load()
    const onVisible = () => document.visibilityState === 'visible' && void load()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearTimeout(timer.current)
      controller.abort()
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  return { view, error, updatedAt }
}
