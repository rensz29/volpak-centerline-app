import { useContext } from 'react'

import { EventCountsContext } from '@/context/EventCountsContext'
import type { EventCounts } from '@/types/monitoringApi'

/** Open events by kind and severity; null until the first answer. */
export function useEventCounts(): EventCounts | null {
  return useContext(EventCountsContext)
}
