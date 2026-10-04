import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ChevronsUpDown,
  Columns3,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { TableHead } from '@/components/ui/table'
import type { DataTableColumn, SortState } from '@/hooks/useDataTable'
import { cn } from '@/utils/cn'

interface SortableHeadProps<K extends string> {
  columnKey: K
  label: string
  sort: SortState<K> | null
  onToggle: (key: K) => void
  align?: 'left' | 'right' | 'center'
  className?: string
  sortable?: boolean
}

export function SortableHead<K extends string>({
  columnKey,
  label,
  sort,
  onToggle,
  align = 'left',
  className,
  sortable = true,
}: SortableHeadProps<K>) {
  const active = sort?.key === columnKey
  const Icon = !active ? ChevronsUpDown : sort.direction === 'asc' ? ArrowUp : ArrowDown

  return (
    <TableHead
      className={cn(
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        className,
      )}
      aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      {sortable ? (
        <button
          type="button"
          onClick={() => onToggle(columnKey)}
          className={cn(
            'hover:text-ink focus-visible:ring-brand-ring -mx-1 inline-flex h-8 items-center gap-1.5 rounded px-1 transition-colors focus-visible:ring-2 focus-visible:outline-none',
            align === 'right' && 'flex-row-reverse',
            active && 'text-ink',
          )}
        >
          {label}
          <Icon
            className={cn('size-3 shrink-0', active ? 'text-brand' : 'opacity-40')}
            aria-hidden
          />
        </button>
      ) : (
        label
      )}
    </TableHead>
  )
}

interface ColumnVisibilityMenuProps<T, K extends string> {
  columns: ReadonlyArray<DataTableColumn<T, K>>
  isVisible: (key: K) => boolean
  onToggle: (key: K) => void
  onReset: () => void
}

export function ColumnVisibilityMenu<T, K extends string>({
  columns,
  isVisible,
  onToggle,
  onReset,
}: ColumnVisibilityMenuProps<T, K>) {
  const hiddenCount = columns.filter((column) => !isVisible(column.key)).length

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Columns3 className="size-4" aria-hidden />
          Columns
          {hiddenCount > 0 && (
            <span className="bg-brand-surface text-brand tnum ml-0.5 rounded px-1.5 py-0.5 text-[11px] font-semibold">
              {hiddenCount} hidden
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>Visible columns</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {columns.map((column) => (
          <DropdownMenuCheckboxItem
            key={column.key}
            checked={isVisible(column.key)}
            disabled={column.alwaysVisible}
            onCheckedChange={() => onToggle(column.key)}
            onSelect={(event) => event.preventDefault()}
          >
            {column.header}
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onReset}>Reset to default</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

interface PaginationProps {
  page: number
  pageCount: number
  pageSize: number
  rangeStart: number
  rangeEnd: number
  totalRows: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  itemLabel?: string
}

const PAGE_SIZES = [10, 25, 50, 100]

export function DataTablePagination({
  page,
  pageCount,
  pageSize,
  rangeStart,
  rangeEnd,
  totalRows,
  onPageChange,
  onPageSizeChange,
  itemLabel = 'rows',
}: PaginationProps) {
  return (
    <div className="border-line flex flex-wrap items-center justify-between gap-3 border-t px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span className="text-ink-soft text-[12px]">Rows per page</span>
        <Select
          value={String(pageSize)}
          onValueChange={(value) => onPageSizeChange(Number(value))}
        >
          <SelectTrigger size="sm" className="h-8 w-[72px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PAGE_SIZES.map((size) => (
              <SelectItem key={size} value={String(size)}>
                {size}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <p className="text-ink-soft tnum text-[12px]">
        {totalRows === 0
          ? `No ${itemLabel}`
          : `${rangeStart}–${rangeEnd} of ${totalRows} ${itemLabel}`}
      </p>

      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon-sm"
          onClick={() => onPageChange(1)}
          disabled={page <= 1}
          aria-label="First page"
        >
          <ChevronsLeft className="size-4" aria-hidden />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-4" aria-hidden />
        </Button>
        <span className="text-ink-soft tnum px-2 text-[12px]">
          Page {page} of {pageCount}
        </span>
        <Button
          variant="outline"
          size="icon-sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pageCount}
          aria-label="Next page"
        >
          <ChevronRight className="size-4" aria-hidden />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          onClick={() => onPageChange(pageCount)}
          disabled={page >= pageCount}
          aria-label="Last page"
        >
          <ChevronsRight className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  )
}
