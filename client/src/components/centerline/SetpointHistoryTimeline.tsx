import { ArrowRight, FileClock } from 'lucide-react'

import { EmptyState } from '@/components/shared/EmptyState'
import { SETPOINT_FIELD_LABELS, type SetpointChange } from '@/types'
import { formatNumber, formatRelativeTime, formatTimestamp, initialsOf } from '@/utils/format'

interface SetpointHistoryTimelineProps {
  changes: readonly SetpointChange[]
  limit?: number
}

export function SetpointHistoryTimeline({
  changes,
  limit = 6,
}: SetpointHistoryTimelineProps) {
  if (changes.length === 0) {
    return (
      <EmptyState
        icon={FileClock}
        title="No recorded changes"
        description="No setpoint or tolerance change has been logged for this parameter."
        compact
      />
    )
  }

  return (
    <ol className="relative space-y-0">
      {changes.slice(0, limit).map((change, index, list) => (
        <li key={change.id} className="relative flex gap-3 pb-4 last:pb-0">
          {/* Connector line between entries */}
          {index < list.length - 1 && (
            <span className="bg-line absolute top-8 bottom-0 left-[13px] w-px" aria-hidden />
          )}

          <span className="bg-brand-surface text-brand ring-surface z-10 grid size-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold ring-4">
            {initialsOf(change.changedBy)}
          </span>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <p className="text-ink text-[13px] font-medium">
                {SETPOINT_FIELD_LABELS[change.field]}
              </p>
              <span className="text-ink-muted tnum shrink-0 text-[11px]">
                {formatRelativeTime(change.changedAt)}
              </span>
            </div>

            <p className="tnum text-ink-soft mt-1 flex items-center gap-1.5 text-[12px]">
              <span className="bg-surface-muted border-line rounded border px-1.5 py-0.5 line-through">
                {formatNumber(change.previousValue, 2)} {change.unit}
              </span>
              <ArrowRight className="size-3 shrink-0" aria-hidden />
              <span className="border-normal-border bg-normal-surface text-normal rounded border px-1.5 py-0.5 font-medium">
                {formatNumber(change.newValue, 2)} {change.unit}
              </span>
            </p>

            <p className="text-ink-soft mt-1.5 text-[12px] leading-relaxed">
              {change.reason}
            </p>
            <p className="text-ink-muted mt-1 text-[11px]">
              {change.changedBy} · {formatTimestamp(change.changedAt)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  )
}
