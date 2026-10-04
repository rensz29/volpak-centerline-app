import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

interface SectionCardProps {
  title: string
  description?: string
  icon?: LucideIcon
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  /** Removes body padding, for cards whose content is a full-bleed table. */
  flush?: boolean
}

export function SectionCard({
  title,
  description,
  icon: Icon,
  actions,
  children,
  className,
  bodyClassName,
  flush = false,
}: SectionCardProps) {
  return (
    <section
      className={cn(
        'bg-surface border-line shadow-card flex flex-col overflow-hidden rounded-lg border',
        className,
      )}
    >
      <div className="border-line flex flex-wrap items-start justify-between gap-3 border-b px-5 py-3.5">
        <div className="flex min-w-0 items-start gap-2.5">
          {Icon && (
            <span className="bg-surface-muted text-ink-soft mt-0.5 grid size-7 shrink-0 place-items-center rounded-md">
              <Icon className="size-4" aria-hidden />
            </span>
          )}
          <div className="min-w-0">
            <h2 className="text-ink text-[15px] leading-tight font-semibold">{title}</h2>
            {description && (
              <p className="text-ink-soft mt-0.5 text-[12px]">{description}</p>
            )}
          </div>
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>

      <div className={cn('min-w-0 flex-1', !flush && 'p-5', bodyClassName)}>{children}</div>
    </section>
  )
}

interface KeyValueRowProps {
  label: string
  children: ReactNode
  className?: string
}

/** Label/value pair used throughout the details drawer and alarm dialog. */
export function KeyValueRow({ label, children, className }: KeyValueRowProps) {
  return (
    <div className={cn('flex items-baseline justify-between gap-4 py-1.5', className)}>
      <dt className="text-ink-soft shrink-0 text-[12px]">{label}</dt>
      <dd className="text-ink min-w-0 text-right text-[13px] font-medium">{children}</dd>
    </div>
  )
}
