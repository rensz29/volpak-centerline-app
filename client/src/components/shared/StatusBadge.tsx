import type { ParameterStatus } from '@/types'
import { cn } from '@/utils/cn'
import { STATUS_META } from '@/utils/status'

interface StatusBadgeProps {
  status: ParameterStatus
  /** Compact form drops the icon but keeps the dot and label. */
  compact?: boolean
  className?: string
}

/**
 * Status is never carried by colour alone: every badge pairs the hue with a
 * shape (dot), a glyph (icon) and a written label, so it survives colour
 * blindness and the washed-out contrast of a glare-lit factory panel.
 */
export function StatusBadge({ status, compact = false, className }: StatusBadgeProps) {
  const meta = STATUS_META[status]
  const Icon = meta.icon

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px] font-medium whitespace-nowrap',
        meta.badge,
        className,
      )}
    >
      <span className={cn('size-2 shrink-0 rounded-full', meta.dot)} aria-hidden />
      {!compact && <Icon className="size-3.5 shrink-0" aria-hidden />}
      {meta.label}
    </span>
  )
}

export function StatusDot({
  status,
  className,
}: {
  status: ParameterStatus
  className?: string
}) {
  const meta = STATUS_META[status]
  return (
    <span
      className={cn('inline-block size-2.5 shrink-0 rounded-full', meta.dot, className)}
      role="img"
      aria-label={meta.label}
    />
  )
}
