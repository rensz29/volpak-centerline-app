/** Display formatting. All measured values render through here so decimals and
 *  units stay consistent between tables, cards, charts and CSV exports. */

const NO_VALUE = '—'

export function formatNumber(value: number | null, decimals = 1): string {
  if (value === null || Number.isNaN(value)) return NO_VALUE
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function formatValue(
  value: number | null,
  unit: string,
  decimals = 1,
): string {
  if (value === null || Number.isNaN(value)) return NO_VALUE
  return `${formatNumber(value, decimals)}${unitSuffix(unit)}`
}

/** Percent and degree signs sit tight against the number; words get a space. */
export function unitSuffix(unit: string): string {
  if (unit === '') return ''
  return unit === '%' || unit.startsWith('°') ? unit : ` ${unit}`
}

/** Signed deviation — the sign matters, so it is always shown. */
export function formatDeviation(value: number | null, decimals = 1): string {
  if (value === null || Number.isNaN(value)) return NO_VALUE
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${formatNumber(Math.abs(value), decimals)}`
}

export function formatDeviationPct(value: number | null, decimals = 1): string {
  if (value === null || Number.isNaN(value)) return NO_VALUE
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${formatNumber(Math.abs(value), decimals)}%`
}

export function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NO_VALUE
  return date.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NO_VALUE
  return date.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NO_VALUE
  return date.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

/** For an ISO string into a `<input type="date">` value. */
export function toDateInputValue(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

export function formatRelativeTime(iso: string, now = Date.now()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NO_VALUE

  const diffSeconds = Math.round((now - date.getTime()) / 1000)
  const future = diffSeconds < 0
  const seconds = Math.abs(diffSeconds)

  if (seconds < 45) return future ? 'in a moment' : 'just now'

  const units: ReadonlyArray<[label: string, seconds: number]> = [
    ['d', 86_400],
    ['h', 3_600],
    ['m', 60],
  ]

  for (const [label, unitSeconds] of units) {
    if (seconds >= unitSeconds) {
      const amount = Math.floor(seconds / unitSeconds)
      return future ? `in ${amount}${label}` : `${amount}${label} ago`
    }
  }
  return future ? 'in a moment' : 'just now'
}

export function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export { NO_VALUE }
