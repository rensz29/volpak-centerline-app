import { Info, TrendingDown, TrendingUp, TriangleAlert, Waves } from 'lucide-react'

import type { CorrelationResult, ParameterDefinition } from '@/types'
import { cn } from '@/utils/cn'
import { describeCorrelation, rSquared } from '@/utils/stats'

interface CorrelationInsightCardProps {
  correlation: CorrelationResult
  xParameter: ParameterDefinition
  yParameter: ParameterDefinition
  /** Mixing SKUs or machines pools different operating regimes together. */
  spansMultipleSkus: boolean
  spansMultipleMachines: boolean
}

export function CorrelationInsightCard({
  correlation,
  xParameter,
  yParameter,
  spansMultipleSkus,
  spansMultipleMachines,
}: CorrelationInsightCardProps) {
  const { coefficient, strength, direction, sampleCount } = correlation

  const tone =
    direction === 'none'
      ? 'neutral'
      : strength === 'very strong' || strength === 'strong'
        ? 'strong'
        : 'moderate'

  const Icon =
    direction === 'none' ? Waves : direction === 'positive' ? TrendingUp : TrendingDown

  const headline =
    direction === 'none'
      ? 'Negligible correlation'
      : `${capitalise(strength)} ${direction} correlation`

  return (
    <section className="bg-surface border-line shadow-card overflow-hidden rounded-lg border">
      <div className="border-line border-b px-4 py-3">
        <h2 className="text-ink text-[15px] font-semibold">Correlation insight</h2>
        <p className="text-ink-soft mt-0.5 text-[12px]">
          {xParameter.name} versus {yParameter.name}
        </p>
      </div>

      <div className="p-4">
        <div
          className={cn(
            'flex items-center gap-3 rounded-lg border px-3.5 py-3',
            tone === 'strong'
              ? 'border-brand/25 bg-brand-surface'
              : tone === 'moderate'
                ? 'border-warning-border bg-warning-surface'
                : 'border-line bg-surface-muted',
          )}
        >
          <span
            className={cn(
              'grid size-10 shrink-0 place-items-center rounded-md',
              tone === 'strong'
                ? 'bg-brand text-white'
                : tone === 'moderate'
                  ? 'bg-warning-solid text-white'
                  : 'bg-nodata-solid text-white',
            )}
          >
            <Icon className="size-5" aria-hidden />
          </span>

          <div className="min-w-0">
            <p className="tnum text-ink text-[22px] leading-none font-semibold">
              {coefficient >= 0 ? '' : '−'}
              {Math.abs(coefficient).toFixed(2)}
            </p>
            <p
              className={cn(
                'mt-1 text-[13px] font-medium',
                tone === 'strong'
                  ? 'text-brand'
                  : tone === 'moderate'
                    ? 'text-warning'
                    : 'text-ink-soft',
              )}
            >
              {headline}
            </p>
          </div>
        </div>

        <p className="text-ink-soft mt-3 text-[13px] leading-relaxed">
          {describeCorrelation(correlation)}
        </p>

        <dl className="border-line mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t pt-3">
          <Stat label="Coefficient (r)" value={coefficient.toFixed(3)} />
          <Stat label="Variance explained (r²)" value={`${(rSquared(coefficient) * 100).toFixed(1)}%`} />
          <Stat label="Paired samples" value={String(sampleCount)} />
          <Stat
            label="Fit slope"
            value={`${correlation.slope >= 0 ? '' : '−'}${Math.abs(correlation.slope).toFixed(3)}`}
          />
        </dl>

        {/* The confounding warning: pooling regimes is the classic way to read a
            relationship into data that does not contain one. */}
        {(spansMultipleSkus || spansMultipleMachines) && (
          <p className="border-warning-border bg-warning-surface text-warning mt-3 flex items-start gap-2 rounded-md border px-3 py-2.5 text-[12px] leading-relaxed">
            <TriangleAlert className="mt-px size-4 shrink-0" aria-hidden />
            <span>
              <strong className="font-semibold">Mixed operating regimes.</strong> This
              selection spans{' '}
              {[
                spansMultipleSkus ? 'several SKUs' : null,
                spansMultipleMachines ? 'several machines' : null,
              ]
                .filter(Boolean)
                .join(' and ')}
              , which run at different magnitudes. Grouped differences can inflate the
              coefficient on their own. Narrow to a single SKU and machine before reading
              this figure as a process relationship.
            </span>
          </p>
        )}

        <p className="text-ink-soft border-line bg-surface-muted mt-3 flex items-start gap-2 rounded-md border px-3 py-2.5 text-[12px] leading-relaxed">
          <Info className="text-brand mt-px size-4 shrink-0" aria-hidden />
          Correlation indicates a relationship between variables but does not prove
          causation.
        </p>
      </div>
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-ink-muted text-[11px]">{label}</dt>
      <dd className="tnum text-ink mt-0.5 text-[13px] font-semibold">{value}</dd>
    </div>
  )
}

function capitalise(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}
