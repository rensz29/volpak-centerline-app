import { Download, Eye, History, RotateCcw, Search, SearchX, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { AlarmSeverityBadge, AlarmStatusBadge } from '@/components/alarms/AlarmBadges'
import { AlarmDetailsDialog } from '@/components/alarms/AlarmDetailsDialog'
import { AlarmActionDialog, useAlarmActions } from '@/components/alarms/useAlarmActions'
import {
  ColumnVisibilityMenu,
  DataTablePagination,
  SortableHead,
} from '@/components/shared/DataTableParts'
import { EmptyState } from '@/components/shared/EmptyState'
import { PageHeader } from '@/components/shared/PageHeader'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ALL } from '@/context/ScopeContext'
import { useDataTable, type DataTableColumn } from '@/hooks/useDataTable'
import { useCenterline } from '@/hooks/useCenterline'
import {
  ALARM_SEVERITIES,
  ALARM_SEVERITY_LABELS,
  ALARM_STATUSES,
  ALARM_STATUS_LABELS,
  type AlarmRow,
  type AlarmSeverity,
  type AlarmStatus,
} from '@/types'
import { downloadCsv, timestampedFilename, type CsvColumn } from '@/utils/csv'
import { NO_VALUE, formatDeviationPct, formatNumber, formatTimestamp } from '@/utils/format'

type ColumnKey =
  | 'reference'
  | 'raisedAt'
  | 'severity'
  | 'parameter'
  | 'machine'
  | 'sku'
  | 'target'
  | 'hmi'
  | 'actual'
  | 'deviation'
  | 'status'
  | 'resolvedBy'
  | 'actions'

export function AlarmHistoryPage() {
  const { loading, alarmRows } = useCenterline()
  const actions = useAlarmActions()

  const [severity, setSeverity] = useState<AlarmSeverity | typeof ALL>(ALL)
  const [status, setStatus] = useState<AlarmStatus | typeof ALL>(ALL)
  const [search, setSearch] = useState('')
  const [detailsAlarm, setDetailsAlarm] = useState<AlarmRow | null>(null)

  const scoped = useMemo(
    () =>
      alarmRows.filter((alarm) => {
        if (severity !== ALL && alarm.severity !== severity) return false
        if (status !== ALL && alarm.status !== status) return false
        return true
      }),
    [alarmRows, severity, status],
  )

  const columns = useMemo<ReadonlyArray<DataTableColumn<AlarmRow, ColumnKey>>>(
    () => [
      {
        key: 'reference',
        header: 'Reference',
        alwaysVisible: true,
        sortValue: (row) => row.reference,
        searchValue: (row) => row.reference,
      },
      { key: 'raisedAt', header: 'Raised', sortValue: (row) => row.raisedAt },
      {
        key: 'severity',
        header: 'Severity',
        sortValue: (row) => ({ critical: 0, warning: 1, info: 2 })[row.severity],
      },
      {
        key: 'parameter',
        header: 'Parameter',
        alwaysVisible: true,
        sortValue: (row) => row.parameterName,
        searchValue: (row) => `${row.parameterName} ${row.message}`,
      },
      {
        key: 'machine',
        header: 'Machine',
        sortValue: (row) => row.machineName,
        searchValue: (row) => `${row.machineName} ${row.lineName}`,
      },
      { key: 'sku', header: 'SKU', sortValue: (row) => row.skuCode, searchValue: (row) => row.skuCode },
      { key: 'target', header: 'Target', sortValue: (row) => row.targetValue },
      { key: 'hmi', header: 'HMI', sortValue: (row) => row.hmiValue },
      { key: 'actual', header: 'Actual', sortValue: (row) => row.actualValue },
      { key: 'deviation', header: 'Deviation', sortValue: (row) => row.deviationPct },
      {
        key: 'status',
        header: 'Status',
        alwaysVisible: true,
        sortValue: (row) => ({ active: 0, acknowledged: 1, resolved: 2 })[row.status],
      },
      {
        key: 'resolvedBy',
        header: 'Resolved by',
        sortValue: (row) => row.resolvedBy,
        defaultHidden: true,
      },
      { key: 'actions', header: 'Actions', alwaysVisible: true },
    ],
    [],
  )

  const table = useDataTable<AlarmRow, ColumnKey>({
    data: scoped,
    columns,
    getRowId: (row) => row.id,
    initialSort: { key: 'raisedAt', direction: 'desc' },
    initialPageSize: 10,
    search,
  })

  const show = table.isColumnVisible
  const activeFilters = (severity !== ALL ? 1 : 0) + (status !== ALL ? 1 : 0) + (search.trim() !== '' ? 1 : 0)

  const reset = () => {
    setSeverity(ALL)
    setStatus(ALL)
    setSearch('')
  }

  const exportCsv = () => {
    downloadCsv(timestampedFilename('alarm-history'), table.allFilteredRows, CSV_COLUMNS)
    toast.success('Export started', {
      description: `${table.allFilteredRows.length} alarms written to CSV.`,
    })
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Alarm History"
        description="Complete record of every alarm raised against the centerline, including resolved entries."
        breadcrumbs={[{ label: 'Alarms' }, { label: 'Alarm History' }]}
      />

      <div className="bg-surface border-line shadow-card flex flex-col overflow-hidden rounded-lg border">
        <div className="border-line flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={severity}
              onValueChange={(value) => setSeverity(value as AlarmSeverity | typeof ALL)}
            >
              <SelectTrigger size="sm" aria-label="Filter by severity" className="w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All severities</SelectItem>
                {ALARM_SEVERITIES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {ALARM_SEVERITY_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={status}
              onValueChange={(value) => setStatus(value as AlarmStatus | typeof ALL)}
            >
              <SelectTrigger size="sm" aria-label="Filter by status" className="w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All statuses</SelectItem>
                {ALARM_STATUSES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {ALARM_STATUS_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="relative w-full sm:w-60">
              <Search
                className="text-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search alarms…"
                aria-label="Search alarm history"
                className="h-8 pr-8 pl-9 text-[13px]"
              />
              {search !== '' && (
                <button
                  type="button"
                  onClick={() => setSearch('')}
                  className="text-ink-muted hover:text-ink absolute top-1/2 right-2 grid size-5 -translate-y-1/2 place-items-center rounded"
                  aria-label="Clear search"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </div>

            {activeFilters > 0 && (
              <Button variant="ghost" size="sm" onClick={reset} className="gap-1.5">
                <RotateCcw className="size-3.5" aria-hidden />
                Reset
              </Button>
            )}
          </div>

          <div className="flex items-center gap-2">
            <ColumnVisibilityMenu
              columns={columns}
              isVisible={table.isColumnVisible}
              onToggle={table.toggleColumn}
              onReset={table.resetColumns}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={exportCsv}
              disabled={table.totalRows === 0}
              className="gap-1.5"
            >
              <Download className="size-3.5" aria-hidden />
              Export CSV
            </Button>
          </div>
        </div>

        {loading ? (
          <TableSkeleton rows={10} columns={9} />
        ) : table.totalRows === 0 ? (
          <EmptyState
            icon={activeFilters > 0 ? SearchX : History}
            title={activeFilters > 0 ? 'No alarms match' : 'No alarm history'}
            description={
              activeFilters > 0
                ? 'No alarm matches the current filters. Reset them to see the full history.'
                : 'No alarms have been raised against this dataset.'
            }
            action={
              activeFilters > 0 ? (
                <Button variant="outline" size="sm" onClick={reset}>
                  Reset filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="max-h-[680px] min-w-0 overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 z-10">
                  <TableRow className="hover:bg-transparent">
                    {show('reference') && (
                      <SortableHead columnKey="reference" label="Reference" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    {show('raisedAt') && (
                      <SortableHead columnKey="raisedAt" label="Raised" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    {show('severity') && (
                      <SortableHead columnKey="severity" label="Severity" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    {show('parameter') && (
                      <SortableHead columnKey="parameter" label="Parameter" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    {show('machine') && (
                      <SortableHead columnKey="machine" label="Machine" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    {show('sku') && (
                      <SortableHead columnKey="sku" label="SKU" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    {show('target') && (
                      <SortableHead columnKey="target" label="Target" sort={table.sort} onToggle={table.toggleSort} align="right" />
                    )}
                    {show('hmi') && (
                      <SortableHead columnKey="hmi" label="HMI" sort={table.sort} onToggle={table.toggleSort} align="right" />
                    )}
                    {show('actual') && (
                      <SortableHead columnKey="actual" label="Actual" sort={table.sort} onToggle={table.toggleSort} align="right" />
                    )}
                    {show('deviation') && (
                      <SortableHead columnKey="deviation" label="Deviation" sort={table.sort} onToggle={table.toggleSort} align="right" />
                    )}
                    {show('status') && (
                      <SortableHead columnKey="status" label="Status" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    {show('resolvedBy') && (
                      <SortableHead columnKey="resolvedBy" label="Resolved by" sort={table.sort} onToggle={table.toggleSort} />
                    )}
                    <TableHead className="w-16 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {table.rows.map((alarm) => (
                    <TableRow
                      key={alarm.id}
                      className="cursor-pointer"
                      onClick={() => setDetailsAlarm(alarm)}
                    >
                      {show('reference') && (
                        <TableCell className="tnum font-medium">{alarm.reference}</TableCell>
                      )}
                      {show('raisedAt') && (
                        <TableCell className="tnum text-ink-soft">
                          {formatTimestamp(alarm.raisedAt)}
                        </TableCell>
                      )}
                      {show('severity') && (
                        <TableCell>
                          <AlarmSeverityBadge severity={alarm.severity} />
                        </TableCell>
                      )}
                      {show('parameter') && <TableCell>{alarm.parameterName}</TableCell>}
                      {show('machine') && (
                        <TableCell className="text-ink-soft">{alarm.machineName}</TableCell>
                      )}
                      {show('sku') && (
                        <TableCell className="tnum text-ink-soft">{alarm.skuCode}</TableCell>
                      )}
                      {show('target') && (
                        <TableCell className="tnum text-ink-soft text-right">
                          {formatNumber(alarm.targetValue, alarm.parameterDecimals)}
                        </TableCell>
                      )}
                      {show('hmi') && (
                        <TableCell
                          className={`tnum text-right ${alarm.hmiValue !== alarm.targetValue ? 'text-warning font-medium' : 'text-ink-soft'}`}
                        >
                          {formatNumber(alarm.hmiValue, alarm.parameterDecimals)}
                        </TableCell>
                      )}
                      {show('actual') && (
                        <TableCell className="tnum text-right font-semibold">
                          {alarm.actualValue === null
                            ? NO_VALUE
                            : formatNumber(alarm.actualValue, alarm.parameterDecimals)}
                        </TableCell>
                      )}
                      {show('deviation') && (
                        <TableCell className="tnum text-right">
                          {formatDeviationPct(alarm.deviationPct)}
                        </TableCell>
                      )}
                      {show('status') && (
                        <TableCell>
                          <AlarmStatusBadge status={alarm.status} />
                        </TableCell>
                      )}
                      {show('resolvedBy') && (
                        <TableCell className="text-ink-soft">
                          {alarm.resolvedBy ?? NO_VALUE}
                        </TableCell>
                      )}
                      <TableCell
                        className="text-right"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setDetailsAlarm(alarm)}
                          aria-label={`View ${alarm.reference}`}
                        >
                          <Eye className="size-4" aria-hidden />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <DataTablePagination
              page={table.page}
              pageCount={table.pageCount}
              pageSize={table.pageSize}
              rangeStart={table.rangeStart}
              rangeEnd={table.rangeEnd}
              totalRows={table.totalRows}
              onPageChange={table.setPage}
              onPageSizeChange={table.setPageSize}
              itemLabel="alarms"
            />
          </>
        )}
      </div>

      <AlarmDetailsDialog
        alarm={detailsAlarm}
        open={detailsAlarm !== null}
        onOpenChange={(open) => {
          if (!open) setDetailsAlarm(null)
        }}
        onAcknowledge={(alarm) => {
          setDetailsAlarm(null)
          actions.requestAcknowledge(alarm)
        }}
        onResolve={(alarm) => {
          setDetailsAlarm(null)
          actions.requestResolve(alarm)
        }}
      />

      <AlarmActionDialog actions={actions} />
    </div>
  )
}

const CSV_COLUMNS: ReadonlyArray<CsvColumn<AlarmRow>> = [
  { header: 'Reference', value: (row) => row.reference },
  { header: 'Raised At', value: (row) => row.raisedAt },
  { header: 'Severity', value: (row) => row.severity },
  { header: 'Status', value: (row) => row.status },
  { header: 'Parameter', value: (row) => row.parameterName },
  { header: 'Factory', value: (row) => row.factoryName },
  { header: 'Line', value: (row) => row.lineName },
  { header: 'Machine', value: (row) => row.machineName },
  { header: 'SKU', value: (row) => row.skuCode },
  { header: 'Unit', value: (row) => row.unit },
  { header: 'Target', value: (row) => row.targetValue },
  { header: 'HMI', value: (row) => row.hmiValue },
  { header: 'Actual', value: (row) => row.actualValue },
  { header: 'Deviation', value: (row) => row.deviation },
  { header: 'Deviation %', value: (row) => row.deviationPct?.toFixed(2) ?? null },
  { header: 'Message', value: (row) => row.message },
  { header: 'Acknowledged By', value: (row) => row.acknowledgedBy },
  { header: 'Acknowledged At', value: (row) => row.acknowledgedAt },
  { header: 'Resolved By', value: (row) => row.resolvedBy },
  { header: 'Resolved At', value: (row) => row.resolvedAt },
  { header: 'Resolution Note', value: (row) => row.resolutionNote },
]
