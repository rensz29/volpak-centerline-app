import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

export interface Crumb {
  label: string
  to?: string
}

interface PageHeaderProps {
  title: string
  description?: string
  breadcrumbs?: readonly Crumb[]
  actions?: ReactNode
  className?: string
}

export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn('flex flex-wrap items-end justify-between gap-4', className)}>
      <div className="min-w-0">
        {breadcrumbs && breadcrumbs.length > 0 && (
          <nav aria-label="Breadcrumb" className="mb-1.5">
            <ol className="text-ink-muted flex flex-wrap items-center gap-1 text-[12px]">
              {breadcrumbs.map((crumb, index) => {
                const isLast = index === breadcrumbs.length - 1
                return (
                  <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                    {crumb.to && !isLast ? (
                      <Link
                        to={crumb.to}
                        className="hover:text-brand rounded-sm transition-colors"
                      >
                        {crumb.label}
                      </Link>
                    ) : (
                      <span className={cn(isLast && 'text-ink-soft font-medium')}>
                        {crumb.label}
                      </span>
                    )}
                    {!isLast && (
                      <ChevronRight className="size-3 shrink-0 opacity-60" aria-hidden />
                    )}
                  </li>
                )
              })}
            </ol>
          </nav>
        )}

        <h1 className="text-ink truncate text-xl leading-tight font-semibold tracking-[-0.01em]">
          {title}
        </h1>
        {description && (
          <p className="text-ink-soft mt-1 max-w-3xl text-[13px]">{description}</p>
        )}
      </div>

      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
