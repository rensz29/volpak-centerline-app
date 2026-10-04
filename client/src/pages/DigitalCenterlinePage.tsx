import {
  AlertOctagon,
  AlertTriangle,
  BellRing,
  CheckCircle2,
  Gauge,
  MinusCircle,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import { AlarmPanel } from '@/components/alarms/AlarmPanel'
import { CenterlineTable } from '@/components/centerline/CenterlineTable'
import { FilterToolbar } from '@/components/centerline/FilterToolbar'
import { ParameterConfigurationModal } from '@/components/centerline/ParameterConfigurationModal'
import { ParameterDetailsDrawer } from '@/components/centerline/ParameterDetailsDrawer'
import { CardGridSkeleton, ListSkeleton, TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SummaryCard } from '@/components/shared/SummaryCard'
import { ALL } from '@/context/ScopeContext'
import { useCenterline, useScope } from '@/hooks/useCenterline'
import { useCenterlineFilters } from '@/hooks/useCenterlineFilters'
import type { CenterlineRow, ParameterStatus } from '@/types'
import { countByStatus } from '@/utils/status'

/**
 * Fixed shift-over-shift deltas. A prototype has no previous shift to compare
 * against, so these are labelled mock context rather than computed figures.
 */
const MOCK_SHIFT_TRENDS: Record<ParameterStatus | 'alarms', number> = {
  normal: 2,
  warning: -1,
  critical: 1,
  'no-data': 0,
  alarms: 1,
}

export function DigitalCenterlinePage() {
  const { loading, centerlineRows, alarmRows, skus } = useCenterline()
  const scope = useScope()

  const [detailsRow, setDetailsRow] = useState<CenterlineRow | null>(null)
  const [configRow, setConfigRow] = useState<CenterlineRow | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)

  const filters = useCenterlineFilters({
    rows: centerlineRows,
    factoryId: scope.factoryId,
    lineId: scope.lineId,
    machineId: scope.machineId,
  })

  // Counts come from the scoped rows, not the filtered ones, so clicking a
  // status card to filter the table does not also change the card's own count.
  const counts = useMemo(
    () => countByStatus(filters.scopedRows.map((row) => row.status)),
    [filters.scopedRows],
  )

  const scopedAlarms = useMemo(
    () =>
      alarmRows.filter((alarm) => {
        if (scope.factoryId !== ALL && alarm.factoryId !== scope.factoryId) return false
        if (scope.lineId !== ALL && alarm.lineId !== scope.lineId) return false
        if (scope.machineId !== ALL && alarm.machineId !== scope.machineId) return false
        return true
      }),
    [alarmRows, scope.factoryId, scope.lineId, scope.machineId],
  )

  const activeAlarms = scopedAlarms.filter((alarm) => alarm.status === 'active').length

  const openDetails = (row: CenterlineRow) => {
    setDetailsRow(row)
    setDrawerOpen(true)
  }

  const openConfiguration = (row: CenterlineRow) => {
    setConfigRow(row)
    setConfigOpen(true)
  }

  const resetEverything = () => {
    filters.reset()
    scope.reset()
  }

  const toggleStatusFilter = (status: ParameterStatus) => {
    filters.setStatus(filters.filters.status === status ? ALL : status)
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Digital Centerline"
        description="Target setpoint, HMI setpoint and actual value compared across every monitored parameter."
        breadcrumbs={[{ label: 'Monitoring' }, { label: 'Digital Centerline' }]}
      />

      {loading ? (
        <CardGridSkeleton />
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
          <SummaryCard
            label="Total Parameters"
            value={filters.scopedRows.length}
            supportingText="Monitored in the current plant selection"
            icon={Gauge}
            tone="brand"
            active={filters.filters.status === ALL}
            onClick={() => filters.setStatus(ALL)}
          />
          <SummaryCard
            label="Normal"
            value={counts.normal}
            supportingText="Inside the warning tolerance band"
            icon={CheckCircle2}
            tone="normal"
            trend={MOCK_SHIFT_TRENDS.normal}
            active={filters.filters.status === 'normal'}
            onClick={() => toggleStatusFilter('normal')}
          />
          <SummaryCard
            label="Warning"
            value={counts.warning}
            supportingText="Drifting beyond the warning band"
            icon={AlertTriangle}
            tone="warning"
            trend={MOCK_SHIFT_TRENDS.warning}
            invertTrendColor
            active={filters.filters.status === 'warning'}
            onClick={() => toggleStatusFilter('warning')}
          />
          <SummaryCard
            label="Critical"
            value={counts.critical}
            supportingText="Outside the critical tolerance band"
            icon={AlertOctagon}
            tone="critical"
            trend={MOCK_SHIFT_TRENDS.critical}
            invertTrendColor
            active={filters.filters.status === 'critical'}
            onClick={() => toggleStatusFilter('critical')}
          />
          <SummaryCard
            label="No Data"
            value={counts['no-data']}
            supportingText="Sensor offline or not reporting"
            icon={MinusCircle}
            tone="nodata"
            trend={MOCK_SHIFT_TRENDS['no-data']}
            invertTrendColor
            active={filters.filters.status === 'no-data'}
            onClick={() => toggleStatusFilter('no-data')}
          />
          <SummaryCard
            label="Active Alarms"
            value={activeAlarms}
            supportingText="Awaiting acknowledgement"
            icon={BellRing}
            tone={activeAlarms > 0 ? 'critical' : 'normal'}
            trend={MOCK_SHIFT_TRENDS.alarms}
            invertTrendColor
          />
        </div>
      )}

      <FilterToolbar filters={filters} skus={skus} onResetAll={resetEverything} />

      {loading ? (
        <div className="bg-surface border-line shadow-card overflow-hidden rounded-lg border">
          <TableSkeleton rows={10} columns={8} />
        </div>
      ) : (
        <CenterlineTable
          rows={filters.rows}
          search={filters.filters.search}
          onRowClick={openDetails}
          onConfigure={openConfiguration}
          onResetFilters={resetEverything}
          hasActiveFilters={filters.activeFilterCount > 0}
        />
      )}

      {loading ? <ListSkeleton rows={2} /> : <AlarmPanel alarms={scopedAlarms} />}

      <ParameterDetailsDrawer
        row={detailsRow}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onEditConfiguration={(row) => {
          setDrawerOpen(false)
          openConfiguration(row)
        }}
      />

      <ParameterConfigurationModal
        row={configRow}
        open={configOpen}
        onOpenChange={setConfigOpen}
      />
    </div>
  )
}
