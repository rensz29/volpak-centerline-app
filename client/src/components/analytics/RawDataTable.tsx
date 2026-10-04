import { Download, Search, SearchX, X } from 'lucide-react'
import { useMemo } from 'react'
import { toast } from 'sonner'

import {
  ColumnVisibilityMenu,
  DataTablePagination,
  SortableHead,
} from '@/components/shared/DataTableParts'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useDataTable, type DataTableColumn } from '@/hooks/useDataTable'
import type { AnalyticsRecord } from '@/types'
import { downloadCsv, timestampedFilename, type CsvColumn } from '@/utils/csv'
import { NO_VALUE, formatNumber, formatTimestamp } from '@/utils/format'

type ColumnKey =
  | 'timestamp'
  | 'factory'
  | 'line'
  | 'machine'
  | 'sku'
  | 'parameter'
  | 'target'
  | 'hmi'
  | 'actual'
  | 'deviation'
  | 'status'

export function RawDataTable({ records }: { records: readonly AnalyticsRecord[] }) {
  const columns = useMemo<ReadonlyArray<DataTableColumn<AnalyticsRecord, ColumnKey>>>(
    () => [
      {
        key: 'timestamp',
        header: 'Timestamp',
        alwaysVisible: true,
        sortValue: (row) => row.timestamp,
        searchValue: (row) => formatTimestamp(row.timestamp),
      },
      {
        key: 'factory',
        header: 'Factory',
        sortValue: (row) => row.factoryName,
        searchValue: (row) => row.factoryName,
        defaultHidden: true,
      },
      { key: 'line', header: 'Line', sortValue: (row) => row.lineName, searchValue: (row) => row.lineName },
      {
        key: 'machine',
        header: 'Machine',
        sortValue: (row) => row.machineName,
        searchValue: (row) => row.machineName,
      },
      { key: 'sku', header: 'SKU', sortValue: (row) => row.skuCode, searchValue: (row) => row.skuCode },
      {
        key: 'parameter',
        header: 'Parameter',
        alwaysVisible: true,
        sortValue: (row) => row.parameterName,
        searchValue: (row) => row.parameterName,
      },
      { key: 'target', header: 'Target', sortValue: (row) => row.target },
      { key: 'hmi', header: 'HMI', sortValue: (row) => row.hmi },
      { key: 'actual', header: 'Actual', sortValue: (row) => row.actual },
      { key: 'deviation', header: 'Deviation', sortValue: (row) => row.deviation },
      {
        key: 'status',
        header: 'Status',
        alwaysVisible: true,
        sortValue: (row) => ({ critical: 0, warning: 1, 'no-data': 2, normal: 3 })[row.status],
      },
    ],
    [],
  )

  const table = useDataTable<AnalyticsRecord, ColumnKey>({
    data: records,
    columns,
    getRowId: (row) => row.id,
    initialSort: { key: 'timestamp', direction: 'desc' },
    initialPageSize: 25,
  })

  const show = table.isColumnVisible

  const exportCsv = () => {
    downloadCsv(timestampedFilename('analytics-records'), table.allFilteredRows, CSV_COLUMNS)
    toast.success('Export started', {
      description: `${table.allFilteredRows.length} records written to CSV.`,
    })
  }

  return (
    <div className="bg-surface border-line shadow-card flex flex-col overflow-hidden rounded-lg border">
      <div className="border-line flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-ink text-[15px] font-semibold">Filtered records</h2>
          <p className="text-ink-soft mt-0.5 text-[12px]">
            Raw readings behind the charts above ·{' '}
            <span className="tnum">{table.totalRows}</span> rows
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-56">
            <Search
              className="text-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
              aria-hidden
            />
            <Input
              value={table.search}
              onChange={(event) => table.setSearch(event.target.value)}
              placeholder="Search records…"
              aria-label="Search records"
              className="h-8 pr-8 pl-9 text-[13px]"
            />
            {table.search !== '' && (
              <button
                type="button"
                onClick={() => table.setSearch('')}
                className="text-ink-muted hover:text-ink absolute top-1/2 right-2 grid size-5 -translate-y-1/2 place-items-center rounded"
                aria-label="Clear record search"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            )}
          </div>

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

      {table.totalRows === 0 ? (
        <EmptyState
          icon={SearchX}
          title="No records to show"
          description="No reading matches the current analytics filters and search term."
          compact
        />
      ) : (
        <>
          <div className="max-h-[560px] min-w-0 overflow-auto">
            <Table>
              <TableHeader className="sticky top-0 z-10">
                <TableRow className="hover:bg-transparent">
                  {show('timestamp') && (
                    <SortableHead columnKey="timestamp" label="Timestamp" sort={table.sort} onToggle={table.toggleSort} />
                  )}
                  {show('factory') && (
                    <SortableHead columnKey="factory" label="Factory" sort={table.sort} onToggle={table.toggleSort} />
                  )}
                  {show('line') && (
                    <SortableHead columnKey="line" label="Line" sort={table.sort} onToggle={table.toggleSort} />
                  )}
                  {show('machine') && (
                    <SortableHead columnKey="machine" label="Machine" sort={table.sort} onToggle={table.toggleSort} />
                  )}
                  {show('sku') && (
                    <SortableHead columnKey="sku" label="SKU" sort={table.sort} onToggle={table.toggleSort} />
                  )}
                  {show('parameter') && (
                    <SortableHead columnKey="parameter" label="Parameter" sort={table.sort} onToggle={table.toggleSort} />
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
                </TableRow>
              </TableHeader>

              <TableBody>
                {table.rows.map((row) => (
                  <TableRow key={row.id}>
                    {show('timestamp') && (
                      <TableCell className="tnum text-ink-soft">
                        {formatTimestamp(row.timestamp)}
                      </TableCell>
                    )}
                    {show('factory') && (
                      <TableCell className="text-ink-soft">{row.factoryName}</TableCell>
                    )}
                    {show('line') && (
                      <TableCell className="text-ink-soft">{row.lineName}</TableCell>
                    )}
                    {show('machine') && <TableCell>{row.machineName}</TableCell>}
                    {show('sku') && (
                      <TableCell className="tnum text-ink-soft">{row.skuCode}</TableCell>
                    )}
                    {show('parameter') && (
                      <TableCell className="font-medium">{row.parameterName}</TableCell>
                    )}
                    {show('target') && (
                      <TableCell className="tnum text-ink-soft text-right">
                        {formatNumber(row.target, row.decimals)}
                      </TableCell>
                    )}
                    {show('hmi') && (
                      <TableCell className="tnum text-ink-soft text-right">
                        {formatNumber(row.hmi, row.decimals)}
                      </TableCell>
                    )}
                    {show('actual') && (
                      <TableCell className="tnum text-right font-semibold">
                        {row.actual === null ? (
                          <span className="text-ink-muted font-normal">{NO_VALUE}</span>
                        ) : (
                          formatNumber(row.actual, row.decimals)
                        )}
                      </TableCell>
                    )}
                    {show('deviation') && (
                      <TableCell className="tnum text-ink-soft text-right">
                        {row.deviation === null
                          ? NO_VALUE
                          : `${row.deviation > 0 ? '+' : row.deviation < 0 ? '−' : ''}${formatNumber(Math.abs(row.deviation), row.decimals)}`}
                      </TableCell>
                    )}
                    {show('status') && (
                      <TableCell>
                        <StatusBadge status={row.status} compact />
                      </TableCell>
                    )}
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
            itemLabel="records"
          />
        </>
      )}
    </div>
  )
}

const CSV_COLUMNS: ReadonlyArray<CsvColumn<AnalyticsRecord>> = [
  { header: 'Timestamp', value: (row) => row.timestamp },
  { header: 'Factory', value: (row) => row.factoryName },
  { header: 'Line', value: (row) => row.lineName },
  { header: 'Machine', value: (row) => row.machineName },
  { header: 'SKU', value: (row) => row.skuCode },
  { header: 'Shift', value: (row) => row.shift },
  { header: 'Parameter', value: (row) => row.parameterName },
  { header: 'Unit', value: (row) => row.unit },
  { header: 'Target', value: (row) => row.target },
  { header: 'HMI', value: (row) => row.hmi },
  { header: 'Actual', value: (row) => row.actual },
  { header: 'Deviation', value: (row) => row.deviation?.toFixed(3) ?? null },
  { header: 'Status', value: (row) => row.status },
]
