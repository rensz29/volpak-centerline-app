import { Minus, TrendingDown, TrendingUp, type LucideIcon } from 'lucide-react'

import { cn } from '@/utils/cn'

export type SummaryTone = 'neutral' | 'brand' | 'normal' | 'warning' | 'critical' | 'nodata'

const TONE_STYLES: Record<SummaryTone, { rail: string; icon: string; value: string }> = {
  neutral: { rail: 'bg-slate-400', icon: 'bg-surface-muted text-ink-soft', value: 'text-ink' },
  brand: { rail: 'bg-brand', icon: 'bg-brand-surface text-brand', value: 'text-ink' },
  normal: {
    rail: 'bg-normal-solid',
    icon: 'bg-normal-surface text-normal',
    value: 'text-normal',
  },
  warning: {
    rail: 'bg-warning-solid',
    icon: 'bg-warning-surface text-warning',
    value: 'text-warning',
  },
  critical: {
    rail: 'bg-critical-solid',
    icon: 'bg-critical-surface text-critical',
    value: 'text-critical',
  },
  nodata: {
    rail: 'bg-nodata-solid',
    icon: 'bg-nodata-surface text-nodata',
    value: 'text-nodata',
  },
}

export interface SummaryCardProps {
  label: string
  value: number | string
  supportingText: string
  icon: LucideIcon
  tone?: SummaryTone
  /** Change against the previous shift; sign drives the arrow and wording. */
  trend?: number
  trendLabel?: string
  /** For counts, a lower number is the good outcome — flips the trend colour. */
  invertTrendColor?: boolean
  onClick?: () => void
  active?: boolean
}

export function SummaryCard({
  label,
  value,
  supportingText,
  icon: Icon,
  tone = 'neutral',
  trend,
  trendLabel = 'vs previous shift',
  invertTrendColor = false,
  onClick,
  active = false,
}: SummaryCardProps) {
  const styles = TONE_STYLES[tone]
  const Wrapper = onClick ? 'button' : 'div'

  const hasTrend = trend !== undefined && Number.isFinite(trend)
  const TrendIcon = !hasTrend || trend === 0 ? Minus : trend > 0 ? TrendingUp : TrendingDown
  const improving = invertTrendColor ? (trend ?? 0) < 0 : (trend ?? 0) > 0
  const trendClass =
    !hasTrend || trend === 0 ? 'text-ink-muted' : improving ? 'text-normal' : 'text-critical'

  return (
    <Wrapper
      {...(onClick ? { type: 'button' as const, onClick } : {})}
      className={cn(
        'bg-surface border-line shadow-card relative flex flex-col overflow-hidden rounded-lg border pt-4 pr-4 pb-3.5 pl-5 text-left',
        onClick &&
          'focus-visible:ring-brand-ring hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-offset-1',
        active && 'border-brand ring-brand/25 ring-2',
        'transition-colors duration-150',
      )}
      aria-pressed={onClick ? active : undefined}
    >
      {/* Status rail: a thin edge marker rather than a pastel wash across the card. */}
      <span className={cn('absolute inset-y-0 left-0 w-1', styles.rail)} aria-hidden />

      <div className="flex items-start justify-between gap-3">
        <span className="micro-label">{label}</span>
        <span className={cn('grid size-7 shrink-0 place-items-center rounded-md', styles.icon)}>
          <Icon className="size-4" aria-hidden />
        </span>
      </div>

      <span className={cn('tnum mt-2 text-[26px] leading-none font-semibold', styles.value)}>
        {value}
      </span>

      <p className="text-ink-soft mt-1.5 text-[12px] leading-snug">{supportingText}</p>

      {hasTrend && (
        <p className={cn('mt-2 flex items-center gap-1 text-[12px] font-medium', trendClass)}>
          <TrendIcon className="size-3.5 shrink-0" aria-hidden />
          <span className="tnum">
            {trend > 0 ? '+' : trend < 0 ? '−' : ''}
            {Math.abs(trend)}
          </span>
          <span className="text-ink-muted font-normal">{trendLabel}</span>
        </p>
      )}
    </Wrapper>
  )
}
