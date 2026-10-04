import { createContext, useEffect, useState, type ReactNode } from 'react'

import { monitoringApi } from '@/services/monitoringApi'
import type { EventCounts } from '@/types/monitoringApi'

const EVERY_MS = 10_000

/** Open events by kind and severity, shared by the sidebar badge and the bell; refreshed every 10 s. */
const EventCountsContext = createContext<EventCounts | null>(null)

export function EventCountsProvider({ children }: { children: ReactNode }) {
  const [counts, setCounts] = useState<EventCounts | null>(null)

  useEffect(() => {
    let timer: number | undefined
    const load = () => {
      monitoringApi
        .counts()
        .then(setCounts)
        .catch(() => undefined)
        .finally(() => {
          timer = window.setTimeout(load, EVERY_MS)
        })
    }
    load()
    return () => window.clearTimeout(timer)
  }, [])

  return <EventCountsContext.Provider value={counts}>{children}</EventCountsContext.Provider>
}

export { EventCountsContext }
