import { ArrowDownRight, ArrowUpRight, Database, GitCompareArrows, Minus, Sigma } from 'lucide-react'

import { KeyValueRow, SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import type { AnalyticsResult, Exclusions } from '@/types/analyticsApi'
import { formatDuration } from '@/utils/manilaTime'

import { formatValue, sentenceCase, variableLabel } from './chartOptions'

const count = (n: number) => n.toLocaleString('en-US')

function strengthVariant(strength: string | null) {
  if (strength === 'very strong' || strength === 'strong') return 'default' as const
  if (strength === 'moderate') return 'neutral' as const
  return 'outline' as const
}

/** Pearson r, the fitted line and the causation note (ANA-12, ANA-13, ANA-14). */
export function CorrelationCard({ result }: { result: AnalyticsResult }) {
  const corr = result.statistics?.correlation
  const DirectionIcon =
    corr?.direction === 'positive' ? ArrowUpRight : corr?.direction === 'negative' ? ArrowDownRight : Minus
  return (
    <SectionCard
      title="Correlation"
      description={`${variableLabel(result.y)} against ${variableLabel(result.x)}`}
      icon={GitCompareArrows}
    >
      {!corr ? (
        <p className="text-ink-soft text-[13px]">
          No statistics: the query returned more buckets than the {count(result.sizeGuard.limit)} limit.
        </p>
      ) : !corr.computable ? (
        <p className="text-ink-soft text-[13px]">Not computable: {corr.reason}</p>
      ) : (
        <>
          <div className="flex items-end justify-between gap-3">
            <div>
              <span className="micro-label">Pearson r</span>
              <p className="tnum text-ink mt-1 text-3xl leading-none font-semibold">{corr.r?.toFixed(3)}</p>
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <Badge variant={strengthVariant(corr.strength)}>{sentenceCase(corr.strength)}</Badge>
              <span className="text-ink-soft flex items-center gap-1 text-[12px] capitalize">
                <DirectionIcon className="size-3.5" aria-hidden />
                {corr.direction}
              </span>
            </div>
          </div>
          <dl className="divide-line-soft mt-4 divide-y">
            <KeyValueRow label="R²">
              <span className="tnum">{corr.rSquared?.toFixed(3)}</span>
            </KeyValueRow>
            <KeyValueRow label="Least-squares line">
              <span className="tnum font-mono text-[12px]">{corr.equation}</span>
            </KeyValueRow>
            <KeyValueRow label="Paired buckets">
              <span className="tnum">{count(corr.n)}</span>
            </KeyValueRow>
          </dl>
        </>
      )}
      <p className="text-ink-muted border-line mt-4 border-t pt-3 text-[12px] leading-relaxed">{result.note}</p>
    </SectionCard>
  )
}

/** Minimum, maximum, mean and standard deviation of the paired buckets (ANA-12). */
export function SeriesStatsCard({ result }: { result: AnalyticsResult }) {
  const s = result.statistics
  const rows: [string, 'min' | 'max' | 'mean' | 'sd'][] = [
    ['Minimum', 'min'],
    ['Maximum', 'max'],
    ['Mean', 'mean'],
    ['Std deviation', 'sd'],
  ]
  return (
    <SectionCard title="Summary statistics" description="Over the paired buckets" icon={Sigma} flush>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-line text-ink-muted border-b text-left text-[11px] uppercase">
            <th className="px-4 py-2 font-semibold" />
            <th className="px-4 py-2 text-right font-semibold">X {result.x.unit ?? ''}</th>
            <th className="px-4 py-2 text-right font-semibold">Y {result.y.unit ?? ''}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, key]) => (
            <tr key={key} className="border-line-soft border-b last:border-0">
              <td className="text-ink-soft px-4 py-1.5">{label}</td>
              <td className="tnum text-ink px-4 py-1.5 text-right">{formatValue(s?.x[key])}</td>
              <td className="tnum text-ink px-4 py-1.5 text-right">{formatValue(s?.y[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </SectionCard>
  )
}

function exclusionRows(e: Exclusions): [string, string][] {
  const rows: [string, string][] = [['Samples read', count(e.samples)]]
  const reasons: [string, number][] = [
    ['Bad quality', e.badQuality],
    ['Empty', e.null],
    ['Not a number', e.nonNumeric],
    ['NaN', e.nan],
    ['Infinite', e.infinite],
    ['Outside Analytics-valid range', e.outOfRange],
  ]
  for (const [label, n] of reasons) if (n > 0) rows.push([`Excluded: ${label.toLowerCase()}`, count(n)])
  if (e.unreadableSeconds > 0) rows.push(['Unreadable in Timebase', formatDuration(e.unreadableSeconds)])
  if (e.gapSeconds > 0) rows.push(['No data from the machine', formatDuration(e.gapSeconds)])
  return rows
}

/** What was read, what was excluded and why, and how many buckets paired (ANA-08, ANA-09). */
export function DataQualityCard({ result }: { result: AnalyticsResult }) {
  const b = result.buckets
  return (
    <SectionCard title="Data quality" description="Excluded samples are never filled with zero" icon={Database}>
      <div className="flex flex-col gap-3">
        {(['x', 'y'] as const).map((axis) => (
          <div key={axis} className="min-w-0">
            <span className="micro-label">{axis.toUpperCase()} · {variableLabel(result[axis])}</span>
            <dl className="mt-1">
              {exclusionRows(result.exclusions[axis]).map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-2 py-0.5 text-[12px]">
                  <dt className="text-ink-soft">{label}</dt>
                  <dd className="tnum text-ink font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
      <dl className="border-line mt-3 border-t pt-2">
        <KeyValueRow label="Buckets in range">
          <span className="tnum">{count(b.total)}</span>
        </KeyValueRow>
        <KeyValueRow label="Valid X · valid Y">
          <span className="tnum">
            {count(b.xValid)} · {count(b.yValid)}
          </span>
        </KeyValueRow>
        {b.outsideShift > 0 && (
          <KeyValueRow label="Outside the chosen shift">
            <span className="tnum">{count(b.outsideShift)}</span>
          </KeyValueRow>
        )}
        <KeyValueRow label="Paired buckets">
          <span className="tnum">{count(b.paired)}</span>
        </KeyValueRow>
      </dl>
    </SectionCard>
  )
}
