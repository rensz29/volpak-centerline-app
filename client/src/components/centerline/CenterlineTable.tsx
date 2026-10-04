import { Download, Eye, MoreHorizontal, SearchX, Settings2, X } from 'lucide-react'
import { useMemo } from 'react'

import {
  ActualValueCell,
  DeviationCell,
  HmiSetpointCell,
  ToleranceCell,
} from '@/components/centerline/cells'
import {
  ColumnVisibilityMenu,
  DataTablePagination,
  SortableHead,
} from '@/components/shared/DataTableParts'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useDataTable, type DataTableColumn } from '@/hooks/useDataTable'
import type { CenterlineRow } from '@/types'
import { CATEGORY_LABELS } from '@/types'
import { downloadCsv, timestampedFilename, type CsvColumn } from '@/utils/csv'
import { formatNumber, formatRelativeTime, formatTimestamp } from '@/utils/format'

type ColumnKey =
  | 'status'
  | 'parameter'
  | 'category'
  | 'unit'
  | 'target'
  | 'hmi'
  | 'actual'
  | 'deviation'
  | 'tolerance'
  | 'sku'
  | 'machine'
  | 'updated'
  | 'actions'

interface CenterlineTableProps {
  rows: readonly CenterlineRow[]
  /** Driven by the filter toolbar, which owns the search field. */
  search: string
  onRowClick: (row: CenterlineRow) => void
  onConfigure: (row: CenterlineRow) => void
  onResetFilters: () => void
  hasActiveFilters: boolean
}

export function CenterlineTable({
  rows,
  search,
  onRowClick,
  onConfigure,
  onResetFilters,
  hasActiveFilters,
}: CenterlineTableProps) {
  const columns = useMemo<ReadonlyArray<DataTableColumn<CenterlineRow, ColumnKey>>>(
    () => [
      {
        key: 'status',
        header: 'Status',
        alwaysVisible: true,
        sortValue: (row) =>
          ({ critical: 0, warning: 1, 'no-data': 2, normal: 3 })[row.status],
      },
      {
        key: 'parameter',
        header: 'Parameter',
        alwaysVisible: true,
        sortValue: (row) => row.parameter.name,
        searchValue: (row) => row.parameter.name,
      },
      {
        key: 'category',
        header: 'Category',
        sortValue: (row) => CATEGORY_LABELS[row.parameter.category],
        searchValue: (row) => CATEGORY_LABELS[row.parameter.category],
      },
      { key: 'unit', header: 'Unit', sortValue: (row) => row.parameter.unit },
      {
        key: 'target',
        header: 'Target Setpoint',
        sortValue: (row) => row.reading.targetSetpoint,
      },
      {
        key: 'hmi',
        header: 'HMI Setpoint',
        sortValue: (row) => row.reading.hmiSetpoint,
      },
      {
        key: 'actual',
        header: 'Actual Value',
        sortValue: (row) => row.reading.actualValue,
      },
      {
        key: 'deviation',
        header: 'Deviation',
        sortValue: (row) => row.deviationPct,
      },
      {
        key: 'tolerance',
        header: 'Tolerance',
        sortValue: (row) => row.parameter.warningTolerancePct,
      },
      {
        key: 'sku',
        header: 'SKU',
        sortValue: (row) => row.skuCode,
        searchValue: (row) => `${row.skuCode} ${row.skuName}`,
      },
      {
        key: 'machine',
        header: 'Machine',
        sortValue: (row) => row.machineName,
        searchValue: (row) => `${row.machineName} ${row.lineName} ${row.factoryName}`,
      },
      {
        key: 'updated',
        header: 'Last Updated',
        sortValue: (row) => row.reading.updatedAt,
      },
      { key: 'actions', header: 'Actions', alwaysVisible: true },
    ],
    [],
  )

  const table = useDataTable<CenterlineRow, ColumnKey>({
    data: rows,
    columns,
    getRowId: (row) => row.id,
    initialSort: { key: 'status', direction: 'asc' },
    initialPageSize: 10,
    search,
  })

  const show = table.isColumnVisible
  const selectedRows = rows.filter((row) => table.selectedIds.has(row.id))

  const exportSelected = () => {
    const target = selectedRows.length > 0 ? selectedRows : table.allFilteredRows
    downloadCsv(timestampedFilename('digital-centerline'), target, CSV_COLUMNS)
  }

  return (
    <div className="bg-surface border-line shadow-card flex flex-col overflow-hidden rounded-lg border">
      {/* Selection bar replaces the toolbar when rows are checked. */}
      {table.selectedIds.size > 0 ? (
        <div className="border-line bg-brand-surface flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2.5">
          <p className="text-brand text-[13px] font-medium">
            <span className="tnum">{table.selectedIds.size}</span>{' '}
            {table.selectedIds.size === 1 ? 'parameter' : 'parameters'} selected
          </p>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={exportSelected} className="gap-1.5">
              <Download className="size-3.5" aria-hidden />
              Export selection
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={table.clearSelection}
              className="gap-1.5"
            >
              <X className="size-3.5" aria-hidden />
              Clear
            </Button>
          </div>
        </div>
      ) : (
        <div className="border-line flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2.5">
          <p className="text-ink-soft text-[13px]">
            Showing <span className="tnum text-ink font-medium">{table.totalRows}</span> of{' '}
            <span className="tnum">{rows.length}</span> parameters
          </p>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={exportSelected} className="gap-1.5">
              <Download className="size-3.5" aria-hidden />
              Export CSV
            </Button>
            <ColumnVisibilityMenu
              columns={columns}
              isVisible={table.isColumnVisible}
              onToggle={table.toggleColumn}
              onReset={table.resetColumns}
            />
          </div>
        </div>
      )}

      {table.totalRows === 0 ? (
        <EmptyState
          icon={SearchX}
          title="No parameters match these filters"
          description="No centerline parameter matches the current plant scope and filter combination. Widen the selection or reset the filters to see all readings."
          action={
            hasActiveFilters ? (
              <Button variant="outline" size="sm" onClick={onResetFilters}>
                Reset filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          {/* Horizontal scroll is confined here, so the page itself never scrolls sideways. */}
          <div className="max-h-[680px] min-w-0 overflow-auto">
            <Table>
              <TableHeader className="sticky top-0 z-10">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-10 px-3">
                    <Checkbox
                      checked={
                        table.allOnPageSelected
                          ? true
                          : table.someOnPageSelected
                            ? 'indeterminate'
                            : false
                      }
                      onCheckedChange={table.toggleAllOnPage}
                      aria-label="Select all rows on this page"
                    />
                  </TableHead>

                  {show('status') && (
                    <SortableHead
                      columnKey="status"
                      label="Status"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      className="w-[120px]"
                    />
                  )}
                  {show('parameter') && (
                    <SortableHead
                      columnKey="parameter"
                      label="Parameter"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      className="min-w-[190px]"
                    />
                  )}
                  {show('category') && (
                    <SortableHead
                      columnKey="category"
                      label="Category"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                    />
                  )}
                  {show('unit') && (
                    <SortableHead
                      columnKey="unit"
                      label="Unit"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                    />
                  )}
                  {show('target') && (
                    <SortableHead
                      columnKey="target"
                      label="Target"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      align="right"
                    />
                  )}
                  {show('hmi') && (
                    <SortableHead
                      columnKey="hmi"
                      label="HMI"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      align="right"
                    />
                  )}
                  {show('actual') && (
                    <SortableHead
                      columnKey="actual"
                      label="Actual"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      align="right"
                    />
                  )}
                  {show('deviation') && (
                    <SortableHead
                      columnKey="deviation"
                      label="Deviation"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      align="right"
                    />
                  )}
                  {show('tolerance') && (
                    <SortableHead
                      columnKey="tolerance"
                      label="Tolerance"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      align="right"
                    />
                  )}
                  {show('sku') && (
                    <SortableHead
                      columnKey="sku"
                      label="SKU"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                    />
                  )}
                  {show('machine') && (
                    <SortableHead
                      columnKey="machine"
                      label="Machine"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                    />
                  )}
                  {show('updated') && (
                    <SortableHead
                      columnKey="updated"
                      label="Last Updated"
                      sort={table.sort}
                      onToggle={table.toggleSort}
                      align="right"
                    />
                  )}
                  <TableHead className="w-16 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>

              <TableBody>
                {table.rows.map((row) => {
                  const selected = table.isSelected(row)
                  return (
                    <TableRow
                      key={row.id}
                      data-state={selected ? 'selected' : undefined}
                      onClick={() => onRowClick(row)}
                      className="group cursor-pointer"
                    >
                      <TableCell
                        className="px-3"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <Checkbox
                          checked={selected}
                          onCheckedChange={() => table.toggleRow(row)}
                          aria-label={`Select ${row.parameter.name} on ${row.machineName}`}
                        />
                      </TableCell>

                      {show('status') && (
                        <TableCell>
                          <StatusBadge status={row.status} />
                        </TableCell>
                      )}
                      {show('parameter') && (
                        <TableCell className="font-medium">
                          <span className="group-hover:text-brand transition-colors">
                            {row.parameter.name}
                          </span>
                        </TableCell>
                      )}
                      {show('category') && (
                        <TableCell className="text-ink-soft">
                          {CATEGORY_LABELS[row.parameter.category]}
                        </TableCell>
                      )}
                      {show('unit') && (
                        <TableCell className="text-ink-soft">{row.parameter.unit}</TableCell>
                      )}
                      {show('target') && (
                        <TableCell className="tnum text-ink-soft text-right">
                          {formatNumber(row.reading.targetSetpoint, row.parameter.decimals)}
                        </TableCell>
                      )}
                      {show('hmi') && (
                        <TableCell className="text-right">
                          <HmiSetpointCell row={row} />
                        </TableCell>
                      )}
                      {show('actual') && (
                        <TableCell className="text-right">
                          <ActualValueCell row={row} />
                        </TableCell>
                      )}
                      {show('deviation') && (
                        <TableCell className="text-right">
                          <DeviationCell row={row} />
                        </TableCell>
                      )}
                      {show('tolerance') && (
                        <TableCell className="text-right">
                          <ToleranceCell row={row} />
                        </TableCell>
                      )}
                      {show('sku') && (
                        <TableCell className="tnum text-ink-soft">{row.skuCode}</TableCell>
                      )}
                      {show('machine') && (
                        <TableCell>
                          <span className="text-ink block">{row.machineName}</span>
                          <span className="text-ink-muted block text-[11px]">
                            {row.lineName}
                          </span>
                        </TableCell>
                      )}
                      {show('updated') && (
                        <TableCell className="text-right">
                          <span className="text-ink-soft tnum block">
                            {formatRelativeTime(row.reading.updatedAt)}
                          </span>
                          <span className="text-ink-muted tnum block text-[11px]">
                            {formatTimestamp(row.reading.updatedAt).split(', ')[1]}
                          </span>
                        </TableCell>
                      )}

                      <TableCell
                        className="text-right"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Actions for ${row.parameter.name}`}
                            >
                              <MoreHorizontal className="size-4" aria-hidden />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => onRowClick(row)}>
                              <Eye aria-hidden />
                              View details
                            </DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => onConfigure(row)}>
                              <Settings2 aria-hidden />
                              Edit configuration
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  )
                })}
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
            itemLabel="parameters"
          />
        </>
      )}
    </div>
  )
}

const CSV_COLUMNS: ReadonlyArray<CsvColumn<CenterlineRow>> = [
  { header: 'Status', value: (row) => row.status },
  { header: 'Parameter', value: (row) => row.parameter.name },
  { header: 'Category', value: (row) => CATEGORY_LABELS[row.parameter.category] },
  { header: 'Unit', value: (row) => row.parameter.unit },
  { header: 'Target Setpoint', value: (row) => row.reading.targetSetpoint },
  { header: 'HMI Setpoint', value: (row) => row.reading.hmiSetpoint },
  { header: 'Actual Value', value: (row) => row.reading.actualValue },
  // Rounded to the parameter's own precision: `5.7 - 5.0` is 0.7000000000000002
  // in binary floating point, and that must not reach a spreadsheet.
  {
    header: 'Deviation',
    value: (row) => row.deviation?.toFixed(row.parameter.decimals) ?? null,
  },
  { header: 'Deviation %', value: (row) => row.deviationPct?.toFixed(2) ?? null },
  { header: 'Warning Tolerance %', value: (row) => row.parameter.warningTolerancePct },
  { header: 'Critical Tolerance %', value: (row) => row.parameter.criticalTolerancePct },
  { header: 'SKU', value: (row) => row.skuCode },
  { header: 'Machine', value: (row) => row.machineName },
  { header: 'Line', value: (row) => row.lineName },
  { header: 'Factory', value: (row) => row.factoryName },
  { header: 'Last Updated', value: (row) => row.reading.updatedAt },
  { header: 'Updated By', value: (row) => row.reading.updatedBy },
]
