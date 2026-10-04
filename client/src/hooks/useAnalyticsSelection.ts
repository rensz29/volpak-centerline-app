import { useCallback, useMemo, useState } from 'react'

import { ALL } from '@/context/ScopeContext'
import type { ParameterCode, ProcessSample, Shift } from '@/types'

export type GroupBy = 'sku' | 'machine' | 'shift'

export interface AnalyticsLocalFilters {
  skuId: string
  shift: Shift | typeof ALL
  startDate: string
  endDate: string
}

export interface AnalyticsSelection {
  xAxis: ParameterCode
  yAxis: ParameterCode
  groupBy: GroupBy
  selected: ReadonlySet<ParameterCode>
}

/**
 * Defaults are chosen so the page opens on a meaningful analysis rather than an
 * empty workspace: hopper pressure against discharge weight is the relationship
 * the dataset is built around.
 *
 * The SKU defaults to a single product on purpose. Pooling several SKUs mixes
 * recipes running at very different magnitudes (a 500 g doypack beside a 6 g
 * stickpack), and the resulting between-group spread inflates any correlation
 * computed over the combination. Scoping to one SKU asks a question that has a
 * real answer; the insight card warns whenever the selection widens past it.
 */
const DEFAULT_SELECTION: AnalyticsSelection = {
  xAxis: 'hopper_pressure',
  yAxis: 'discharge_weight',
  groupBy: 'sku',
  selected: new Set<ParameterCode>(['hopper_pressure', 'discharge_weight']),
}

const DEFAULT_SKU_ID = 'sku-1'

interface Options {
  samples: readonly ProcessSample[]
  factoryId: string
  lineId: string
  machineId: string
  windowStart: string
  windowEnd: string
}

export interface UseAnalyticsSelectionResult {
  selection: AnalyticsSelection
  filters: AnalyticsLocalFilters
  setXAxis: (code: ParameterCode) => void
  setYAxis: (code: ParameterCode) => void
  setGroupBy: (value: GroupBy) => void
  toggleParameter: (code: ParameterCode) => void
  clearSelection: () => void
  setSkuId: (value: string) => void
  setShift: (value: Shift | typeof ALL) => void
  setStartDate: (value: string) => void
  setEndDate: (value: string) => void
  resetFilters: () => void
  activeFilterCount: number
  filteredSamples: ProcessSample[]
  /** True when the filtered set mixes SKUs, which confounds the correlation. */
  spansMultipleSkus: boolean
  spansMultipleMachines: boolean
}

export function useAnalyticsSelection({
  samples,
  factoryId,
  lineId,
  machineId,
  windowStart,
  windowEnd,
}: Options): UseAnalyticsSelectionResult {
  const initialFilters = useMemo<AnalyticsLocalFilters>(
    () => ({
      skuId: DEFAULT_SKU_ID,
      shift: ALL,
      startDate: windowStart,
      endDate: windowEnd,
    }),
    [windowStart, windowEnd],
  )

  const [selection, setSelection] = useState<AnalyticsSelection>(DEFAULT_SELECTION)
  const [filters, setFilters] = useState<AnalyticsLocalFilters>(initialFilters)

  const filteredSamples = useMemo(() => {
    const from = filters.startDate === '' ? null : new Date(`${filters.startDate}T00:00:00`)
    const to = filters.endDate === '' ? null : new Date(`${filters.endDate}T23:59:59.999`)

    return samples.filter((sample) => {
      if (factoryId !== ALL && sample.factoryId !== factoryId) return false
      if (lineId !== ALL && sample.lineId !== lineId) return false
      if (machineId !== ALL && sample.machineId !== machineId) return false
      if (filters.skuId !== ALL && sample.skuId !== filters.skuId) return false
      if (filters.shift !== ALL && sample.shift !== filters.shift) return false

      const at = new Date(sample.timestamp)
      if (from && at < from) return false
      if (to && at > to) return false
      return true
    })
  }, [samples, factoryId, lineId, machineId, filters])

  const spansMultipleSkus = useMemo(
    () => new Set(filteredSamples.map((s) => s.skuId)).size > 1,
    [filteredSamples],
  )

  const spansMultipleMachines = useMemo(
    () => new Set(filteredSamples.map((s) => s.machineId)).size > 1,
    [filteredSamples],
  )

  const setXAxis = useCallback((code: ParameterCode) => {
    setSelection((current) => ({
      ...current,
      xAxis: code,
      selected: new Set(current.selected).add(code),
    }))
  }, [])

  const setYAxis = useCallback((code: ParameterCode) => {
    setSelection((current) => ({
      ...current,
      yAxis: code,
      selected: new Set(current.selected).add(code),
    }))
  }, [])

  const setGroupBy = useCallback(
    (groupBy: GroupBy) => setSelection((current) => ({ ...current, groupBy })),
    [],
  )

  const toggleParameter = useCallback((code: ParameterCode) => {
    setSelection((current) => {
      const next = new Set(current.selected)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return { ...current, selected: next }
    })
  }, [])

  const clearSelection = useCallback(() => {
    setSelection((current) => ({
      ...current,
      selected: new Set<ParameterCode>([current.xAxis, current.yAxis]),
    }))
  }, [])

  const setSkuId = useCallback(
    (skuId: string) => setFilters((current) => ({ ...current, skuId })),
    [],
  )
  const setShift = useCallback(
    (shift: Shift | typeof ALL) => setFilters((current) => ({ ...current, shift })),
    [],
  )
  const setStartDate = useCallback(
    (startDate: string) => setFilters((current) => ({ ...current, startDate })),
    [],
  )
  const setEndDate = useCallback(
    (endDate: string) => setFilters((current) => ({ ...current, endDate })),
    [],
  )
  const resetFilters = useCallback(
    () => setFilters(initialFilters),
    [initialFilters],
  )

  const activeFilterCount =
    (filters.skuId !== initialFilters.skuId ? 1 : 0) +
    (filters.shift !== ALL ? 1 : 0) +
    (filters.startDate !== initialFilters.startDate ? 1 : 0) +
    (filters.endDate !== initialFilters.endDate ? 1 : 0)

  return {
    selection,
    filters,
    setXAxis,
    setYAxis,
    setGroupBy,
    toggleParameter,
    clearSelection,
    setSkuId,
    setShift,
    setStartDate,
    setEndDate,
    resetFilters,
    activeFilterCount,
    filteredSamples,
    spansMultipleSkus,
    spansMultipleMachines,
  }
}
