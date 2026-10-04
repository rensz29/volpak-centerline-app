import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description: string
  action?: ReactNode
  className?: string
  compact?: boolean
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  compact = false,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'px-6 py-10' : 'px-6 py-16',
        className,
      )}
    >
      <span className="bg-surface-muted border-line text-ink-muted grid size-11 place-items-center rounded-lg border">
        <Icon className="size-5" aria-hidden />
      </span>
      <h3 className="text-ink mt-3.5 text-[15px] font-semibold">{title}</h3>
      <p className="text-ink-soft mt-1.5 max-w-sm text-[13px] leading-relaxed">
        {description}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
