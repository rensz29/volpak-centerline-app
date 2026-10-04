export interface CsvColumn<T> {
  header: string
  value: (row: T) => string | number | null
}

/**
 * RFC 4180 escaping: wrap in quotes when the cell contains a delimiter, quote
 * or newline, and double any embedded quotes. A leading `=`, `+`, `-` or `@` is
 * prefixed with a tab so spreadsheets treat it as text rather than a formula.
 */
function escapeCell(input: string | number | null): string {
  if (input === null) return ''
  const raw = String(input)
  const guarded = /^[=+\-@]/.test(raw) ? `\t${raw}` : raw
  if (/["\n\r,]/.test(guarded)) {
    return `"${guarded.replace(/"/g, '""')}"`
  }
  return guarded
}

export function toCsv<T>(rows: readonly T[], columns: readonly CsvColumn<T>[]): string {
  const header = columns.map((column) => escapeCell(column.header)).join(',')
  const body = rows.map((row) =>
    columns.map((column) => escapeCell(column.value(row))).join(','),
  )
  return [header, ...body].join('\r\n')
}

/** Triggers a client-side download; nothing leaves the browser. */
export function downloadCsv<T>(
  filename: string,
  rows: readonly T[],
  columns: readonly CsvColumn<T>[],
): void {
  // The BOM makes Excel open UTF-8 correctly on Windows.
  const blob = new Blob(['﻿', toCsv(rows, columns)], {
    type: 'text/csv;charset=utf-8;',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function timestampedFilename(prefix: string): string {
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')
  return `${prefix}-${stamp}.csv`
}
