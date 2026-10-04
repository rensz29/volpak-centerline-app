import { RotateCcw, Search, SlidersHorizontal, X } from 'lucide-react'

import { ScopeSelectors } from '@/components/layout/ScopeSelectors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ALL } from '@/context/ScopeContext'
import type { UseCenterlineFiltersResult } from '@/hooks/useCenterlineFilters'
import {
  CATEGORY_LABELS,
  PARAMETER_CATEGORIES,
  PARAMETER_STATUSES,
  type ParameterCategory,
  type ParameterStatus,
  type Sku,
} from '@/types'
import { cn } from '@/utils/cn'
import { STATUS_META } from '@/utils/status'

interface FilterToolbarProps {
  filters: UseCenterlineFiltersResult
  skus: readonly Sku[]
  onResetAll: () => void
}

export function FilterToolbar({ filters, skus, onResetAll }: FilterToolbarProps) {
  const hasFilters = filters.activeFilterCount > 0

  return (
    <div className="bg-surface border-line shadow-card rounded-lg border">
      <div className="border-line flex items-center justify-between gap-3 border-b px-4 py-2.5">
        <div className="text-ink-soft flex items-center gap-2 text-[13px] font-medium">
          <SlidersHorizontal className="size-4" aria-hidden />
          Filters
          {hasFilters && (
            <span className="bg-brand-surface text-brand tnum rounded px-1.5 py-0.5 text-[11px] font-semibold">
              {filters.activeFilterCount} active
            </span>
          )}
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={onResetAll}
          disabled={!hasFilters}
          className="gap-1.5"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          Reset filters
        </Button>
      </div>

      <div className="flex flex-col gap-3 p-4">
        {/* Plant scope repeats here on small screens where the header hides it. */}
        <div className="md:hidden">
          <FilterField label="Plant scope">
            <ScopeSelectors className="flex-wrap [&_button]:bg-surface [&_button]:border-line [&_button]:text-ink [&_svg]:text-ink-muted [&_button]:hover:bg-surface-muted" />
          </FilterField>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <FilterField label="SKU">
            <Select value={filters.filters.skuId} onValueChange={filters.setSkuId}>
              <SelectTrigger aria-label="Filter by SKU">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All SKUs</SelectItem>
                {skus.map((sku) => (
                  <SelectItem key={sku.id} value={sku.id}>
                    {sku.code} — {sku.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="Parameter category">
            <Select
              value={filters.filters.category}
              onValueChange={(value) =>
                filters.setCategory(value as ParameterCategory | typeof ALL)
              }
            >
              <SelectTrigger aria-label="Filter by parameter category">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All categories</SelectItem>
                {PARAMETER_CATEGORIES.map((category) => (
                  <SelectItem key={category} value={category}>
                    {CATEGORY_LABELS[category]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="Status">
            <Select
              value={filters.filters.status}
              onValueChange={(value) =>
                filters.setStatus(value as ParameterStatus | typeof ALL)
              }
            >
              <SelectTrigger aria-label="Filter by status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All statuses</SelectItem>
                {PARAMETER_STATUSES.map((status) => (
                  <SelectItem key={status} value={status}>
                    <span className="flex items-center gap-2">
                      <span
                        className={cn('size-2 rounded-full', STATUS_META[status].dot)}
                        aria-hidden
                      />
                      {STATUS_META[status].label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="Search">
            <div className="relative">
              <Search
                className="text-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
                aria-hidden
              />
              <Input
                value={filters.filters.search}
                onChange={(event) => filters.setSearch(event.target.value)}
                placeholder="Parameter, machine, SKU…"
                aria-label="Search parameters"
                className="pr-9 pl-9"
              />
              {filters.filters.search !== '' && (
                <button
                  type="button"
                  onClick={() => filters.setSearch('')}
                  className="text-ink-muted hover:text-ink focus-visible:ring-brand-ring absolute top-1/2 right-2 grid size-6 -translate-y-1/2 place-items-center rounded transition-colors focus-visible:ring-2 focus-visible:outline-none"
                  aria-label="Clear search"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </div>
          </FilterField>
        </div>
      </div>
    </div>
  )
}

function FilterField({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="min-w-0">
      <span className="micro-label mb-1.5 block">{label}</span>
      {children}
    </div>
  )
}
