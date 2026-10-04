import { useCallback, useMemo, useState } from 'react'

import { ALL } from '@/context/ScopeContext'
import type { CenterlineRow, ParameterCategory, ParameterStatus } from '@/types'

export interface CenterlineFilterState {
  skuId: string
  category: ParameterCategory | typeof ALL
  status: ParameterStatus | typeof ALL
  search: string
}

const INITIAL: CenterlineFilterState = {
  skuId: ALL,
  category: ALL,
  status: ALL,
  search: '',
}

export interface UseCenterlineFiltersResult {
  filters: CenterlineFilterState
  setSkuId: (value: string) => void
  setCategory: (value: ParameterCategory | typeof ALL) => void
  setStatus: (value: ParameterStatus | typeof ALL) => void
  setSearch: (value: string) => void
  reset: () => void
  activeFilterCount: number
  rows: CenterlineRow[]
  /** Rows narrowed by scope only, so status counts stay stable while filtering. */
  scopedRows: CenterlineRow[]
}

interface Options {
  rows: readonly CenterlineRow[]
  factoryId: string
  lineId: string
  machineId: string
}

/**
 * Two-stage narrowing. The plant scope (factory/line/machine) is applied first
 * and drives the summary cards; the toolbar filters are applied on top and drive
 * the table. Keeping them separate means clicking a status card to filter the
 * table does not also change the counts on the cards themselves.
 */
export function useCenterlineFilters({
  rows,
  factoryId,
  lineId,
  machineId,
}: Options): UseCenterlineFiltersResult {
  const [filters, setFilters] = useState<CenterlineFilterState>(INITIAL)

  const scopedRows = useMemo(
    () =>
      rows.filter((row) => {
        if (factoryId !== ALL && row.reading.factoryId !== factoryId) return false
        if (lineId !== ALL && row.reading.lineId !== lineId) return false
        if (machineId !== ALL && row.reading.machineId !== machineId) return false
        return true
      }),
    [rows, factoryId, lineId, machineId],
  )

  const filteredRows = useMemo(
    () =>
      scopedRows.filter((row) => {
        if (filters.skuId !== ALL && row.reading.skuId !== filters.skuId) return false
        if (filters.category !== ALL && row.parameter.category !== filters.category) {
          return false
        }
        if (filters.status !== ALL && row.status !== filters.status) return false
        return true
      }),
    [scopedRows, filters],
  )

  const setSkuId = useCallback(
    (skuId: string) => setFilters((current) => ({ ...current, skuId })),
    [],
  )
  const setCategory = useCallback(
    (category: ParameterCategory | typeof ALL) =>
      setFilters((current) => ({ ...current, category })),
    [],
  )
  const setStatus = useCallback(
    (status: ParameterStatus | typeof ALL) =>
      setFilters((current) => ({ ...current, status })),
    [],
  )
  const setSearch = useCallback(
    (search: string) => setFilters((current) => ({ ...current, search })),
    [],
  )
  const reset = useCallback(() => setFilters(INITIAL), [])

  const activeFilterCount =
    (filters.skuId !== ALL ? 1 : 0) +
    (filters.category !== ALL ? 1 : 0) +
    (filters.status !== ALL ? 1 : 0) +
    (filters.search.trim() !== '' ? 1 : 0)

  return {
    filters,
    setSkuId,
    setCategory,
    setStatus,
    setSearch,
    reset,
    activeFilterCount,
    rows: filteredRows,
    scopedRows,
  }
}
