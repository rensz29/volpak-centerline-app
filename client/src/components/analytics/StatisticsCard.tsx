import type { LucideIcon } from 'lucide-react'

import { cn } from '@/utils/cn'

interface StatisticsCardProps {
  label: string
  value: string
  hint?: string
  icon?: LucideIcon
  tone?: 'default' | 'normal' | 'warning' | 'critical'
}

export function StatisticsCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'default',
}: StatisticsCardProps) {
  return (
    <div className="bg-surface border-line rounded-lg border px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <span className="micro-label leading-tight">{label}</span>
        {Icon && <Icon className="text-ink-muted size-3.5 shrink-0" aria-hidden />}
      </div>
      <p
        className={cn(
          'tnum mt-1.5 text-[17px] leading-none font-semibold',
          tone === 'normal' && 'text-normal',
          tone === 'warning' && 'text-warning',
          tone === 'critical' && 'text-critical',
          tone === 'default' && 'text-ink',
        )}
      >
        {value}
      </p>
      {hint && <p className="text-ink-muted mt-1 text-[11px] leading-snug">{hint}</p>}
    </div>
  )
}
