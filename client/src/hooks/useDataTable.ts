import { useCallback, useMemo, useState } from 'react'

export type SortDirection = 'asc' | 'desc'

export interface SortState<K extends string> {
  key: K
  direction: SortDirection
}

/** Column metadata the table engine needs; rendering stays with the caller. */
export interface DataTableColumn<T, K extends string = string> {
  key: K
  header: string
  /** Sortable columns supply the value to compare. */
  sortValue?: (row: T) => string | number | null
  /** Columns included in the global search supply their searchable text. */
  searchValue?: (row: T) => string
  /** Columns the user may not hide, such as the primary identifier. */
  alwaysVisible?: boolean
  defaultHidden?: boolean
}

export interface UseDataTableOptions<T, K extends string> {
  data: readonly T[]
  columns: ReadonlyArray<DataTableColumn<T, K>>
  getRowId: (row: T) => string
  initialSort?: SortState<K>
  initialPageSize?: number
  /**
   * Supply this to drive the search term from outside — the Digital Centerline
   * page keeps its search field in the filter toolbar alongside the other
   * filters rather than in the table header.
   */
  search?: string
}

export interface UseDataTableResult<T, K extends string> {
  rows: T[]
  allFilteredRows: T[]
  sort: SortState<K> | null
  toggleSort: (key: K) => void
  search: string
  setSearch: (value: string) => void
  page: number
  pageCount: number
  pageSize: number
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  totalRows: number
  rangeStart: number
  rangeEnd: number
  visibleColumns: ReadonlyArray<DataTableColumn<T, K>>
  isColumnVisible: (key: K) => boolean
  toggleColumn: (key: K) => void
  resetColumns: () => void
  selectedIds: ReadonlySet<string>
  isSelected: (row: T) => boolean
  toggleRow: (row: T) => void
  toggleAllOnPage: () => void
  clearSelection: () => void
  allOnPageSelected: boolean
  someOnPageSelected: boolean
}

/**
 * Client-side sorting, searching, pagination, column visibility and row
 * selection over an in-memory array.
 *
 * Deliberately hand-rolled rather than pulling in a table library: the dataset
 * is a few hundred rows held in React state, and both tables in the app need
 * exactly this set of behaviours and nothing more.
 */
export function useDataTable<T, K extends string = string>({
  data,
  columns,
  getRowId,
  initialSort,
  initialPageSize = 10,
  search: controlledSearch,
}: UseDataTableOptions<T, K>): UseDataTableResult<T, K> {
  const [sort, setSort] = useState<SortState<K> | null>(initialSort ?? null)
  const [internalSearch, setSearchValue] = useState('')
  const search = controlledSearch ?? internalSearch
  const [page, setPage] = useState(1)
  const [pageSize, setPageSizeValue] = useState(initialPageSize)
  const [hiddenColumns, setHiddenColumns] = useState<ReadonlySet<K>>(
    () => new Set(columns.filter((c) => c.defaultHidden).map((c) => c.key)),
  )
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set())

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (term === '') return [...data]

    const searchable = columns.filter((column) => column.searchValue)
    return data.filter((row) =>
      searchable.some((column) =>
        (column.searchValue?.(row) ?? '').toLowerCase().includes(term),
      ),
    )
  }, [data, columns, search])

  const sorted = useMemo(() => {
    if (!sort) return filtered
    const column = columns.find((c) => c.key === sort.key)
    if (!column?.sortValue) return filtered

    const factor = sort.direction === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const left = column.sortValue?.(a) ?? null
      const right = column.sortValue?.(b) ?? null

      // Missing values always sort last, whichever direction is active, so a
      // No Data row never displaces real readings from the top of the table.
      if (left === null && right === null) return 0
      if (left === null) return 1
      if (right === null) return -1

      if (typeof left === 'number' && typeof right === 'number') {
        return (left - right) * factor
      }
      return String(left).localeCompare(String(right), undefined, { numeric: true }) * factor
    })
  }, [filtered, sort, columns])

  const totalRows = sorted.length
  const pageCount = Math.max(1, Math.ceil(totalRows / pageSize))

  // Both adjustments below run during render rather than in an effect: they
  // derive state from changed inputs, so an effect would render once with a
  // stale page before correcting itself.

  // Clamp the page whenever filtering shrinks the result set beneath it.
  const [lastPageCount, setLastPageCount] = useState(pageCount)
  if (pageCount !== lastPageCount) {
    setLastPageCount(pageCount)
    if (page > pageCount) setPage(pageCount)
  }

  // A new search term always returns to the first page, whether the term is
  // controlled from outside or typed into the table's own field.
  const [lastSearch, setLastSearch] = useState(search)
  if (search !== lastSearch) {
    setLastSearch(search)
    setPage(1)
  }

  const safePage = Math.min(page, pageCount)
  const rows = useMemo(
    () => sorted.slice((safePage - 1) * pageSize, safePage * pageSize),
    [sorted, safePage, pageSize],
  )

  const toggleSort = useCallback((key: K) => {
    setSort((current) => {
      if (current?.key !== key) return { key, direction: 'asc' }
      if (current.direction === 'asc') return { key, direction: 'desc' }
      return null // third click clears the sort
    })
  }, [])

  const setSearch = useCallback((value: string) => {
    setSearchValue(value)
    setPage(1)
  }, [])

  const setPageSize = useCallback((size: number) => {
    setPageSizeValue(size)
    setPage(1)
  }, [])

  const isColumnVisible = useCallback(
    (key: K) => !hiddenColumns.has(key),
    [hiddenColumns],
  )

  const toggleColumn = useCallback(
    (key: K) => {
      const column = columns.find((c) => c.key === key)
      if (column?.alwaysVisible) return
      setHiddenColumns((current) => {
        const next = new Set(current)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      })
    },
    [columns],
  )

  const resetColumns = useCallback(() => {
    setHiddenColumns(new Set(columns.filter((c) => c.defaultHidden).map((c) => c.key)))
  }, [columns])

  const visibleColumns = useMemo(
    () => columns.filter((column) => !hiddenColumns.has(column.key)),
    [columns, hiddenColumns],
  )

  const isSelected = useCallback(
    (row: T) => selectedIds.has(getRowId(row)),
    [selectedIds, getRowId],
  )

  const toggleRow = useCallback(
    (row: T) => {
      const id = getRowId(row)
      setSelectedIds((current) => {
        const next = new Set(current)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
    },
    [getRowId],
  )

  const pageIds = useMemo(() => rows.map(getRowId), [rows, getRowId])
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id))
  const someOnPageSelected = pageIds.some((id) => selectedIds.has(id))

  const toggleAllOnPage = useCallback(() => {
    setSelectedIds((current) => {
      const next = new Set(current)
      const everySelected = pageIds.length > 0 && pageIds.every((id) => next.has(id))
      for (const id of pageIds) {
        if (everySelected) next.delete(id)
        else next.add(id)
      }
      return next
    })
  }, [pageIds])

  const clearSelection = useCallback(() => setSelectedIds(new Set()), [])

  return {
    rows,
    allFilteredRows: sorted,
    sort,
    toggleSort,
    search,
    setSearch,
    page: safePage,
    pageCount,
    pageSize,
    setPage,
    setPageSize,
    totalRows,
    rangeStart: totalRows === 0 ? 0 : (safePage - 1) * pageSize + 1,
    rangeEnd: Math.min(safePage * pageSize, totalRows),
    visibleColumns,
    isColumnVisible,
    toggleColumn,
    resetColumns,
    selectedIds,
    isSelected,
    toggleRow,
    toggleAllOnPage,
    clearSelection,
    allOnPageSelected,
    someOnPageSelected,
  }
}
