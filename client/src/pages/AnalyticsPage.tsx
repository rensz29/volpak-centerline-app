import {
  ArrowUpDown,
  BellRing,
  Database,
  Gauge,
  GitCompareArrows,
  Maximize2,
  Minimize2,
  Sigma,
  Target,
  Timer,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import {
  AnalyticsFilterBar,
  GroupBySelect,
  type ChartTab,
} from '@/components/analytics/AnalyticsFilterBar'
import { AnalyticsParameterPanel } from '@/components/analytics/AnalyticsParameterPanel'
import { CorrelationInsightCard } from '@/components/analytics/CorrelationInsightCard'
import { CorrelationScatterChart } from '@/components/analytics/CorrelationScatterChart'
import { RawDataTable } from '@/components/analytics/RawDataTable'
import { SetpointComparisonChart } from '@/components/analytics/SetpointComparisonChart'
import { StatisticsCard } from '@/components/analytics/StatisticsCard'
import { ChartSkeleton, TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { ScatterChartIcon } from '@/components/shared/icons'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { WINDOW_START, SESSION_NOW } from '@/data/generate'
import { useCenterline, useScope } from '@/hooks/useCenterline'
import { useAnalyticsSelection } from '@/hooks/useAnalyticsSelection'
import type { ParameterCode, ParameterDefinition } from '@/types'
import { formatNumber, toDateInputValue } from '@/utils/format'
import {
  buildAnalyticsRecords,
  buildScatterPoints,
  computeStatistics,
  describeSpan,
} from '@/utils/selectors'
import { analyseCorrelation } from '@/utils/stats'

const WINDOW = {
  start: toDateInputValue(new Date(WINDOW_START).toISOString()),
  end: toDateInputValue(new Date(SESSION_NOW).toISOString()),
}

export function AnalyticsPage() {
  const { loading, parameters, samples, factories, lines, machines, skus, lookups } =
    useCenterline()
  const scope = useScope()

  const [chartTab, setChartTab] = useState<ChartTab>('scatter')
  const [panelCollapsed, setPanelCollapsed] = useState(false)

  const analytics = useAnalyticsSelection({
    samples,
    factoryId: scope.factoryId,
    lineId: scope.lineId,
    machineId: scope.machineId,
    windowStart: WINDOW.start,
    windowEnd: WINDOW.end,
  })

  const { xAxis, yAxis, groupBy } = analytics.selection

  const xParameter = findParameter(parameters, xAxis)
  const yParameter = findParameter(parameters, yAxis)

  /** The paired observations that actually enter the correlation. Everything
   *  about the scatter tab is derived from this one array. */
  const scatterPoints = useMemo(() => {
    if (!xParameter || !yParameter) return []
    return buildScatterPoints(
      analytics.filteredSamples,
      xParameter.code,
      yParameter.code,
      lookups,
    )
  }, [analytics.filteredSamples, xParameter, yParameter, lookups])

  const correlation = useMemo(
    () =>
      analyseCorrelation(
        scatterPoints.map((p) => p.x),
        scatterPoints.map((p) => p.y),
      ),
    [scatterPoints],
  )

  // Measured on the paired points, not the filtered samples: a machine without
  // a sensor for one of the two parameters contributes nothing to the
  // correlation, so warning about it would be a false alarm.
  const span = useMemo(() => describeSpan(scatterPoints), [scatterPoints])

  const statistics = useMemo(() => {
    if (!yParameter || !xParameter) return null
    return computeStatistics(
      analytics.filteredSamples,
      yParameter.code,
      xParameter.code,
      yParameter,
    )
  }, [analytics.filteredSamples, yParameter, xParameter])

  const records = useMemo(() => {
    const codes = [...new Set<ParameterCode>([xAxis, yAxis])]
    return buildAnalyticsRecords(analytics.filteredSamples, codes, lookups)
  }, [analytics.filteredSamples, xAxis, yAxis, lookups])

  const resetAll = () => {
    analytics.resetFilters()
    scope.reset()
  }

  if (!xParameter || !yParameter) return null

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Analytics & Correlation"
        description="Correlate any two process parameters and compare actual readings against both setpoints over time."
        breadcrumbs={[{ label: 'Monitoring' }, { label: 'Analytics & Correlation' }]}
      />

      <AnalyticsFilterBar
        analytics={analytics}
        scope={scope}
        factories={factories}
        lines={lines}
        machines={machines}
        skus={skus}
        chartTab={chartTab}
        onChartTabChange={setChartTab}
        onResetAll={resetAll}
      />

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <AnalyticsParameterPanel
          parameters={parameters}
          analytics={analytics}
          collapsed={panelCollapsed}
          onToggleCollapsed={() => setPanelCollapsed(!panelCollapsed)}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <Tabs value={chartTab} onValueChange={(value) => setChartTab(value as ChartTab)}>
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

                <div className="flex items-center gap-2">
                  {chartTab === 'scatter' && (
                    <GroupBySelect value={groupBy} onChange={analytics.setGroupBy} />
                  )}
                  <button
                    type="button"
                    onClick={() => setPanelCollapsed(!panelCollapsed)}
                    className="text-ink-soft hover:bg-surface-muted hover:text-ink focus-visible:ring-brand-ring hidden size-8 place-items-center rounded-md border border-transparent transition-colors focus-visible:ring-2 focus-visible:outline-none xl:grid"
                    aria-label={
                      panelCollapsed ? 'Expand parameter panel' : 'Collapse parameter panel'
                    }
                  >
                    {panelCollapsed ? (
                      <Minimize2 className="size-4" aria-hidden />
                    ) : (
                      <Maximize2 className="size-4" aria-hidden />
                    )}
                  </button>
                </div>
              </div>

              <div className="p-4">
                {loading ? (
                  <ChartSkeleton height={420} />
                ) : (
                  <>
                    <TabsContent value="scatter">
                      <p className="text-ink-soft mb-3 text-[13px]">
                        <span className="text-ink font-medium">{yParameter.name}</span>{' '}
                        against{' '}
                        <span className="text-ink font-medium">{xParameter.name}</span> ·{' '}
                        <span className="tnum">{correlation.sampleCount}</span> paired
                        samples
                      </p>
                      <CorrelationScatterChart
                        points={scatterPoints}
                        xParameter={xParameter}
                        yParameter={yParameter}
                        groupBy={groupBy}
                        correlation={correlation}
                      />
                    </TabsContent>

                    <TabsContent value="trend">
                      <p className="text-ink-soft mb-3 text-[13px]">
                        <span className="text-ink font-medium">{yParameter.name}</span> —
                        actual reading against the HMI and target setpoints
                        {analytics.spansMultipleMachines && ' (averaged across machines)'}
                      </p>
                      <SetpointComparisonChart
                        samples={analytics.filteredSamples}
                        parameter={yParameter}
                      />
                    </TabsContent>
                  </>
                )}
              </div>
            </div>
          </Tabs>
        </div>

        {/* Insights column: beside the workspace on wide screens, below it otherwise. */}
        <div className="flex w-full shrink-0 flex-col gap-4 xl:w-[320px]">
          <CorrelationInsightCard
            correlation={correlation}
            xParameter={xParameter}
            yParameter={yParameter}
            spansMultipleSkus={span.skuCount > 1}
            spansMultipleMachines={span.machineCount > 1}
          />

          {statistics && (
            <section className="bg-surface border-line shadow-card overflow-hidden rounded-lg border">
              <div className="border-line border-b px-4 py-3">
                <h2 className="text-ink text-[15px] font-semibold">Summary statistics</h2>
                <p className="text-ink-soft mt-0.5 text-[12px]">
                  Computed over {yParameter.name} in the current selection
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 p-3">
                <StatisticsCard
                  label="Total records"
                  value={String(statistics.totalRecords)}
                  icon={Database}
                />
                <StatisticsCard
                  label="Average value"
                  value={`${formatNumber(statistics.average, yParameter.decimals)} ${yParameter.unit}`}
                  icon={Sigma}
                />
                <StatisticsCard
                  label="Minimum"
                  value={`${formatNumber(statistics.minimum, yParameter.decimals)}`}
                  icon={ArrowUpDown}
                />
                <StatisticsCard
                  label="Maximum"
                  value={`${formatNumber(statistics.maximum, yParameter.decimals)}`}
                  icon={ArrowUpDown}
                />
                <StatisticsCard
                  label="Std deviation"
                  value={formatNumber(statistics.standardDeviation, 3)}
                  icon={Gauge}
                />
                <StatisticsCard
                  label="Correlation (r)"
                  value={
                    statistics.correlationCoefficient === null
                      ? '—'
                      : statistics.correlationCoefficient.toFixed(3)
                  }
                  icon={GitCompareArrows}
                />
                <StatisticsCard
                  label="Avg actual vs HMI"
                  value={`${statistics.averageActualVsHmiDeviation >= 0 ? '+' : '−'}${formatNumber(Math.abs(statistics.averageActualVsHmiDeviation), yParameter.decimals)}`}
                  hint={`Mean gap from the panel setpoint, in ${yParameter.unit}`}
                  icon={Target}
                  tone={
                    Math.abs(statistics.averageActualVsHmiDeviation) >
                    (yParameter.warningTolerancePct / 100) *
                      Math.max(statistics.average, 1)
                      ? 'warning'
                      : 'default'
                  }
                />
                <StatisticsCard
                  label="Alarm count"
                  value={String(statistics.alarmCount)}
                  hint="Readings outside the warning band"
                  icon={BellRing}
                  tone={statistics.alarmCount > 0 ? 'warning' : 'normal'}
                />
                <StatisticsCard
                  label="Time within target"
                  value={`${formatNumber(statistics.timeWithinTargetPct, 1)}%`}
                  hint="Share of readings inside tolerance"
                  icon={Timer}
                  tone={
                    statistics.timeWithinTargetPct >= 90
                      ? 'normal'
                      : statistics.timeWithinTargetPct >= 70
                        ? 'warning'
                        : 'critical'
                  }
                />
              </div>
            </section>
          )}
        </div>
      </div>

      {loading ? (
        <div className="bg-surface border-line shadow-card overflow-hidden rounded-lg border">
          <TableSkeleton rows={8} columns={9} />
        </div>
      ) : (
        <RawDataTable records={records} />
      )}
    </div>
  )
}

function findParameter(
  parameters: readonly ParameterDefinition[],
  code: ParameterCode,
): ParameterDefinition | undefined {
  return parameters.find((parameter) => parameter.code === code)
}
