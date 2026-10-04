import { Info, TriangleAlert } from 'lucide-react'

import type { AnalyticsWarning } from '@/types/analyticsApi'
import { cn } from '@/utils/cn'

// Codes that change how far the numbers can be trusted; the rest are context.
const CAUTION = new Set([
  'NO_RANGES',
  'RANGES_REJECTED',
  'HISTORIAN_CLOCK',
  'UNREADABLE',
  'VARIABLE_UNDER_REVIEW',
  'TOO_MANY_PAIRS',
  'NOT_COMPUTABLE',
  'NO_HEARTBEAT',
])

export function AnalysisWarnings({ warnings }: { warnings: AnalyticsWarning[] }) {
  if (warnings.length === 0) return null
  return (
    <ul className="bg-surface border-line shadow-card divide-line-soft divide-y rounded-lg border" aria-label="Notes about this analysis">
      {warnings.map((w, i) => {
        const caution = CAUTION.has(w.code)
        const Icon = caution ? TriangleAlert : Info
        return (
          <li key={`${w.code}-${i}`} className="flex items-start gap-2.5 px-4 py-1.5 text-[13px]">
            <Icon
              className={cn('mt-0.5 size-4 shrink-0', caution ? 'text-warning' : 'text-ink-muted')}
              aria-hidden
            />
            <span className={caution ? 'text-ink' : 'text-ink-soft'}>{w.message}</span>
          </li>
        )
      })}
    </ul>
  )
}
