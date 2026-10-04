import { CloudOff, Database, GitCompareArrows, Loader2, SearchX } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { AnalysisQueryPanel } from '@/components/correlation/AnalysisQueryPanel'
import { AnalysisWarnings } from '@/components/correlation/AnalysisWarnings'
import { ScatterView, TrendView } from '@/components/correlation/CorrelationCharts'
import { GroupStatsTable } from '@/components/correlation/GroupStatsTable'
import { CorrelationCard, DataQualityCard, SeriesStatsCard } from '@/components/correlation/ResultCards'
import { variableLabel } from '@/components/correlation/chartOptions'
import { EmptyState } from '@/components/shared/EmptyState'
import { ChartSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { ScatterChartIcon } from '@/components/shared/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCorrelationAnalysis } from '@/hooks/useCorrelationAnalysis'
import type { AnalyticsResult, BucketCode } from '@/types/analyticsApi'
import { formatDuration, formatManilaShort } from '@/utils/manilaTime'

type ChartTab = 'scatter' | 'trend'

/**
 * Analytics & Correlation on Timebase history (ANA-01…21, ADR-0008).
 * The api fetches, cleans, buckets, pairs and computes; this page only renders
 * its one result, so Scatter and Trend always show the same dataset.
 */
export function AnalyticsCorrelationPage() {
  const analysis = useCorrelationAnalysis()
  const { options, form, result, status, error } = analysis
  const [params, setParams] = useSearchParams()
  const tab: ChartTab = params.get('view') === 'trend' ? 'trend' : 'scatter'
  const setTab = (next: ChartTab) => setParams(next === 'scatter' ? {} : { view: next }, { replace: true })
  const running = status === 'running'

  const applyBucket = (bucket: BucketCode) => {
    if (!form) return
    const next = { ...form, bucket }
    analysis.update({ bucket })
    void analysis.run(next)
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Analytics & Correlation"
        description="Correlate any two zone values, actual or setpoint, from Timebase history. Buckets pair X and Y at the same time; a missing bucket is left out, never filled with zero. Times are Asia/Manila."
        breadcrumbs={[{ label: 'Monitoring' }, { label: 'Analytics & Correlation' }]}
        actions={
          <Badge variant="neutral" className="gap-1.5">
            <Database className="size-3.5" aria-hidden />
            Timebase history · read-only
          </Badge>
        }
      />

      {options && form ? (
        <AnalysisQueryPanel
          options={options}
          form={form}
          onChange={analysis.update}
          onRun={() => void analysis.run(form)}
          running={running}
          fieldErrors={error?.fieldErrors ?? []}
        />
      ) : status === 'error' ? null : (
        <Skeleton className="h-[188px] w-full rounded-lg" />
      )}

      {error && error.fieldErrors.length === 0 && (
        <div className="bg-surface border-critical-border shadow-card rounded-lg border">
          <EmptyState compact icon={CloudOff} title={error.title} description={error.message} />
        </div>
      )}

      {result && !running && <AnalysisWarnings warnings={result.warnings} />}

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <Tabs value={tab} onValueChange={(value) => setTab(value as ChartTab)}>
            <div className="bg-surface border-line shadow-card overflow-hidden rounded-lg border">
              <div className="border-line flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
                <TabsList>
                  <TabsTrigger value="scatter">
                    <ScatterChartIcon className="size-4" aria-hidden />
                    Scatter analysis
                  </TabsTrigger>
                  <TabsTrigger value="trend">
                    <GitCompareArrows className="size-4" aria-hidden />
                    Trend comparison
                  </TabsTrigger>
                </TabsList>
                {result && !running && <ResultCaption result={result} />}
              </div>
              <div className="p-4">
                {running ? (
                  <Running since={analysis.startedAt} />
                ) : !result ? (
                  status === 'error' ? null : <ChartSkeleton height={460} />
                ) : result.sizeGuard.exceeded ? (
                  <EmptyState
                    icon={SearchX}
                    title={`${result.buckets.paired.toLocaleString('en-US')} paired buckets is over the ${result.sizeGuard.limit.toLocaleString('en-US')} limit`}
                    description="Nothing is sampled away silently (ANA-19). Use a longer bucket, or shorten the date range."
                    action={
                      result.sizeGuard.recommendedBucket && (
                        <Button size="sm" onClick={() => applyBucket(result.sizeGuard.recommendedBucket!)}>
                          Use {bucketLabel(options, result.sizeGuard.recommendedBucket)} buckets
                        </Button>
                      )
                    }
                  />
                ) : result.buckets.paired === 0 ? (
                  <EmptyState
                    icon={SearchX}
                    title="No paired buckets"
                    description="Neither the range nor the shift filter left any bucket where both X and Y have valid data. See Data quality for why."
                  />
                ) : (
                  <>
                    <TabsContent value="scatter">
                      <ScatterView result={result} />
                    </TabsContent>
                    <TabsContent value="trend">
                      <TrendView result={result} />
                    </TabsContent>
                  </>
                )}
              </div>
            </div>
          </Tabs>
          {result && !running && result.query.groupStats && <GroupStatsTable result={result} />}
        </div>

        <div className="flex w-full shrink-0 flex-col gap-4 xl:w-[340px]">
          {result && !running ? (
            <>
              <CorrelationCard result={result} />
              <SeriesStatsCard result={result} />
              <DataQualityCard result={result} />
            </>
          ) : status !== 'error' ? (
            <>
              <Skeleton className="h-[250px] w-full rounded-lg" />
              <Skeleton className="h-[180px] w-full rounded-lg" />
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function bucketLabel(options: ReturnType<typeof useCorrelationAnalysis>['options'], code: BucketCode): string {
  return options?.buckets.find((b) => b.code === code)?.label ?? code
}

function ResultCaption({ result }: { result: AnalyticsResult }) {
  const q = result.query
  const offset = result.meta.historianClockOffsetS
  return (
    <p className="text-ink-soft text-[12px]">
      <span className="text-ink font-medium">{variableLabel(result.y)}</span> against{' '}
      <span className="text-ink font-medium">{variableLabel(result.x)}</span> ·{' '}
      {formatManilaShort(Date.parse(q.from))} – {formatManilaShort(Date.parse(q.to))} ·{' '}
      {q.bucketSeconds >= 60 ? `${q.bucketSeconds / 60} min` : `${q.bucketSeconds} s`} {q.aggregation.toLowerCase()}
      {' · '}
      <span className="tnum">{(result.meta.durationMs / 1000).toFixed(1)} s</span>
      {offset !== null && Math.abs(offset) > 30 && (
        <span className="text-warning"> · Timebase clock {offset < 0 ? '−' : '+'}{formatDuration(offset)}</span>
      )}
    </p>
  )
}

function Running({ since }: { since: number | null }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = since ? Math.max(0, Math.round((now - since) / 1000)) : 0
  return (
    <div className="relative">
      <ChartSkeleton height={460} />
      <div className="absolute inset-0 grid place-items-center">
        <div className="bg-surface border-line shadow-raised flex items-center gap-2 rounded-md border px-3 py-2 text-[13px]">
          <Loader2 className="text-brand size-4 animate-spin" aria-hidden />
          Reading Timebase and computing… <span className="tnum text-ink-soft">{seconds} s</span>
        </div>
      </div>
    </div>
  )
}
